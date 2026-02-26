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
_PIVOTED_SELECT_SQL = """
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
"""

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
""" + _PIVOTED_SELECT_SQL)

# 支持指定截止日期的 SQL（用于历史回填）
RS_RATING_SQL_AT_DATE = text("""
WITH ranked AS (
    SELECT
        ts_code,
        name,
        trade_date,
        close,
        ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn,
        COUNT(*) OVER (PARTITION BY ts_code) AS total_days
    FROM stock_daily_quote
    WHERE trade_date <= :target_date
      AND trade_date >= :target_date - make_interval(days => :lookback_days)
      AND close IS NOT NULL AND close > 0
),
""" + _PIVOTED_SELECT_SQL)


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
# 1b. 指定日期计算 RS Rating（用于历史回填）
# ============================================================

async def _compute_rs_rating_at_date(target_date: date) -> pd.DataFrame:
    """计算指定日期的 RS Rating（基于截止到该日期的行情数据）。"""
    async with async_session() as session:
        result = await session.execute(
            RS_RATING_SQL_AT_DATE,
            {
                "target_date": target_date,
                "lookback_days": PERIOD_12M + 30,
                "p3": PERIOD_3M,
                "p6": PERIOD_6M,
                "p9": PERIOD_9M,
                "p12": PERIOD_12M,
                "min_days": MIN_TRADING_DAYS,
            },
        )
        rows = result.fetchall()

    if not rows:
        return pd.DataFrame(columns=["ts_code", "name", "trade_date", "rs_rating"])

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
        return pd.DataFrame(columns=["ts_code", "name", "trade_date", "rs_rating"])

    rating_df = pd.DataFrame(records)
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
    return rating_df


async def backfill_rs_rating(
    start_date: date,
    end_date: date,
    skip_existing: bool = True,
) -> dict:
    """回填指定日期范围的 RS Rating。

    对于非交易日（数据库无行情数据的日子），复制上一个最近交易日的数据。

    Args:
        start_date: 起始日期
        end_date: 结束日期（含）
        skip_existing: 为 True 时跳过已有数据的日期

    Returns:
        {"computed": N, "copied": N, "skipped": N, "failed": N}
    """
    from datetime import timedelta

    # 1. 获取行情表中日期范围内的所有实际交易日
    async with async_session() as session:
        result = await session.execute(
            select(StockDailyQuote.trade_date)
            .where(StockDailyQuote.trade_date.between(start_date, end_date))
            .distinct()
            .order_by(StockDailyQuote.trade_date)
        )
        trading_dates = [row[0] for row in result.all()]

    if not trading_dates:
        logger.warning("回填范围内无交易日行情数据: %s ~ %s", start_date, end_date)
        return {"computed": 0, "copied": 0, "skipped": 0, "failed": 0}

    logger.info(
        "开始回填 RS Rating: %s ~ %s，共 %d 个交易日",
        start_date, end_date, len(trading_dates),
    )

    # 2. 查询已有 RS Rating 数据的日期
    existing_dates = set()
    if skip_existing:
        async with async_session() as session:
            result = await session.execute(
                select(StockRSRating.trade_date)
                .where(StockRSRating.trade_date.between(start_date, end_date))
                .distinct()
            )
            existing_dates = {row[0] for row in result.all()}

    stats = {"computed": 0, "copied": 0, "skipped": 0, "failed": 0}
    last_computed_date = None

    # 3. 逐个交易日计算
    for td in trading_dates:
        if td in existing_dates:
            logger.info("跳过已有数据: %s", td)
            stats["skipped"] += 1
            last_computed_date = td
            continue

        try:
            rating_df = await _compute_rs_rating_at_date(td)
            if rating_df.empty:
                logger.warning("日期 %s 计算结果为空，跳过", td)
                stats["failed"] += 1
                continue

            # 确保 trade_date 统一为该交易日
            rating_df["trade_date"] = td

            # 写入 DB
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

            stats["computed"] += 1
            last_computed_date = td
            logger.info("回填完成: %s（%d 只股票）", td, len(rating_df))
        except Exception as e:
            logger.error("回填日期 %s 失败: %s", td, e)
            stats["failed"] += 1

    # 4. 填充非交易日（周末/节假日）：复制上一个最近交易日的数据
    all_dates = set()
    d = start_date
    while d <= end_date:
        all_dates.add(d)
        d += timedelta(days=1)

    non_trading_dates = sorted(all_dates - set(trading_dates) - existing_dates)

    if non_trading_dates and trading_dates:
        # 构建日期→最近交易日的映射
        sorted_trading = sorted(set(trading_dates) | existing_dates)
        for ntd in non_trading_dates:
            # 找到 <= ntd 的最近交易日
            prev_td = None
            for t in sorted_trading:
                if t <= ntd:
                    prev_td = t
                else:
                    break
            if prev_td is None:
                continue

            # 检查是否已有该非交易日的数据
            async with async_session() as session:
                check = await session.execute(
                    select(func.count())
                    .select_from(StockRSRating)
                    .where(StockRSRating.trade_date == ntd)
                )
                if (check.scalar() or 0) > 0:
                    stats["skipped"] += 1
                    continue

            # 从上一个交易日复制数据，修改 trade_date
            async with async_session() as session:
                prev_data = await session.execute(
                    select(StockRSRating)
                    .where(StockRSRating.trade_date == prev_td)
                )
                prev_rows = prev_data.scalars().all()
                if not prev_rows:
                    continue

                copy_records = [
                    {
                        "ts_code": r.ts_code,
                        "name": r.name,
                        "trade_date": ntd,
                        "p3": r.p3,
                        "p6": r.p6,
                        "p9": r.p9,
                        "p12": r.p12,
                        "score": r.score,
                        "rs_rating": r.rs_rating,
                    }
                    for r in prev_rows
                ]

                for i in range(0, len(copy_records), 2000):
                    batch = copy_records[i : i + 2000]
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

            stats["copied"] += 1
            logger.info("非交易日 %s 已复制自 %s（%d 只股票）", ntd, prev_td, len(copy_records))

    logger.info("回填完成: %s", stats)
    return stats


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
