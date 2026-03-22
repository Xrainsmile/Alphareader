"""催化剂标的 API 端点。

提供催化剂标的排行榜查询、交叉验证结果、
以及按 ts_code 查询是否有催化剂命中。
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select, func as sa_func, and_

from app.database import async_session
from app.models.catalyst import NewsCatalystStock
from app.schemas.response import APIResponse

logger = logging.getLogger("alphareader.api.catalyst")
router = APIRouter(prefix="/catalyst", tags=["catalyst"])


# ── Response Schemas ──

class CatalystStockItem(BaseModel):
    """催化剂标的单条记录。"""
    ts_code: str
    name: str | None = None
    news_count: int = 0
    top_score: int = 0
    avg_score: float = 0.0
    catalyst_types: list[str] | None = None
    catalyst_summary: str | None = None
    avg_sentiment: float | None = None
    news_titles: list[str] | None = None
    in_vcp: bool = False
    vcp_score: float | None = None
    in_trend: bool = False
    trend_score: float | None = None
    rs_rating: int | None = None
    heat_score: float = 0.0
    confirm_level: str = "catalyst_only"
    futu_url: str | None = None


def _generate_futu_url(ts_code: str) -> str:
    """根据 A 股代码生成富途链接。"""
    code = ts_code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "").strip()
    suffix = "SH" if code.startswith("6") else "SZ"
    return f"https://www.futunn.com/stock/{code}-{suffix}"


# ── Endpoints ──

@router.get("/stocks")
async def get_catalyst_stocks(
    target_date: date | None = Query(None, description="查询日期，默认最新"),
    confirm_level: str | None = Query(
        None,
        description="交叉验证分类：double_confirmed / strong_rs / catalyst_only，不传则返回全部",
    ),
    min_heat: float | None = Query(None, ge=0, description="最低热度分阈值"),
):
    """查询催化剂标的排行榜。

    返回当日（或最新有数据日期）从高分新闻中提取的催化剂标的，
    含催化剂热度、交叉验证状态（VCP/趋势/RS）等。
    按热度降序排列。
    """
    async with async_session() as session:
        # 确定查询日期
        if target_date:
            query_date = target_date
        else:
            max_date_q = await session.execute(
                select(sa_func.max(NewsCatalystStock.catalyst_date))
            )
            query_date = max_date_q.scalar()
            if not query_date:
                return APIResponse(data={"count": 0, "date": None, "items": []})

        # 构建查询
        conditions = [NewsCatalystStock.catalyst_date == query_date]
        if confirm_level:
            conditions.append(NewsCatalystStock.confirm_level == confirm_level)
        if min_heat is not None:
            conditions.append(NewsCatalystStock.heat_score >= min_heat)

        stmt = (
            select(NewsCatalystStock)
            .where(and_(*conditions))
            .order_by(NewsCatalystStock.heat_score.desc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

    items = []
    for r in rows:
        items.append(CatalystStockItem(
            ts_code=r.ts_code,
            name=r.name,
            news_count=r.news_count,
            top_score=r.top_score,
            avg_score=r.avg_score,
            catalyst_types=r.catalyst_types,
            catalyst_summary=r.catalyst_summary,
            avg_sentiment=r.avg_sentiment,
            news_titles=r.news_titles,
            in_vcp=r.in_vcp,
            vcp_score=r.vcp_score,
            in_trend=r.in_trend,
            trend_score=r.trend_score,
            rs_rating=r.rs_rating,
            heat_score=r.heat_score,
            confirm_level=r.confirm_level,
            futu_url=_generate_futu_url(r.ts_code),
        ).model_dump())

    # 统计
    double_count = sum(1 for i in items if i["confirm_level"] == "double_confirmed")
    strong_rs_count = sum(1 for i in items if i["confirm_level"] == "strong_rs")
    catalyst_only_count = sum(1 for i in items if i["confirm_level"] == "catalyst_only")

    return APIResponse(data={
        "count": len(items),
        "date": str(query_date),
        "stats": {
            "double_confirmed": double_count,
            "strong_rs": strong_rs_count,
            "catalyst_only": catalyst_only_count,
        },
        "items": items,
    })


@router.get("/check")
async def check_catalyst(
    ts_code: str = Query(..., description="股票代码（如 300750.SZ）"),
    target_date: date | None = Query(None, description="查询日期，默认最新"),
):
    """查询指定标的是否命中今日催化剂。

    用于 VCP/趋势 Tab 给有催化剂的标的加 🔥 标记。
    """
    async with async_session() as session:
        if target_date:
            query_date = target_date
        else:
            max_date_q = await session.execute(
                select(sa_func.max(NewsCatalystStock.catalyst_date))
            )
            query_date = max_date_q.scalar()
            if not query_date:
                return APIResponse(data={"has_catalyst": False})

        stmt = (
            select(NewsCatalystStock)
            .where(
                and_(
                    NewsCatalystStock.catalyst_date == query_date,
                    NewsCatalystStock.ts_code == ts_code.strip().upper(),
                )
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalars().first()

    if not row:
        return APIResponse(data={
            "has_catalyst": False,
            "ts_code": ts_code.strip().upper(),
            "date": str(query_date) if query_date else None,
        })

    return APIResponse(data={
        "has_catalyst": True,
        "ts_code": row.ts_code,
        "date": str(query_date),
        "news_count": row.news_count,
        "top_score": row.top_score,
        "heat_score": row.heat_score,
        "catalyst_types": row.catalyst_types,
        "catalyst_summary": row.catalyst_summary,
        "confirm_level": row.confirm_level,
    })


@router.get("/batch_check")
async def batch_check_catalyst(
    ts_codes: str = Query(..., description="逗号分隔的股票代码列表"),
    target_date: date | None = Query(None, description="查询日期，默认最新"),
):
    """批量查询多只标的的催化剂命中状态。

    用于 VCP/趋势白名单列表，一次性获取所有标的的催化剂状态。
    返回 {ts_code: {has_catalyst, heat_score, ...}} 映射。
    """
    codes = [c.strip().upper() for c in ts_codes.split(",") if c.strip()]
    if not codes:
        return APIResponse(data={"date": None, "items": {}})

    async with async_session() as session:
        if target_date:
            query_date = target_date
        else:
            max_date_q = await session.execute(
                select(sa_func.max(NewsCatalystStock.catalyst_date))
            )
            query_date = max_date_q.scalar()
            if not query_date:
                return APIResponse(data={"date": None, "items": {}})

        stmt = (
            select(NewsCatalystStock)
            .where(
                and_(
                    NewsCatalystStock.catalyst_date == query_date,
                    NewsCatalystStock.ts_code.in_(codes),
                )
            )
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

    items: dict[str, dict] = {}
    for r in rows:
        items[r.ts_code] = {
            "has_catalyst": True,
            "news_count": r.news_count,
            "top_score": r.top_score,
            "heat_score": r.heat_score,
            "catalyst_types": r.catalyst_types,
            "catalyst_summary": r.catalyst_summary,
            "confirm_level": r.confirm_level,
        }

    return APIResponse(data={
        "date": str(query_date),
        "items": items,
    })
