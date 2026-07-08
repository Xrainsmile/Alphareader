"""News & Pipeline API endpoints."""

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import and_, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_key
from app.database import get_db
from app.models.news import News
from app.redis import get_redis
from app.services.pipeline import run_pipeline
from app.services.search import get_hot_topics, get_search_suggestions, search_news
from app.utils.ranking import calculate_ranking_score, gravity_sql_expression
from app.schemas.response import APIResponse, PaginatedResponse

logger = logging.getLogger("alphareader.api.news")


class SortMode(str, Enum):
    """新闻列表排序模式。"""
    HOT = "hot"           # Hacker Gravity: HN 原版重力公式，ai_score 作为 points
    LATEST = "latest"     # 时间倒序（最新优先）
    SCORE = "score"       # AI 评分倒序（最高优先）

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
async def trigger_pipeline(background_tasks: BackgroundTasks, _: str | None = Depends(require_api_key)):
    """Manually trigger the news pipeline (runs in background to avoid timeout)."""
    if _pipeline_status["running"]:
        return APIResponse(code=1, message="Pipeline already running, please wait")

    background_tasks.add_task(_run_pipeline_bg)
    return APIResponse(message="Pipeline started in background. Check /pipeline/status for results.")


@router.get("/pipeline/status")
async def pipeline_status(_: str | None = Depends(require_api_key)):
    """Check the status of the last pipeline run."""
    return APIResponse(data={
        "running": _pipeline_status["running"],
        "last_result": _pipeline_status["last_result"],
    })


@router.delete("/pipeline/cache")
async def clear_dedup_cache(_: str | None = Depends(require_api_key)):
    """Clear the Redis dedup cache so next run re-fetches all news."""
    r = get_redis()
    deleted = await r.delete("alphareader:seen_urls")
    return APIResponse(data={"keys_deleted": deleted}, message="Dedup cache cleared")


