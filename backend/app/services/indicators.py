"""Alphareader — RS Rating 计算模块（异步版，SQL 优化）。

职责：
  基于 IBD/Minervini 方法，计算 A 股个股相对强度评分（RS Rating）。

算法：
  1. 计算 4 个周期的涨跌幅 (ROC)：3/6/9/12 个月
  2. 加权得分：Score = 0.4*P3 + 0.2*P6 + 0.2*P9 + 0.2*P12
  3. 百分位排名映射为 1~99 整数（99 = 最强）

核心逻辑（v2 — 内存优化）：
  - 通过 SQL 窗口函数在 PostgreSQL 中完成 ROC 计算
  - Python 只处理 ~5000 行聚合结果（<50MB 内存）
  - 不再将 165 万行行情数据全量加载到内存

错误处理：
  - 数据不足的股票自动跳过（至少需要 63 个交易日）
  - 全局异常向上抛出
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session, engine
from app.models.stock import StockDailyQuote, StockRSRating

logger = logging.getLogger("alphareader.indicators")

# ────────── 周期配置（交易日） ──────────
PERIOD_3M = 63
PERIOD_6M = 126
PERIOD_9M = 189
PERIOD_12M = 252

MIN_TRADING_DAYS = PERIOD_3M

# ────────── SQL: 在数据库中完成 ROC 计算 ──────────
# 用窗口函数为每只股票按日期排序，取最新价和 N 天前的价格
# 只返回每只股票的一行聚合结果（~5000 行），内存 <50MB
RS_RATING_SQL = text("""
WITH ranked AS (
    SELECT
        ts_code,
        name,
        trade_date,
        close,
        ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn,
        COUNT(*) OVER (PARTITION BY ts_code) AS total_days
    FROM stock_daily_quote
    WHERE trade_date >= CURRENT_DATE - make_interval(days => :lookback_days)
      AND close IS NOT NULL AND close > 0
),
pivoted AS (
    SELECT
        ts_code,
        MAX(name) AS name,
        MAX(trade_date) FILTER (WHERE rn = 1) AS latest_date,
        MAX(total_days) AS total_days,
        MAX(CASE WHEN rn = 1 THEN close END) AS latest_close,
        MAX(CASE WHEN rn = :p3 THEN close END) AS close_p3,
        MAX(CASE WHEN rn = :p6 THEN close END) AS close_p6,
        MAX(CASE WHEN rn = :p9 THEN close END) AS close_p9,
        MAX(CASE WHEN rn = :p12 THEN close END) AS close_p12
    FROM ranked
    GROUP BY ts_code
    HAVING MAX(total_days) >= :min_days
)
SELECT
    ts_code,
    name,
    latest_date,
    total_days,
    CASE WHEN close_p3 IS NOT NULL AND close_p3 > 0
         THEN ROUND(CAST((latest_close / close_p3 - 1) * 100 AS numeric), 2) END AS p3,
    CASE WHEN close_p6 IS NOT NULL AND close_p6 > 0
         THEN ROUND(CAST((latest_close / close_p6 - 1) * 100 AS numeric), 2) END AS p6,
    CASE WHEN close_p9 IS NOT NULL AND close_p9 > 0
         THEN ROUND(CAST((latest_close / close_p9 - 1) * 100 AS numeric), 2) END AS p9,
    CASE WHEN close_p12 IS NOT NULL AND close_p12 > 0
         THEN ROUND(CAST((latest_close / close_p12 - 1) * 100 AS numeric), 2) END AS p12
