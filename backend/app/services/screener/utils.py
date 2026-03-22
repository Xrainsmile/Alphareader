"""Screener 公共工具函数。

抽取两个 pipeline 共享的逻辑，消除代码重复。
"""

from __future__ import annotations

import logging

from app.database import async_session

logger = logging.getLogger("alphareader.screener.utils")


async def load_st_codes(market: str = "CN") -> set[str]:
    """从数据库中查询最近完整交易日名称包含 ST 的股票代码。

    仅对 A 股（CN）市场有意义，美股无 ST 机制，直接返回空集合。

    匹配规则：股票简称包含 'ST'（覆盖 *ST、ST 两种情况）。
    仅查最近的完整交易日，避免历史上曾 ST 但已摘帽的股票被误杀。

    注意：不能简单取 MAX(trade_date)，因为当天数据可能还在入库中
    （只有少量记录），会导致 ST 列表几乎为空。改为取最近一个
    至少有 1000 只股票记录的交易日，确保数据完整。

    Args:
        market: 市场标识，"CN" 或 "US"

    Returns:
        ST 股票的 ts_code 集合
    """
    if market != "CN":
        logger.info("load_st_codes: 市场 %s 无 ST 机制，跳过", market)
        return set()

    from sqlalchemy import text as sa_text

    # 取最近一个有完整数据的交易日（至少 1000 只股票）
    sql = sa_text("""
        WITH full_dates AS (
            SELECT trade_date, COUNT(DISTINCT ts_code) AS cnt
            FROM stock_daily_quote
            WHERE market = 'CN'
            GROUP BY trade_date
            HAVING COUNT(DISTINCT ts_code) >= 1000
            ORDER BY trade_date DESC
            LIMIT 1
        )
        SELECT DISTINCT q.ts_code
        FROM stock_daily_quote q
        JOIN full_dates fd ON q.trade_date = fd.trade_date
        WHERE q.name LIKE '%ST%' AND q.market = 'CN'
    """)

    async with async_session() as session:
        result = await session.execute(sql)
        codes = {row[0] for row in result}

    logger.info("load_st_codes: 发现 %d 只 ST 股票", len(codes))
    return codes


async def load_stock_names(codes: set[str], market: str = "CN") -> dict[str, str]:
    """从 stock_daily_quote 表批量查询股票名称。

    取最近一个有完整数据的交易日，然后一次性查出所有候选股票的 name。

    Args:
        codes: 需要查名称的 ts_code 集合
        market: 市场标识

    Returns:
        {ts_code: name} 映射字典
    """
    if not codes:
        return {}

    from sqlalchemy import text as sa_text

    # 取最近一个有足够非空 name 的交易日，避免取到 name 全空的日期
    sql = sa_text("""
        WITH name_date AS (
            SELECT trade_date
            FROM stock_daily_quote
            WHERE name IS NOT NULL AND name != '' AND market = :market
            GROUP BY trade_date
            HAVING COUNT(DISTINCT ts_code) >= :min_count
            ORDER BY trade_date DESC
            LIMIT 1
        )
        SELECT q.ts_code, q.name
        FROM stock_daily_quote q
        JOIN name_date nd ON q.trade_date = nd.trade_date
        WHERE q.ts_code = ANY(:codes)
          AND q.name IS NOT NULL
          AND q.name != ''
          AND q.market = :market
    """)

    # A 股至少 500 只股票的交易日才算完整，美股至少 100 只
    min_count = 500 if market == "CN" else 100

    async with async_session() as session:
        result = await session.execute(sql, {
            "codes": list(codes),
            "market": market,
            "min_count": min_count,
        })
        name_map = {row[0]: row[1] for row in result}

    return name_map
