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
from app.schemas.response import APIResponse

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

@router.get("/latest")
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
        return APIResponse(data=None)

    return APIResponse(data=BriefingDetail(
        id=b.id,
        briefing_date=b.briefing_date.isoformat(),
        content=b.content,
        meta=b.meta,
        prompt_tokens_est=b.prompt_tokens_est,
        generation_sec=b.generation_sec,
        status=b.status,
        created_at=b.created_at.isoformat() if b.created_at else "",
    ).model_dump())


@router.get("/")
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

    items = [
        BriefingListItem(
            id=b.id,
            briefing_date=b.briefing_date.isoformat(),
            content=b.content,
            meta=b.meta,
            prompt_tokens_est=b.prompt_tokens_est,
            generation_sec=b.generation_sec,
            status=b.status,
            created_at=b.created_at.isoformat() if b.created_at else "",
        ).model_dump()
        for b in briefings
    ]
    return APIResponse(data=items)


@router.get("/{briefing_id}")
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

    return APIResponse(data=BriefingDetail(
        id=b.id,
        briefing_date=b.briefing_date.isoformat(),
        content=b.content,
        meta=b.meta,
        prompt_tokens_est=b.prompt_tokens_est,
        generation_sec=b.generation_sec,
        status=b.status,
        created_at=b.created_at.isoformat() if b.created_at else "",
    ).model_dump())


class GenerateBriefingRequest(BaseModel):
    target_date: date | None = None  # YYYY-MM-DD，为空则用今天


@router.post("/generate")
async def generate_briefing_endpoint(payload: GenerateBriefingRequest):
    """手动触发生成分析报告（调试/补数据用）。"""
    from app.services.briefing_service import generate_briefing

    try:
        result = await generate_briefing(payload.target_date)
        return APIResponse(data=result)
    except Exception as e:
        logger.exception("Generate briefing failed: %s", e)
        raise HTTPException(status_code=500, detail="研报生成失败，请稍后重试")
