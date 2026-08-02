"""Events API — 事件化新闻接口（PRD 第三阶段）。

与 /news 的区别：
  /news   = 文章流（含子报道，旧前端兼容保留）
  /events = 事件流（仅聚合根 related_to_id IS NULL），
            按事件分页（一页 20 条 = 20 个事件），
            子报道只通过事件展开/详情/信源接口访问。

排序：
  important   = 重要（默认）：HN 重力公式，points = ai_score + min(独立信源数×0.5, 2)，
                时间取事件新鲜度（根与最新子报道之大者 / event_last_updated_at），
                多信源事件衰减更慢（gravity 1.2 vs 1.8）
  latest_update = 最新更新：event_last_updated_at / 最新子报道时间倒序
  first_seen  = 首次出现：event_first_seen_at / 根发布时间倒序
"""

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth import require_api_key
from app.database import get_db
from app.models.event_version import EventVersion
from app.models.news import News
from app.schemas.response import APIResponse, PaginatedResponse
from app.utils.ranking import calculate_ranking_score, gravity_sql_expression

logger = logging.getLogger("alphareader.api.events")

router = APIRouter(prefix="/events", tags=["events"])

# 与 list_news 同口径的事件排序参数
EVENT_BOOST_PER_SOURCE = 0.5
EVENT_BOOST_MAX = 2.0
EVENT_GRAVITY = 1.2
DEFAULT_GRAVITY = 1.8


class EventSortMode(str, Enum):
    IMPORTANT = "important"          # 重要（默认，重力排序）
    LATEST_UPDATE = "latest_update"  # 最新更新
    FIRST_SEEN = "first_seen"        # 首次出现


