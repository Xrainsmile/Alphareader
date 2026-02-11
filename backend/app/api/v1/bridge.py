"""Gemini Context Bridge API endpoint."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.context_bridge import generate_prompt_context

router = APIRouter(prefix="/bridge", tags=["bridge"])


@router.get("/generate_prompt")
async def generate_prompt(
    sector: str | None = Query(None, description="板块/行业筛选，如 '新能源'"),
    target_date: date | None = Query(None, alias="date", description="目标日期，默认今天"),
    top_n: int = Query(66, ge=1, le=100, description="返回 Top N 条新闻"),
    db: AsyncSession = Depends(get_db),
):
    """Generate a structured prompt context for Gemini consumption.

    Example: GET /api/v1/bridge/generate_prompt?sector=新能源&date=2026-02-08
    """
    return await generate_prompt_context(
        session=db,
        sector=sector,
        target_date=target_date,
        top_n=top_n,
    )
