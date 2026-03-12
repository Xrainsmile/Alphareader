from __future__ import annotations

from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sandbox import SandboxAnalysis, SandboxNav, SandboxStock, SandboxTrade
from app.models.stock import StockDailyQuote
from app.services.sandbox_nav import INITIAL_CAPITAL


async def get_sandbox_stock_list(
    db: AsyncSession,
    *,
    status: str | None,
    q: str | None,
    holding_only: bool,
) -> dict:
    query = select(SandboxStock).order_by(desc(SandboxStock.updated_at))
    # 模拟仓列表默认只显示短线策略（swing），排除价投标的
    query = query.where(SandboxStock.strategy == "swing")
    if status:
        query = query.where(SandboxStock.status == status)
    else:
        query = query.where(SandboxStock.status != "exited")

    if holding_only:
        query = query.where(SandboxStock.status == "holding")

    if q:
        keyword = f"%{q.strip()}%"
        query = query.where(
            (SandboxStock.ts_code.ilike(keyword)) | (SandboxStock.name.ilike(keyword))
        )

    stocks = (await db.execute(query)).scalars().all()

    nav_result = await db.execute(select(SandboxNav).order_by(desc(SandboxNav.trade_date)).limit(1))
    latest_nav = nav_result.scalar_one_or_none()
    total_assets = float(latest_nav.total_market_value + latest_nav.cash) if latest_nav else float(INITIAL_CAPITAL)

    if not stocks:
        return {"items": [], "total": 0}

    stock_ids = [s.id for s in stocks]
    ts_codes = [s.ts_code for s in stocks]

    latest_analysis_id_subq = (
        select(
            SandboxAnalysis.stock_id.label("stock_id"),
            func.max(SandboxAnalysis.id).label("latest_id"),
        )
        .where(SandboxAnalysis.stock_id.in_(stock_ids))
        .group_by(SandboxAnalysis.stock_id)
        .subquery()
    )
    latest_analyses = (
        await db.execute(
            select(SandboxAnalysis)
            .join(latest_analysis_id_subq, SandboxAnalysis.id == latest_analysis_id_subq.c.latest_id)
        )
    ).scalars().all()
    latest_analysis_map = {a.stock_id: a for a in latest_analyses}

    analysis_stats_rows = (
        await db.execute(
            select(
                SandboxAnalysis.stock_id.label("stock_id"),
                func.count(SandboxAnalysis.id).label("count"),
                func.max(SandboxAnalysis.created_at).label("latest_at"),
            )
            .where(SandboxAnalysis.stock_id.in_(stock_ids))
            .group_by(SandboxAnalysis.stock_id)
        )
    ).all()
    analysis_stats_map = {
        int(row.stock_id): {
            "count": int(row.count or 0),
            "latest_at": row.latest_at,
        }
        for row in analysis_stats_rows
    }

    net_shares_rows = (
        await db.execute(
            select(
                SandboxTrade.stock_id.label("stock_id"),
                func.sum(
                    case(
                        (SandboxTrade.action == "buy", SandboxTrade.shares),
                        else_=-SandboxTrade.shares,
                    )
                ).label("net_shares"),
            )
            .where(SandboxTrade.stock_id.in_(stock_ids))
            .group_by(SandboxTrade.stock_id)
        )
    ).all()
    net_shares_map = {
        int(row.stock_id): int(row.net_shares or 0)
        for row in net_shares_rows
    }

    latest_quote_subq = (
        select(
            StockDailyQuote.ts_code.label("ts_code"),
            func.max(StockDailyQuote.trade_date).label("trade_date"),
        )
        .where(StockDailyQuote.ts_code.in_(ts_codes))
        .group_by(StockDailyQuote.ts_code)
        .subquery()
    )
    latest_quote_rows = (
        await db.execute(
            select(StockDailyQuote.ts_code, StockDailyQuote.close)
            .join(
                latest_quote_subq,
                and_(
                    StockDailyQuote.ts_code == latest_quote_subq.c.ts_code,
                    StockDailyQuote.trade_date == latest_quote_subq.c.trade_date,
                ),
            )
        )
    ).all()
    latest_quote_map = {
        str(row.ts_code): float(row.close)
        for row in latest_quote_rows
        if row.close is not None
    }

    fallback_trade_subq = (
        select(
            SandboxTrade.ts_code.label("ts_code"),
            SandboxTrade.price.label("price"),
            func.row_number()
            .over(
                partition_by=SandboxTrade.ts_code,
                order_by=(desc(SandboxTrade.trade_date), desc(SandboxTrade.id)),
            )
            .label("rn"),
        )
        .where(SandboxTrade.ts_code.in_(ts_codes))
        .subquery()
    )
    fallback_trade_rows = (
        await db.execute(
            select(fallback_trade_subq.c.ts_code, fallback_trade_subq.c.price)
            .where(fallback_trade_subq.c.rn == 1)
        )
    ).all()
    fallback_trade_map = {
        str(row.ts_code): float(row.price)
        for row in fallback_trade_rows
        if row.price is not None
    }

    items = []
    for s in stocks:
        analysis_stats = analysis_stats_map.get(int(s.id), {"count": 0, "latest_at": None})
        analysis_count = analysis_stats["count"]
        analysis_latest_at = analysis_stats["latest_at"]

        net_shares = net_shares_map.get(int(s.id), 0)
        position_pct = 0.0
        if net_shares > 0 and total_assets > 0:
            close_price = latest_quote_map.get(s.ts_code)
            if close_price is None:
                close_price = fallback_trade_map.get(s.ts_code)
            if close_price:
                market_val = float(close_price) * net_shares
                position_pct = round(market_val / total_assets * 100, 1)

        la = latest_analysis_map.get(int(s.id))
        items.append(
            {
                "id": s.id,
                "ts_code": s.ts_code,
                "name": s.name,
                "status": s.status,
                "reason": s.reason,
                "position_pct": position_pct,
                "added_at": s.added_at.isoformat() if s.added_at else None,
                "analysis_count": analysis_count,
                "analysis_latest_at": analysis_latest_at.isoformat() if analysis_latest_at else None,
                "latest_analysis": {
                    "id": la.id,
                    "score": la.score,
                    "plan": la.plan,
                    "verdict": la.verdict,
                    "created_at": la.created_at.isoformat(),
                }
                if la
                else None,
            }
        )

    return {"items": items, "total": len(items)}