def _serialize_event(n: News, child_cnt: int, source_cnt: int,
                     child_max_pub, ranking_score: float | None) -> dict:
    """事件列表条目序列化：事件字段优先，回落到根报道字段。"""
    return {
        "id": str(n.id),
        # 事件标题/摘要优先，未合成的单信源事件回落到根报道
        "title": n.event_title or n.title,
        "summary": n.event_summary or n.ai_summary,
        "latest_change": n.event_latest_change,
        "why_important": n.event_why_important,
        "status": n.event_status,
        "is_synthesized": n.event_title is not None,
        "source": n.source,
        "category": n.category,
        "url": n.url,
        "ai_score": n.ai_score,
        "ranking_score": ranking_score,
        "is_highlight": bool(n.is_highlight),
        "tags": n.tags,
        # 报道总数 vs 独立信源数（同一媒体多篇只计 1）
        "article_count": child_cnt + 1,
        "source_count": source_cnt,
        "version": n.event_version,
        "first_seen_at": (n.event_first_seen_at or n.published_at or n.created_at).isoformat()
            if (n.event_first_seen_at or n.published_at or n.created_at) else None,
        "last_updated_at": (n.event_last_updated_at or child_max_pub
                            or n.published_at or n.created_at).isoformat()
            if (n.event_last_updated_at or child_max_pub
                or n.published_at or n.created_at) else None,
        "published_at": n.published_at.isoformat() if n.published_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/")
async def list_events(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: EventSortMode = Query(EventSortMode.IMPORTANT),
    max_age_hours: int | None = Query(24, ge=1, le=720),
    category: str | None = Query(None),
    min_score: int = Query(6, ge=0, le=10),
    status: str | None = Query(None, description="事件状态: new/developing/stable/resolved"),
    highlight_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(require_api_key),
):
    """事件列表——只返回事件根，按事件分页（一页 N 条 = N 个事件）。"""
    conditions = [
        News.related_to_id.is_(None),   # 只有事件根（PRD 6.1）
        News.ai_score >= min_score,
    ]
    if highlight_only:
        conditions.append(News.is_highlight == True)  # noqa: E712
    if category:
        conditions.append(News.category == category)
    if status:
        conditions.append(News.event_status == status)

    if max_age_hours:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        # 根超窗但窗口内仍有新子报道/有实质更新的事件保留（事件新鲜度）
        child_news = aliased(News)
        fresh_parents = (
            select(child_news.related_to_id)
            .where(child_news.related_to_id.isnot(None))
            .where(child_news.created_at >= cutoff_time)
            .distinct()
        )
        conditions.append(or_(
            News.created_at >= cutoff_time,
            News.event_last_updated_at >= cutoff_time,
            News.id.in_(fresh_parents),
        ))

    where_clause = and_(*conditions)

    count_stmt = select(func.count()).select_from(News).where(where_clause)
    total = (await db.execute(count_stmt)).scalar() or 0

    # 统一口径独立信源数：COUNT(DISTINCT source) WHERE id=根 OR related_to_id=根
    # （根报道来源与子报道来源相同时只计 1 次，避免重复计算）。
    source_counts: dict = {}
    try:
        src_stmt = text("""
            SELECT root_id, COUNT(DISTINCT source) AS source_count
            FROM (
                SELECT id AS root_id, source
                FROM news
                WHERE related_to_id IS NULL
                UNION ALL
                SELECT related_to_id AS root_id, source
                FROM news
                WHERE related_to_id IS NOT NULL
            ) sources
            GROUP BY root_id
        """)
        for rid, cnt in (await db.execute(src_stmt)).all():
            source_counts[str(rid)] = int(cnt)
    except Exception as e:
        logger.warning("event source-count query failed: %s", e)

    # 子报道统计（计数 + 最新发布时间）；信源数以上文统一口径为准
    child_stats: dict = {}  # pid -> (count, max_published_at)
    try:
        stats_stmt = (
            select(
                News.related_to_id,
                func.count(),
                func.max(News.published_at),
            )
            .where(News.related_to_id.isnot(None))
            .group_by(News.related_to_id)
        )
        for pid, cnt, max_pub in (await db.execute(stats_stmt)).all():
            child_stats[pid] = (cnt, max_pub)
    except Exception as e:
        logger.warning("child-stats query failed: %s", e)

    # ── 排序 ──
    use_python_sort = False
    if sort == EventSortMode.IMPORTANT:
        try:
            child_cnt_sql = "(SELECT COUNT(*) FROM news c WHERE c.related_to_id = news.id)"
            event_src_sql = (
                "(SELECT COUNT(DISTINCT x.source) FROM news x "
                "WHERE x.id = news.id OR x.related_to_id = news.id)"
            )
            boost_sql = (
                f"+ LEAST(COALESCE({event_src_sql}, 0) * {EVENT_BOOST_PER_SOURCE}, "
                f"{EVENT_BOOST_MAX})"
            )
            event_time_sql = (
                "GREATEST(published_at, "
                "COALESCE(event_last_updated_at, published_at), "
                "COALESCE((SELECT MAX(c2.published_at) FROM news c2 "
                "WHERE c2.related_to_id = news.id), published_at))"
            )
            gravity_sql = (
                f"CASE WHEN COALESCE({child_cnt_sql}, 0) > 0 "
                f"THEN {EVENT_GRAVITY} ELSE {DEFAULT_GRAVITY} END"
            )
            ranking_expr = text(gravity_sql_expression(
                score_column="ai_score",
                time_column=event_time_sql,
                gravity=gravity_sql,
                boost_sql=boost_sql,
            ))
            order_clause = desc(ranking_expr)
        except Exception:
            order_clause = desc(News.created_at)
            use_python_sort = True
    elif sort == EventSortMode.LATEST_UPDATE:
        order_clause = desc(func.coalesce(
            News.event_last_updated_at, News.published_at, News.created_at,
        ))
    else:  # FIRST_SEEN
        order_clause = desc(func.coalesce(
            News.event_first_seen_at, News.published_at, News.created_at,
        ))

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

    items = []
    for n in rows:
        child_cnt, child_max_pub = child_stats.get(n.id, (0, None))
        # 统一口径：整个事件（根 + 全部子报道）的去重信源数
        source_count = source_counts.get(str(n.id), 1)
        ranking_score = None
        if sort == EventSortMode.IMPORTANT:
            boost = min(source_count * EVENT_BOOST_PER_SOURCE, EVENT_BOOST_MAX)
            effective_pub = n.event_last_updated_at or n.published_at
            if child_max_pub and (effective_pub is None or child_max_pub > effective_pub):
                effective_pub = child_max_pub
            ranking_score = calculate_ranking_score(
                ai_score=n.ai_score or 0,
                publish_time=effective_pub,
                gravity=EVENT_GRAVITY if child_cnt > 0 else DEFAULT_GRAVITY,
                boost=boost,
            )
        items.append(_serialize_event(n, child_cnt, source_count,
                                      child_max_pub, ranking_score))

    if use_python_sort and sort == EventSortMode.IMPORTANT:
        items.sort(key=lambda x: x["ranking_score"] or 0, reverse=True)

    return PaginatedResponse(data=items, total=total, limit=limit, offset=offset)


def _serialize_article(n: News) -> dict:
    return {
        "id": str(n.id),
        "title": n.title,
        "source": n.source,
        "url": n.url,
        "ai_score": n.ai_score,
        "ai_summary": n.ai_summary,
        "published_at": n.published_at.isoformat() if n.published_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/{event_id}")
async def get_event_detail(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(require_api_key),
):
    """事件详情：当前状态 + 版本演进 + 全部关联报道。"""
    import uuid as _uuid
    try:
        eid = _uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event_id")

    root = (
        await db.execute(select(News).where(News.id == eid))
    ).scalar_one_or_none()
    if root is None:
        raise HTTPException(status_code=404, detail="Event not found")

    # 版本演进（倒序）
    versions = (
        await db.execute(
            select(EventVersion)
            .where(EventVersion.event_id == eid)
            .order_by(EventVersion.version.desc())
        )
    ).scalars().all()

    # 全部关联报道（发布时间倒序）
    children = (
        await db.execute(
            select(News)
            .where(News.related_to_id == eid)
            .order_by(desc(func.coalesce(News.published_at, News.created_at)))
        )
    ).scalars().all()

    # 统一口径：独立信源数 = 去重统计整个事件（根 + 全部子报道）的来源
    src_cnt = await db.execute(
        text(
            "SELECT COUNT(DISTINCT source) FROM news "
            "WHERE id = :eid OR related_to_id = :eid"
        ),
        {"eid": eid},
    ).scalar() or 0
    detail = _serialize_event(root, len(children), int(src_cnt) or 1, None, None)
    detail.update({
        "uncertainty": root.event_uncertainty,
        "watch_next": root.event_watch_next,
        "versions": [
            {
                "version": v.version,
                "event_title": v.event_title,
                "event_summary": v.event_summary,
                "latest_change": v.latest_change,
                "why_important": v.why_important,
                "uncertainty": v.uncertainty,
                "watch_next": v.watch_next,
                "status": v.status,
                "source_count": v.source_count,
                "article_count": v.article_count,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ],
        "articles": [_serialize_article(root)]
                    + [_serialize_article(c) for c in children],
    })
    return APIResponse(data=detail)


@router.get("/{event_id}/sources")
async def get_event_sources(
    event_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(require_api_key),
):
    """事件信源——全部关联报道（含根），独立接口分页加载（PRD 16.5）。"""
    import uuid as _uuid
    try:
        eid = _uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event_id")

    where = or_(News.id == eid, News.related_to_id == eid)
    total = (
        await db.execute(select(func.count()).select_from(News).where(where))
    ).scalar() or 0
    rows = (
        await db.execute(
            select(News)
            .where(where)
            .order_by(desc(func.coalesce(News.published_at, News.created_at)))
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    return PaginatedResponse(
        data=[_serialize_article(n) for n in rows],
        total=total, limit=limit, offset=offset,
    )