FROM pivoted
WHERE close_p3 IS NOT NULL
""")


# ============================================================
# 1. 纯 SQL 计算 RS Rating（内存友好）
# ============================================================

async def _compute_rs_rating_sql() -> pd.DataFrame:
    """通过 SQL 窗口函数在 PostgreSQL 中计算 RS Rating。

    只返回 ~5000 行聚合结果，内存 <50MB。
    """
    async with async_session() as session:
        result = await session.execute(
            RS_RATING_SQL,
            {
                "lookback_days": PERIOD_12M + 30,  # 多留 30 天余量
                "p3": PERIOD_3M,
                "p6": PERIOD_6M,
                "p9": PERIOD_9M,
                "p12": PERIOD_12M,
                "min_days": MIN_TRADING_DAYS,
            },
        )
        rows = result.fetchall()

    if not rows:
        logger.error("SQL 查询无结果，数据库可能无行情数据")
        return pd.DataFrame(columns=["ts_code", "name", "trade_date", "rs_rating"])

    # 构建 DataFrame（~5000 行，非常轻量）
    records = []
    for r in rows:
        p3, p6, p9, p12 = r.p3, r.p6, r.p9, r.p12
        rocs = {"p3": (p3, 0.4), "p6": (p6, 0.2), "p9": (p9, 0.2), "p12": (p12, 0.2)}
        valid_weight = sum(w for v, w in rocs.values() if v is not None)
        if valid_weight == 0:
            continue
        score = sum(
            (w / valid_weight) * float(v)
            for v, w in rocs.values()
            if v is not None
        )
        records.append({
            "ts_code": r.ts_code,
            "name": r.name or "",
            "trade_date": r.latest_date,
            "p3": float(p3) if p3 is not None else None,
            "p6": float(p6) if p6 is not None else None,
            "p9": float(p9) if p9 is not None else None,
            "p12": float(p12) if p12 is not None else None,
            "score": round(score, 4),
        })

    if not records:
        logger.error("没有股票满足最低数据量要求")
        return pd.DataFrame(columns=["ts_code", "name", "trade_date", "rs_rating"])

    rating_df = pd.DataFrame(records)

    # 百分位排名 → 映射为 1~99
    rating_df["rs_rating"] = (
        rating_df["score"]
        .rank(pct=True)
        .mul(98)
        .add(1)
        .round(0)
        .astype(int)
        .clip(1, 99)
    )

    rating_df.sort_values("rs_rating", ascending=False, inplace=True)
    rating_df.reset_index(drop=True, inplace=True)

    logger.info(
        "RS Rating 计算完成（SQL 模式）：共 %d 只股票，日期 %s",
        len(rating_df),
        rating_df["trade_date"].iloc[0],
    )
    return rating_df


# ============================================================
# 2. 异步入口：计算并持久化
# ============================================================

async def compute_rs_rating(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """计算全市场 RS Rating（异步入口）。

    v2: 忽略 df 参数，直接使用 SQL 计算，避免加载全量行情到内存。
    保留参数签名以兼容旧调用方。
    """
    return await _compute_rs_rating_sql()


async def compute_and_save_rs_rating(force_refresh: bool = False) -> pd.DataFrame:
    """计算 RS Rating 并写入 PostgreSQL（主入口）。

    v2: 不再加载全量行情到内存，通过 SQL 直接在 DB 中计算。
    force_refresh 控制是否跳过缓存检查。

    Args:
        force_refresh: 为 True 时强制重新计算。

    Returns:
        RS Rating DataFrame。
    """
    # 检查今天是否已有 RS Rating 数据
    if not force_refresh:
        today = date.today()
        async with async_session() as session:
            result = await session.execute(
                select(func.count())
                .select_from(StockRSRating)
                .where(StockRSRating.trade_date == today)
            )
            count = result.scalar() or 0
            if count > 0:
                logger.info("今天的 RS Rating 已存在（%d 条），跳过计算", count)
                return await load_rs_rating(today)

    # 直接在 SQL 中计算，内存 <50MB
    logger.info("开始 RS Rating 计算（SQL 模式，force_refresh=%s）...", force_refresh)
    rating_df = await _compute_rs_rating_sql()

    if rating_df.empty:
        return rating_df

    # 写入 PostgreSQL
    records = rating_df.to_dict("records")
    batch_size = 2000

    async with async_session() as session:
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            stmt = pg_insert(StockRSRating).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_rs_code_date",
                set_={
                    "name": stmt.excluded.name,
                    "p3": stmt.excluded.p3,
                    "p6": stmt.excluded.p6,
                    "p9": stmt.excluded.p9,
                    "p12": stmt.excluded.p12,
                    "score": stmt.excluded.score,
                    "rs_rating": stmt.excluded.rs_rating,
                },
            )
            await session.execute(stmt)
        await session.commit()

    logger.info("RS Rating 已写入 PostgreSQL，共 %d 条", len(records))
    return rating_df


async def load_rs_rating(
    target_date: date | None = None,
    top_n: int | None = None,
    min_rating: int | None = None,
) -> pd.DataFrame:
    """从 PostgreSQL 加载 RS Rating。

    Args:
        target_date: 查询日期，默认今天。
        top_n: 取前 N 名。
        min_rating: 最低 RS Rating 阈值。

    Returns:
        RS Rating DataFrame。
    """
    if target_date is None:
        target_date = date.today()

    async with async_session() as session:
        # 若指定日期无数据，自动回退到最近有数据的交易日
        check = await session.execute(
            select(func.count())
            .select_from(StockRSRating)
            .where(StockRSRating.trade_date == target_date)
        )
        if (check.scalar() or 0) == 0:
            latest = await session.execute(
                select(StockRSRating.trade_date)
                .order_by(StockRSRating.trade_date.desc())
                .limit(1)
            )
            row = latest.scalar()
            if row is not None:
                logger.info("日期 %s 无数据，回退到最近交易日 %s", target_date, row)
                target_date = row

        query = (
            select(
                StockRSRating,
                StockDailyQuote.close.label("close"),
                StockDailyQuote.pct_change.label("pct_change"),
                StockDailyQuote.change.label("change"),
            )
            .outerjoin(
                StockDailyQuote,
                (StockRSRating.ts_code == StockDailyQuote.ts_code)
                & (StockRSRating.trade_date == StockDailyQuote.trade_date),
            )
            .where(StockRSRating.trade_date == target_date)
            .order_by(
                StockRSRating.rs_rating.desc(),
                StockDailyQuote.pct_change.desc().nulls_last(),
                StockDailyQuote.close.desc().nulls_last(),
            )
        )
        if min_rating is not None:
            query = query.where(StockRSRating.rs_rating >= min_rating)
        if top_n is not None:
            query = query.limit(top_n)

        result = await session.execute(query)
        rows = result.all()

    if not rows:
        return pd.DataFrame(columns=["ts_code", "name", "trade_date", "rs_rating"])

    def _safe(v):
        """Convert NaN/inf to None for JSON serialization."""
        if v is None:
            return None
        try:
            import math
            if math.isnan(v) or math.isinf(v):
                return None
        except (TypeError, ValueError):
            pass
        return v

    data = [
        {
            "ts_code": r.StockRSRating.ts_code,
            "name": r.StockRSRating.name,
            "trade_date": r.StockRSRating.trade_date,
            "p3": _safe(r.StockRSRating.p3),
            "p6": _safe(r.StockRSRating.p6),
            "p9": _safe(r.StockRSRating.p9),
            "p12": _safe(r.StockRSRating.p12),
            "score": _safe(r.StockRSRating.score),
            "rs_rating": r.StockRSRating.rs_rating,
            "close": _safe(r.close),
            "pct_change": _safe(r.pct_change),
            "change": _safe(r.change),
        }
        for r in rows
    ]
    result_df = pd.DataFrame(data)
    # 最终兜底：确保无 NaN/inf 残留
    result_df = result_df.replace({np.nan: None, np.inf: None, -np.inf: None})
    return result_df


# ============================================================
# 直接运行入口（开发调试用）
# ============================================================

if __name__ == "__main__":
    import asyncio as _asyncio

    async def _main():
        rs = await compute_rs_rating()

        if rs.empty:
            print("[ERROR] 无可用数据，请先确保数据库连接正常。")
            return

        print("\n===== RS Rating Top 20 =====")
        print(rs.head(20).to_string(index=False))

        print("\n===== RS Rating Bottom 10 =====")
        print(rs.tail(10).to_string(index=False))

        print(f"\n总计: {len(rs)} 只股票")

    _asyncio.run(_main())
