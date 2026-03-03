"""Sandbox NAV 计算服务。"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sandbox import SandboxNav, SandboxTrade
from app.models.stock import StockDailyQuote
from app.services.data_fetcher import get_sina_prices, get_unadjusted_close

logger = logging.getLogger("alphareader.sandbox_nav")

# 104,152.59 元初始总资产（NAV=1 的基准）
INITIAL_CAPITAL = Decimal("104152.59")


async def compute_nav_core(
    db: AsyncSession,
    calc_date: date,
    cash_balance: float | None = None,
    use_realtime: bool = True,
    market_value_override: float | None = None,
) -> dict | None:
    """计算指定日期 NAV，写入 SandboxNav 并返回结果。"""
    trades_result = await db.execute(
        select(SandboxTrade).where(SandboxTrade.trade_date <= calc_date)
    )
    all_trades = trades_result.scalars().all()

    if not all_trades:
        return None

    positions: dict[str, int] = {}
    cash_flow = Decimal("0")
    for t in all_trades:
        code = t.ts_code
        if t.action == "buy":
            positions[code] = positions.get(code, 0) + t.shares
            cash_flow += t.price * t.shares
        else:
            positions[code] = positions.get(code, 0) - t.shares
            cash_flow -= t.price * t.shares

    cash = Decimal(str(cash_balance)) if cash_balance is not None else INITIAL_CAPITAL - cash_flow

    holding_codes = [code for code, shares in positions.items() if shares > 0]

    realtime_prices: dict[str, float] = {}
    if use_realtime and holding_codes and calc_date >= date.today():
        try:
            realtime_prices = await get_sina_prices(holding_codes)
            if realtime_prices:
                logger.info("NAV: 新浪行情获取成功 %d/%d: %s", len(realtime_prices), len(holding_codes), realtime_prices)
        except Exception as e:
            logger.warning("NAV: 新浪行情获取失败: %s", e)

        missing_codes = [c for c in holding_codes if c not in realtime_prices]
        if missing_codes:
            logger.info("NAV: 新浪行情缺少 %d 只，尝试 akshare: %s", len(missing_codes), missing_codes)
            try:
                ak_prices = await get_unadjusted_close(missing_codes)
                if ak_prices:
                    realtime_prices.update(ak_prices)
                    logger.info("NAV: akshare 补全 %d 只: %s", len(ak_prices), ak_prices)
            except Exception as e:
                logger.warning("NAV: akshare 补全失败: %s", e)

    total_market_value = Decimal("0")
    holdings_detail: list[str] = []
    for code, shares in positions.items():
        if shares <= 0:
            continue

        close_price = None
        price_source = ""

        if code in realtime_prices:
            close_price = realtime_prices[code]
            price_source = "unadjusted"
        else:
            price_result = await db.execute(
                select(StockDailyQuote.close)
                .where(
                    StockDailyQuote.ts_code == code,
                    StockDailyQuote.trade_date <= calc_date,
                )
                .order_by(desc(StockDailyQuote.trade_date))
                .limit(1)
            )
            close_price = price_result.scalar()
            if close_price is not None:
                price_source = "db_qfq"

            if close_price is None:
                fallback_result = await db.execute(
                    select(SandboxTrade.price)
                    .where(
                        SandboxTrade.ts_code == code,
                        SandboxTrade.trade_date <= calc_date,
                    )
                    .order_by(desc(SandboxTrade.trade_date), desc(SandboxTrade.id))
                    .limit(1)
                )
                fallback_price = fallback_result.scalar()
                if fallback_price:
                    close_price = float(fallback_price)
                    price_source = "trade_fallback"
                    logger.info("NAV: %s no quote data, using trade price %.4f", code, close_price)

        if close_price:
            mv = Decimal(str(close_price)) * shares
            total_market_value += mv
            holdings_detail.append(
                f"{code}: price={close_price}({price_source}) × {shares}shares = ¥{float(mv):.2f}"
            )

    if holdings_detail:
        logger.info("NAV holdings detail:\n  %s", "\n  ".join(holdings_detail))

    if market_value_override is not None:
        total_market_value = Decimal(str(market_value_override))
        logger.info("NAV: 使用手动输入市值 ¥%.2f（覆盖计算值）", market_value_override)

    total_assets = total_market_value + cash
    nav_value = float(total_assets / INITIAL_CAPITAL) if INITIAL_CAPITAL > 0 else 1.0
    total_pnl = round((nav_value - 1.0) * 100, 2)

    stmt = pg_insert(SandboxNav).values(
        trade_date=calc_date,
        total_market_value=total_market_value,
        cash=cash,
        nav=nav_value,
        total_pnl=total_pnl,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_sandbox_nav_date",
        set_={
            "total_market_value": stmt.excluded.total_market_value,
            "cash": stmt.excluded.cash,
            "nav": stmt.excluded.nav,
            "total_pnl": stmt.excluded.total_pnl,
        },
    )
    await db.execute(stmt)
    await db.commit()

    logger.info(
        "NAV computed for %s: nav=%.4f, pnl=%.2f%%, mv=%.2f, cash=%.2f%s",
        calc_date,
        nav_value,
        total_pnl,
        total_market_value,
        cash,
        " (manual cash)" if cash_balance is not None else "",
    )
    return {
        "date": str(calc_date),
        "nav": round(nav_value, 4),
        "total_pnl": total_pnl,
        "market_value": float(total_market_value),
        "cash": float(cash),
        "total_assets": round(float(total_market_value + cash), 2),
        "holdings_detail": holdings_detail,
    }
