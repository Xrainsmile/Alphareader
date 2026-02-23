"""Analytics API — 用户行为事件上报 + 统计查询。"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analytics import AnalyticsDaily, PipelineRun

logger = logging.getLogger("alphareader.analytics")

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ── 事件上报 ──

class EventItem(BaseModel):
    type: str = Field(..., pattern="^(page_view|news_click|news_impression|session_duration)$")
    dimension: str = Field("_total", max_length=200)
    value: int = Field(1, ge=1)


class EventBatch(BaseModel):
    events: list[EventItem] = Field(..., min_length=1, max_length=500)


@router.post("/events", status_code=202)
async def report_events(batch: EventBatch, db: AsyncSession = Depends(get_db)):
    """批量上报用户行为事件。

    前端攒批后调用，后端直接原子累加到 analytics_daily 表。
    """
    today = date.today()
    count = 0
    for evt in batch.events:
        stmt = (
            pg_insert(AnalyticsDaily)
            .values(date=today, metric=evt.type, dimension=evt.dimension, value=evt.value)
            .on_conflict_do_update(
                constraint="uq_analytics_daily",
                set_={"value": AnalyticsDaily.value + evt.value},
            )
        )
        await db.execute(stmt)
        count += 1
    await db.commit()
    return {"accepted": count}


# ── 用户行为统计查询 ──

@router.get("/user_stats")
async def get_user_stats(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """查询用户行为统计：今日概览 + 过去 N 天趋势 + 点击率 Top10。"""
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    # 1. 今日概览
    today_q = await db.execute(
        select(AnalyticsDaily.metric, func.sum(AnalyticsDaily.value))
        .where(AnalyticsDaily.date == today, AnalyticsDaily.dimension == "_total")
        .group_by(AnalyticsDaily.metric)
    )
    today_map = dict(today_q.all())

    # 2. 每日趋势
    trend_q = await db.execute(
        select(
            AnalyticsDaily.date,
            AnalyticsDaily.metric,
            func.sum(AnalyticsDaily.value).label("total"),
        )
        .where(
            AnalyticsDaily.date >= start_date,
            AnalyticsDaily.dimension == "_total",
        )
        .group_by(AnalyticsDaily.date, AnalyticsDaily.metric)
        .order_by(AnalyticsDaily.date)
    )
    trend_rows = trend_q.all()

    # 组装成 {date: {metric: value}} 的结构
    trend: dict[str, dict] = {}
    for row in trend_rows:
        d = row.date.isoformat()
        if d not in trend:
            trend[d] = {}
        trend[d][row.metric] = row.total

    # 3. 点击率 Top 10 新闻（按 CTR 排序）
    # 子查询：分别聚合 impression 和 click
    top_q = await db.execute(text("""
        WITH imp AS (
            SELECT dimension, SUM(value) AS impressions
            FROM analytics_daily
            WHERE metric = 'news_impression' AND dimension != '_total'
              AND date >= :start
            GROUP BY dimension
        ),
        clk AS (
            SELECT dimension, SUM(value) AS clicks
            FROM analytics_daily
            WHERE metric = 'news_click' AND dimension != '_total'
              AND date >= :start
            GROUP BY dimension
        )
        SELECT
            COALESCE(imp.dimension, clk.dimension) AS news_id,
            COALESCE(imp.impressions, 0) AS impressions,
            COALESCE(clk.clicks, 0) AS clicks,
            CASE WHEN COALESCE(imp.impressions, 0) > 0
                 THEN ROUND(COALESCE(clk.clicks, 0)::numeric / imp.impressions * 100, 1)
                 ELSE 0 END AS ctr,
            n.title
        FROM imp FULL OUTER JOIN clk ON imp.dimension = clk.dimension
        LEFT JOIN news n ON n.id::text = COALESCE(imp.dimension, clk.dimension)
        WHERE COALESCE(clk.clicks, 0) > 0
        ORDER BY clicks DESC
        LIMIT 10
    """), {"start": start_date})
    top_news = [
        {
            "news_id": r.news_id,
            "title": r.title or "(已删除)",
            "impressions": r.impressions,
            "clicks": r.clicks,
            "ctr": float(r.ctr),
        }
        for r in top_q.all()
    ]

    # session_duration 求平均：总秒数 / page_view 数
    total_duration = int(today_map.get("session_duration", 0))
    total_pv = int(today_map.get("page_view", 0))
    avg_duration = round(total_duration / total_pv, 1) if total_pv > 0 else 0

    return {
        "today": {
            "page_view": int(today_map.get("page_view", 0)),
            "news_click": int(today_map.get("news_click", 0)),
            "news_impression": int(today_map.get("news_impression", 0)),
            "avg_duration_sec": avg_duration,
        },
        "trend": trend,
        "top_news": top_news,
    }


# ── Pipeline 运行统计查询 ──

@router.get("/pipeline_stats")
async def get_pipeline_stats(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """查询 Pipeline 运行统计：今日概览 + 信源明细 + 评分分布 + 最近运行记录。"""
    today = date.today()
    start_dt = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())

    # 1. 指定时间段的聚合统计
    agg_q = await db.execute(
        select(
            func.count().label("runs"),
            func.sum(PipelineRun.total_fetched).label("fetched"),
            func.sum(PipelineRun.after_score).label("scored"),
            func.sum(PipelineRun.stored).label("stored"),
            func.avg(PipelineRun.duration_sec).label("avg_duration"),
        )
        .where(PipelineRun.started_at >= start_dt)
    )
    agg = agg_q.one()

    total_fetched = int(agg.fetched or 0)
    total_stored = int(agg.stored or 0)
    retention_rate = round(total_stored / total_fetched * 100, 1) if total_fetched > 0 else 0

    # 2. 各信源聚合（从 JSONB by_source 字段中拆解）
    source_q = await db.execute(text("""
        SELECT
            src_key AS source,
            SUM((src_val->>'fetched')::int) AS fetched,
            SUM((src_val->>'passed')::int) AS passed
        FROM pipeline_runs,
             jsonb_each(by_source) AS t(src_key, src_val)
        WHERE started_at >= :start
        GROUP BY src_key
        ORDER BY fetched DESC
    """), {"start": start_dt})
    by_source = [
        {
            "source": r.source,
            "fetched": int(r.fetched or 0),
            "passed": int(r.passed or 0),
            "retention": round(int(r.passed or 0) / int(r.fetched) * 100, 1) if int(r.fetched or 0) > 0 else 0,
        }
        for r in source_q.all()
    ]

    # 3. 评分分布聚合
    score_q = await db.execute(text("""
        SELECT
            score_key AS score,
            SUM(score_val::int) AS count
        FROM pipeline_runs,
             jsonb_each_text(score_distribution) AS t(score_key, score_val)
        WHERE started_at >= :start
        GROUP BY score_key
        ORDER BY score_key
    """), {"start": start_dt})
    score_dist = {r.score: int(r.count) for r in score_q.all()}

    # 4. 最近 20 次运行记录
    recent_q = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.started_at >= start_dt)
        .order_by(PipelineRun.started_at.desc())
        .limit(20)
    )
    recent = [
        {
            "id": r.id,
            "started_at": r.started_at.isoformat(),
            "duration_sec": round(r.duration_sec, 1),
            "fetched": r.total_fetched,
            "deduped": r.after_dedup,
            "scored": r.after_score,
            "stored": r.stored,
            "errors": r.errors or [],
        }
        for r in recent_q.scalars().all()
    ]

    return {
        "overview": {
            "runs": int(agg.runs or 0),
            "total_fetched": total_fetched,
            "total_scored": int(agg.scored or 0),
            "total_stored": total_stored,
            "retention_rate": retention_rate,
            "avg_duration_sec": round(float(agg.avg_duration or 0), 1),
        },
        "by_source": by_source,
        "score_distribution": score_dist,
        "recent_runs": recent,
    }
