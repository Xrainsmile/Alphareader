"""Stock data & RS Rating API endpoints."""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.indicators import compute_and_save_rs_rating, load_rs_rating

logger = logging.getLogger("alphareader.api.stocks")
router = APIRouter(prefix="/stocks", tags=["stocks"])


# ── Response Schemas ──

class RSRatingItem(BaseModel):
    ts_code: str
    name: str
    trade_date: date
    p3: float | None = None
    p6: float | None = None
    p9: float | None = None
    p12: float | None = None
    score: float
    rs_rating: int


class RSRatingResponse(BaseModel):
    count: int
    date: date
    items: list[RSRatingItem]


# ── Endpoints ──

@router.get("/rs_rating", response_model=RSRatingResponse)
async def get_rs_rating(
    target_date: date | None = Query(None, description="查询日期，默认今天"),
    top_n: int = Query(100, ge=1, le=5000, description="返回前 N 名"),
    min_rating: int | None = Query(None, ge=1, le=99, description="最低 RS Rating"),
):
    """查询 RS Rating 排行榜。"""
    query_date = target_date or date.today()

    df = await load_rs_rating(
        target_date=query_date,
        top_n=top_n,
        min_rating=min_rating,
    )

    items = [RSRatingItem(**row) for row in df.to_dict("records")] if not df.empty else []

    return RSRatingResponse(
        count=len(items),
        date=query_date,
        items=items,
    )


@router.post("/rs_rating/compute")
async def trigger_rs_rating_compute(
    force: bool = Query(False, description="强制重新计算"),
):
    """手动触发 RS Rating 计算。"""
    logger.info("手动触发 RS Rating 计算 (force=%s)", force)
    df = await compute_and_save_rs_rating(force_refresh=force)

    return {
        "status": "ok",
        "count": len(df),
        "date": date.today().isoformat(),
        "message": f"RS Rating 计算完成，共 {len(df)} 只股票",
    }