@router.get("/")
async def list_news(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    min_score: int = Query(5, ge=0, le=10),
    source: str | None = Query(None),
    category: str | None = Query(None, description="分类筛选: 财经 / 科技"),
    sector: str | None = Query(None),
    sort: SortMode = Query(SortMode.HOT, description="Sort mode: hot (gravity decay), latest, score"),
    gravity: float = Query(1.8, ge=0.5, le=5.0, description="Gravity factor for hot sort"),
    max_age_hours: int | None = Query(72, ge=1, le=720, description="Max news age in hours; omit for unlimited"),
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(require_api_key),
):
    """获取评分新闻列表（分页）。

    排序模式:
    - **hot** (默认): Hacker Gravity — 直接复用 Hacker News 重力公式
      rank = (points-1)/(hours+2)^gravity，ai_score 作为 points，gravity 默认 1.8。
    - **latest**: 时间倒序，最新优先。
    - **score**: AI 评分倒序，最高优先。
    """
    conditions = [News.ai_score >= min_score]
    if source:
        conditions.append(News.source == source)
    if category:
        conditions.append(News.category == category)
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
        order_clause = desc(func.coalesce(News.published_at, News.created_at))
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
            "category": n.category,
            "url": n.url,
            "ai_score": n.ai_score,
            "ranking_score": ranking_score,
            "ai_summary": n.ai_summary,
            "why_it_matters": n.why_it_matters,
            "tags": n.tags,
            "related_to_id": str(n.related_to_id) if n.related_to_id else None,
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "sentiment_score": n.sentiment_score,
            "surprise_factor": n.surprise_factor,
            "catalyst_type": n.catalyst_type,
            "sentiment_entity": n.sentiment_entity,
        })

    # If SQL-level gravity sort wasn't available, sort in Python
    if use_python_sort and sort == SortMode.HOT:
        items.sort(key=lambda x: x["ranking_score"], reverse=True)

    return PaginatedResponse(
        data=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/hot-topics")
async def hot_topics(
    limit: int = Query(10, ge=1, le=50),
    min_score: int = Query(5, ge=0, le=10),
    category: str | None = Query(None, description="分类筛选: 财经 / 科技"),
    window_hours: int = Query(72, ge=1, le=720, description="统计时间窗口（小时）"),
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(require_api_key),
):
    """多信源热点榜 — 聚合同一事件的多家媒体报道，按信源数排序。

    利用 related_to_id 父子关系：父条目（related_to_id 为 NULL）下挂的
    关联报道（related_to_id 指向父）视为"同一事件的不同信源"。
    仅保留"信源数 ≥ 2"的事件，按信源数降序排列，直观呈现"多方在谈什么事"。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    conditions = [
        "n.related_to_id IS NULL",
        "n.ai_score >= :min_score",
        "n.created_at >= :cutoff",
    ]
    params: dict = {"min_score": min_score, "cutoff": cutoff, "limit": limit}
    if category:
        conditions.append("n.category = :category")
        params["category"] = category

    sql = f"""
    WITH parents AS (
        SELECT n.id, n.title, n.source, n.url, n.ai_score, n.ai_summary,
               n.tags, n.published_at, n.created_at, n.why_it_matters
        FROM news n
        WHERE {' AND '.join(conditions)}
    ),
    child_agg AS (
        SELECT c.related_to_id AS pid,
               COUNT(*) AS cnt,
               array_agg(DISTINCT c.source) AS child_sources,
               array_agg(c.title) AS child_titles
        FROM news c
        WHERE c.related_to_id IS NOT NULL
        GROUP BY c.related_to_id
    )
    SELECT
        p.id, p.title, p.source, p.url, p.ai_score, p.ai_summary, p.tags,
        p.published_at, p.created_at, p.why_it_matters,
        (COALESCE(ca.cnt, 0) + 1) AS source_count,
        COALESCE(ca.child_sources, ARRAY[]::text[]) AS child_sources,
        COALESCE(ca.child_titles, ARRAY[]::text[]) AS child_titles
    FROM parents p
    LEFT JOIN child_agg ca ON ca.pid = p.id
    WHERE COALESCE(ca.cnt, 0) >= 1
    ORDER BY source_count DESC, p.ai_score DESC, p.published_at DESC
    LIMIT :limit
    """
    try:
        result = await db.execute(text(sql), params)
        rows = result.mappings().all()
    except Exception as e:
        logger.warning("hot-topics query failed: %s", e)
        return APIResponse(data={"items": [], "total": 0})

    items = []
    for r in rows:
        child_sources = list(r["child_sources"] or [])
        seen: set[str] = set()
        child_sources_unique = []
        for s in child_sources:
            if s and s not in seen:
                seen.add(s)
                child_sources_unique.append(s)
        items.append({
            "id": str(r["id"]),
            "title": r["title"],
            "source": r["source"],
            "url": r["url"],
            "ai_score": r["ai_score"],
            "ai_summary": r["ai_summary"],
            "why_it_matters": r["why_it_matters"],
            "tags": r["tags"],
            "published_at": r["published_at"].isoformat() if r["published_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            # 信源数 = 父条目自身(1) + 关联报道数
            "source_count": int(r["source_count"]),
            "child_sources": child_sources_unique,
            "child_titles": [t for t in (r["child_titles"] or [])][:6],
        })

    return APIResponse(data={"items": items, "total": len(items)})


# ── 搜索 API ──


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=200, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    min_score: int = Query(5, ge=0, le=10),
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(require_api_key),
):
    """搜索新闻。

    排序算法: 混合排序 = 文本相关度(ts_rank_cd) × 质量权重(ln(ai_score+1)) × 时间衰减
    支持中英文关键词搜索和模糊匹配。
    返回结果包含标题和摘要的关键词高亮。
    """
    result = await search_news(db, q, limit=limit, offset=offset, min_score=min_score)
    return APIResponse(data=result)


@router.get("/search/suggest")
async def search_suggest(
    q: str = Query(..., min_length=1, max_length=100, description="搜索前缀"),
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(require_api_key),
):
    """搜索建议 — 根据输入前缀返回自动补全建议。"""
    suggestions = await get_search_suggestions(db, q)
    return APIResponse(data={"suggestions": suggestions})


@router.get("/search/hot")
async def search_hot(
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(require_api_key),
):
    """热门话题 — 过去 24 小时高分新闻的高频标签，用于搜索推荐。"""
    topics = await get_hot_topics(db)
    return APIResponse(data={"topics": topics})
