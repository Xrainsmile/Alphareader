"""News Digests API — 新闻概览时间轴数据。

Endpoints:
  GET /api/v1/digests/       — 获取新闻概览列表（按时间倒序）
  GET /api/v1/digests/{id}   — 获取单条概览详情
  POST /api/v1/digests/generate — 手动触发生成指定时段的摘要（调试用）
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.news_digest import NewsDigest
from app.services.digest_service import PERIOD_ICONS, PERIOD_LABELS

logger = logging.getLogger("alphareader.digests_api")

router = APIRouter(prefix="/digests", tags=["digests"])


# ── Response Schemas ──

class DigestListItem(BaseModel):
    id: int
    digest_date: str  # "YYYY-MM-DD"
    period_label: str  # "morning" / "midday" / "evening" / "night"
    period_display: str  # "早间概览"
    period_icon: str  # "🌅"
    period_start: str  # ISO datetime
    period_end: str  # ISO datetime
    news_count: int
    content: str  # Markdown 总结
    created_at: str  # ISO datetime

    class Config:
        from_attributes = True


class DigestDetail(DigestListItem):
    pass


# ── Endpoints ──

@router.get("/", response_model=list[DigestListItem])
async def list_digests(
    days: int = Query(7, ge=1, le=30, description="获取最近几天的概览"),
    db: AsyncSession = Depends(get_db),
):
    """获取新闻概览列表，按时间倒序（最新在前）。默认最近 7 天。"""
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days)

    stmt = (
        select(NewsDigest)
        .where(NewsDigest.digest_date >= cutoff)
        .order_by(NewsDigest.digest_date.desc(), NewsDigest.period_end.desc())
    )
    result = await db.execute(stmt)
    digests = result.scalars().all()

    return [
        DigestListItem(
            id=d.id,
            digest_date=d.digest_date.isoformat(),
            period_label=d.period_label,
            period_display=PERIOD_LABELS.get(d.period_label, d.period_label),
            period_icon=PERIOD_ICONS.get(d.period_label, "📰"),
            period_start=d.period_start.isoformat(),
            period_end=d.period_end.isoformat(),
            news_count=d.news_count,
            content=d.content,
            created_at=d.created_at.isoformat() if d.created_at else "",
        )
        for d in digests
    ]


@router.get("/{digest_id}", response_model=DigestDetail)
async def get_digest(
    digest_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取单条概览详情。"""
    stmt = select(NewsDigest).where(NewsDigest.id == digest_id)
    result = await db.execute(stmt)
    d = result.scalar_one_or_none()

    if not d:
        raise HTTPException(status_code=404, detail="Digest not found")

    return DigestDetail(
        id=d.id,
        digest_date=d.digest_date.isoformat(),
        period_label=d.period_label,
        period_display=PERIOD_LABELS.get(d.period_label, d.period_label),
        period_icon=PERIOD_ICONS.get(d.period_label, "📰"),
        period_start=d.period_start.isoformat(),
        period_end=d.period_end.isoformat(),
        news_count=d.news_count,
        content=d.content,
        created_at=d.created_at.isoformat() if d.created_at else "",
    )


class GenerateRequest(BaseModel):
    period_label: str  # "morning" / "midday" / "evening" / "night"
    target_date: str | None = None  # "YYYY-MM-DD"，为空则用今天


@router.post("/generate")
async def generate_digest_endpoint(payload: GenerateRequest):
    """手动触发生成指定时段的摘要（调试/补数据用）。"""
    from app.services.digest_service import generate_digest

    target = None
    if payload.target_date:
        try:
            target = date.fromisoformat(payload.target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    try:
        result = await generate_digest(payload.period_label, target)
        return {"code": 0, "msg": "ok", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Generate digest failed: %s", e)
        raise HTTPException(status_code=500, detail="摘要生成失败，请稍后重试")
