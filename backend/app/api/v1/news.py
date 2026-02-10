"""News & Pipeline API endpoints."""

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import and_, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.news import News
from app.redis import get_redis
from app.services.pipeline import run_pipeline
from app.utils.ranking import calculate_ranking_score, gravity_sql_expression

logger = logging.getLogger("alphareader.api.news")


class SortMode(str, Enum):
    """News list sort modes."""
    HOT = "hot"           # Gravity algorithm: score decays with time
    LATEST = "latest"     # Pure chronological (newest first)
    SCORE = "score"       # Pure AI score (highest first, legacy default)

router = APIRouter(prefix="/news", tags=["news"])

# Track background pipeline status
_pipeline_status: dict = {"running": False, "last_result": None}


async def _run_pipeline_bg():
    """Run pipeline in background, update status when done."""
    global _pipeline_status
    _pipeline_status["running"] = True
    try:
        result = await run_pipeline()
        _pipeline_status["last_result"] = result
        logger.info("Background pipeline done: %s", result)
    except Exception as e:
        _pipeline_status["last_result"] = {"error": str(e)}
        logger.exception("Background pipeline failed: %s", e)
    finally:
        _pipeline_status["running"] = False


@router.post("/pipeline/run")
async def trigger_pipeline(background_tasks: BackgroundTasks):
    """Manually trigger the news pipeline (runs in background to avoid timeout)."""
    if _pipeline_status["running"]:
        return {"message": "Pipeline already running, please wait"}

    background_tasks.add_task(_run_pipeline_bg)
    return {"message": "Pipeline started in background. Check /pipeline/status for results."}


@router.get("/pipeline/status")
async def pipeline_status():
    """Check the status of the last pipeline run."""
    return {
        "running": _pipeline_status["running"],
        "last_result": _pipeline_status["last_result"],
    }


@router.delete("/pipeline/cache")
async def clear_dedup_cache():
    """Clear the Redis dedup cache so next run re-fetches all news."""
    r = get_redis()
    deleted = await r.delete("alphareader:seen_urls")
    return {"message": "Dedup cache cleared", "keys_deleted": deleted}


@router.get("/")
async def list_news(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    min_score: int = Query(6, ge=0, le=10),
    source: str | None = Query(None),
    sector: str | None = Query(None),
    sort: SortMode = Query(SortMode.HOT, description="Sort mode: hot (gravity decay), latest, score"),
    gravity: float = Query(1.8, ge=0.5, le=5.0, description="Gravity factor for hot sort"),
    max_age_hours: int = Query(72, ge=1, le=720, description="Max news age in hours"),
    db: AsyncSession = Depends(get_db),
):
    """List scored news with pagination.

    Sort modes:
    - **hot** (default): Gravity algorithm — high-score recent news rank first,
      older news decays exponentially. Tuned for financial news (gravity=1.8).
    - **latest**: Pure chronological, newest first.
    - **score**: Pure AI score, highest first (legacy behavior).
    """
    conditions = [News.ai_score >= min_score]
    if source:
        conditions.append(News.source == source)
    if sector:
        conditions.append(News.tags.any(sector))

    # Time window filter: exclude news older than max_age_hours
    # Use Python-computed cutoff for cross-DB compatibility (SQLite + PostgreSQL)
    if max_age_hours:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        conditions.append(News.created_at >= cutoff_time)

    where_clause = and_(*conditions)

    # Get total count
    count_stmt = select(func.count()).select_from(News).where(where_clause)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Build ORDER BY based on sort mode
    # For HOT mode: try SQL-level gravity sort (PostgreSQL), fallback to Python sort
    use_python_sort = False
    if sort == SortMode.HOT:
        try:
            ranking_expr = text(gravity_sql_expression(
                score_column="ai_score",
                time_column="published_at",
                gravity=gravity,
            ))
            order_clause = desc(ranking_expr)
        except Exception:
            # Fallback for non-PostgreSQL (e.g. SQLite in tests)
            order_clause = desc(News.created_at)
            use_python_sort = True
    elif sort == SortMode.LATEST:
        order_clause = desc(News.created_at)
    else:  # SortMode.SCORE
        order_clause = desc(News.ai_score)

    # Get paginated items
    stmt = (
        select(News)
        .where(where_clause)
        .order_by(order_clause, desc(News.created_at))
        .offset(offset)
        .limit(limit)
    )

    try:
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
    except Exception:
        # SQL gravity expression failed at execution time (e.g. SQLite)
        # Fallback: fetch with simple ordering, sort in Python
        use_python_sort = True
        fallback_stmt = (
            select(News)
            .where(where_clause)
            .order_by(desc(News.created_at))
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(fallback_stmt)
        rows = list(result.scalars().all())

    # Compute ranking_score in Python for each item (for API response)
    items = []
    for n in rows:
        ranking_score = calculate_ranking_score(
            ai_score=n.ai_score or 0,
            publish_time=n.published_at,
            gravity=gravity,
        )
        items.append({
            "id": str(n.id),
            "title": n.title,
            "source": n.source,
            "url": n.url,
            "ai_score": n.ai_score,
            "ranking_score": ranking_score,
            "ai_summary": n.ai_summary,
            "tags": n.tags,
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        })

    # If SQL-level gravity sort wasn't available, sort in Python
    if use_python_sort and sort == SortMode.HOT:
        items.sort(key=lambda x: x["ranking_score"], reverse=True)

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort.value,
        "gravity": gravity,
        "max_age_hours": max_age_hours,
    }
