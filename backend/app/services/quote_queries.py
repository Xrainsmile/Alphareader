"""stock_daily_quote 通用查询助手。

把散落在 router（stocks.py / sepa.py 等）里的裸 SQL 下沉到 service 层，
统一收口、避免重复（此前 stocks.py 同一价格查询 SQL 逐行重复两处）。
"""

from __future__ import annotations

import logging

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("alphareader.quote_queries")


async def get_latest_close_prices(
    db: AsyncSession, ts_codes: list[str], market: str
) -> dict[str, float]:
    """批量取一组标的的最新收盘价（每标的取最近一个交易日）。

    Returns:
        {ts_code: close}，无数据的标的不出现在结果中。
    """
    if not ts_codes:
        return {}
    result = await db.execute(
        sa_text(
            """
            SELECT DISTINCT ON (ts_code) ts_code, close
            FROM stock_daily_quote
            WHERE ts_code = ANY(:codes) AND market = :market
            ORDER BY ts_code, trade_date DESC
            """
        ),
        {"codes": ts_codes, "market": market},
    )
    return {
        r[0]: float(r[1]) for r in result.all() if r[1] is not None
    }


async def get_daily_bars(
    db: AsyncSession, ts_code: str, market: str, limit: int
) -> list[dict]:
    """取单标的最近 limit 根日K线，升序返回（oldest→newest）。

    每个元素: {"date", "open", "high", "low", "close", "volume"}。
    """
    rows = await db.execute(
        sa_text(
            """
            SELECT trade_date, open, high, low, close, volume
            FROM stock_daily_quote
            WHERE ts_code = :code AND market = :market
            ORDER BY trade_date DESC
            LIMIT :limit
            """
        ),
        {"code": ts_code, "market": market, "limit": limit},
    )
    recs = rows.all()
    bars = [
        {
            "date": (r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0])),
            "open": float(r[1]) if r[1] is not None else 0.0,
            "high": float(r[2]) if r[2] is not None else 0.0,
            "low": float(r[3]) if r[3] is not None else 0.0,
            "close": float(r[4]) if r[4] is not None else 0.0,
            "volume": float(r[5]) if r[5] is not None else 0.0,
        }
        for r in recs
    ]
    bars.reverse()  # 转升序（oldest→newest）
    return bars
