"""Daily Briefing API — 每日综合分析报告。

Endpoints:
  GET /api/v1/briefings/          — 获取报告列表（按日期倒序）
  GET /api/v1/briefings/{id}      — 获取单条报告详情
  GET /api/v1/briefings/latest    — 获取最新一条报告
  POST /api/v1/briefings/generate — 手动触发生成（调试用）
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.daily_briefing import DailyBriefing

logger = logging.getLogger("alphareader.briefings_api")

router = APIRouter(prefix="/briefings", tags=["briefings"])


# ── Response Schemas ──

class BriefingListItem(BaseModel):
    id: int
    briefing_date: str  # "YYYY-MM-DD"
    content: str  # Markdown 分析报告
    meta: dict  # 策略统计概要
    prompt_tokens_est: int
    generation_sec: float
    status: str  # ok / failed / empty
    created_at: str  # ISO datetime

    class Config:
        from_attributes = True


class BriefingDetail(BriefingListItem):
    pass


# ── Endpoints ──

@router.get("/latest", response_model=BriefingDetail | None)
async def get_latest_briefing(
    db: AsyncSession = Depends(get_db),
):
    """获取最新一条分析报告。"""
    stmt = (
        select(DailyBriefing)
        .order_by(DailyBriefing.briefing_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    b = result.scalar_one_or_none()

    if not b:
        return None

    return BriefingDetail(
        id=b.id,
        briefing_date=b.briefing_date.isoformat(),
        content=b.content,
        meta=b.meta,
        prompt_tokens_est=b.prompt_tokens_est,
        generation_sec=b.generation_sec,
        status=b.status,
        created_at=b.created_at.isoformat() if b.created_at else "",
    )


@router.get("/", response_model=list[BriefingListItem])
async def list_briefings(
    days: int = Query(7, ge=1, le=90, description="获取最近几天的报告"),
    db: AsyncSession = Depends(get_db),
):
    """获取分析报告列表，按日期倒序。默认最近 7 天。"""
    cutoff = date.today() - timedelta(days=days)

    stmt = (
        select(DailyBriefing)
        .where(DailyBriefing.briefing_date >= cutoff)
        .order_by(DailyBriefing.briefing_date.desc())
    )
    result = await db.execute(stmt)
    briefings = result.scalars().all()

    return [
        BriefingListItem(
            id=b.id,
            briefing_date=b.briefing_date.isoformat(),
            content=b.content,
            meta=b.meta,
            prompt_tokens_est=b.prompt_tokens_est,
            generation_sec=b.generation_sec,
            status=b.status,
            created_at=b.created_at.isoformat() if b.created_at else "",
        )
        for b in briefings
    ]


@router.get("/{briefing_id}", response_model=BriefingDetail)
async def get_briefing(
    briefing_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取单条报告详情。"""
    stmt = select(DailyBriefing).where(DailyBriefing.id == briefing_id)
    result = await db.execute(stmt)
    b = result.scalar_one_or_none()

    if not b:
        raise HTTPException(status_code=404, detail="Briefing not found")

    return BriefingDetail(
        id=b.id,
        briefing_date=b.briefing_date.isoformat(),
        content=b.content,
        meta=b.meta,
        prompt_tokens_est=b.prompt_tokens_est,
        generation_sec=b.generation_sec,
        status=b.status,
        created_at=b.created_at.isoformat() if b.created_at else "",
    )


class GenerateBriefingRequest(BaseModel):
    target_date: str | None = None  # "YYYY-MM-DD"，为空则用今天


@router.post("/generate")
async def generate_briefing_endpoint(payload: GenerateBriefingRequest):
    """手动触发生成分析报告（调试/补数据用）。"""
    from app.services.briefing_service import generate_briefing

    target = None
    if payload.target_date:
        try:
            target = date.fromisoformat(payload.target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    try:
        result = await generate_briefing(target)
        return {"code": 0, "msg": "ok", **result}
    except Exception as e:
        logger.exception("Generate briefing failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
