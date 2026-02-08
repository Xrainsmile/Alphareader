"""News & Pipeline API endpoints."""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.news import News
from app.redis import get_redis
from app.services.pipeline import run_pipeline

logger = logging.getLogger("alphareader.api.news")

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
    min_score: int = Query(6, ge=0, le=10),
    source: str | None = Query(None),
    sector: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List scored news, ordered by ai_score DESC."""
    conditions = [News.ai_score >= min_score]
    if source:
        conditions.append(News.source == source)
    if sector:
        conditions.append(News.tags.any(sector))

    stmt = (
        select(News)
        .where(and_(*conditions))
        .order_by(desc(News.ai_score), desc(News.created_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "id": str(n.id),
            "title": n.title,
            "source": n.source,
            "url": n.url,
            "ai_score": n.ai_score,
            "ai_summary": n.ai_summary,
            "tags": n.tags,
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in rows
    ]
