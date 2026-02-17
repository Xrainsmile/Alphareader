"""Alphareader — RS Rating 计算模块（异步版）。

职责：
  基于 IBD/Minervini 方法，计算 A 股个股相对强度评分（RS Rating）。

算法：
  1. 计算 4 个周期的涨跌幅 (ROC)：3/6/9/12 个月
  2. 加权得分：Score = 0.4*P3 + 0.2*P6 + 0.2*P9 + 0.2*P12
  3. 百分位排名映射为 1~99 整数（99 = 最强）

核心逻辑：
  - 从 PostgreSQL 读取行情数据（通过 data_fetcher）
  - 纯 pandas/numpy 计算在 asyncio.to_thread() 中执行
  - 计算结果写入 stock_rs_rating 表

错误处理：
  - 数据不足的股票自动跳过（至少需要 63 个交易日）
  - 全局异常向上抛出
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.stock import StockDailyQuote, StockRSRating
from app.services.data_fetcher import fetch_stock_list, get_all_stock_data, load_from_db

logger = logging.getLogger("alphareader.indicators")

# ────────── 周期配置（交易日） ──────────
PERIOD_3M = 63
PERIOD_6M = 126
PERIOD_9M = 189
PERIOD_12M = 252

WEIGHTS = {
    "P3": 0.4,
    "P6": 0.2,
    "P9": 0.2,
    "P12": 0.2,
}

MIN_TRADING_DAYS = PERIOD_3M


# ============================================================
# 1. 计算单只股票的多周期 ROC
# ============================================================

def _calc_roc(group: pd.DataFrame) -> pd.Series | None:
    """对单只股票的日线数据计算 4 个周期的涨跌幅。

    当数据不足某个长周期时，该周期记为 NaN，
    加权得分按可用周期的权重重新归一化。
    至少需要 3 个月（63 天）数据。
    """
    n = len(group)
    if n < MIN_TRADING_DAYS:
        return None

    close = group["收盘"].values
    latest = close[-1]

    p3 = (latest / close[-PERIOD_3M] - 1) * 100 if n >= PERIOD_3M else np.nan
    p6 = (latest / close[-PERIOD_6M] - 1) * 100 if n >= PERIOD_6M else np.nan
    p9 = (latest / close[-PERIOD_9M] - 1) * 100 if n >= PERIOD_9M else np.nan
    p12 = (latest / close[-PERIOD_12M] - 1) * 100 if n >= PERIOD_12M else np.nan

    rocs = {"P3": p3, "P6": p6, "P9": p9, "P12": p12}
    valid_weight_sum = sum(WEIGHTS[k] for k, v in rocs.items() if not np.isnan(v))

    if valid_weight_sum == 0:
        return None

    score = sum(
        WEIGHTS[k] / valid_weight_sum * v
        for k, v in rocs.items()
        if not np.isnan(v)
    )

    return pd.Series({
        "P3": round(p3, 2),
        "P6": round(p6, 2),
        "P9": round(p9, 2),
        "P12": round(p12, 2),
        "Score": round(score, 4),
    })


# ============================================================
# 2. 计算全市场 RS Rating（纯计算，同步）
# ============================================================

def _compute_rs_rating_sync(df: pd.DataFrame) -> pd.DataFrame:
    """同步版 RS Rating 计算核心，在 to_thread 中执行。"""
    if df.empty:
        logger.error("输入数据为空，无法计算 RS Rating")
        return pd.DataFrame(columns=["ts_code", "name", "trade_date", "rs_rating"])

    df = df.copy()
    df["日期"] = pd.to_datetime(df["日期"])
    df.sort_values(by=["股票代码", "日期"], inplace=True)

    latest_date = df["日期"].max()

    # 构建股票名称映射
    name_map: dict[str, str] = {}
    if "名称" in df.columns:
        name_map = (
            df.drop_duplicates(subset="股票代码", keep="last")
            .set_index("股票代码")["名称"]
            .to_dict()
        )

    records: list[dict] = []
    grouped = df.groupby("股票代码", sort=False)

    for code, group in grouped:
        result = _calc_roc(group)
        if result is not None and not np.isnan(result["Score"]):
            records.append({
                "ts_code": code,
                "name": name_map.get(code, ""),
                "trade_date": latest_date.date() if hasattr(latest_date, "date") else latest_date,
                "p3": None if np.isnan(result["P3"]) else result["P3"],
                "p6": None if np.isnan(result["P6"]) else result["P6"],
                "p9": None if np.isnan(result["P9"]) else result["P9"],
                "p12": None if np.isnan(result["P12"]) else result["P12"],
                "score": result["Score"],
            })

    if not records:
        logger.error("没有股票满足最低数据量要求，无法生成 RS Rating")
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
        "RS Rating 计算完成：共 %d 只股票，日期 %s",
        len(rating_df),
        rating_df["trade_date"].iloc[0],
    )
    return rating_df


# ============================================================
# 3. 异步入口：计算并持久化
# ============================================================

async def compute_rs_rating(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """计算全市场 RS Rating（异步入口）。

    Args:
        df: 行情 DataFrame；为 None 时自动从 data_fetcher 获取。

    Returns:
        包含 RS Rating 的 DataFrame。
    """
    if df is None:
        df = await get_all_stock_data()

    result = await asyncio.to_thread(_compute_rs_rating_sync, df)
    return result


async def compute_and_save_rs_rating(force_refresh: bool = False) -> pd.DataFrame:
    """计算 RS Rating 并写入 PostgreSQL（主入口）。

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

    # 获取行情数据 → 计算
    stock_data = await get_all_stock_data(force_refresh=force_refresh)
    rating_df = await compute_rs_rating(stock_data)

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
            .order_by(StockRSRating.rs_rating.desc())
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
    return pd.DataFrame(data)


# ============================================================
# 直接运行入口（开发调试用）
# ============================================================

if __name__ == "__main__":
    import asyncio as _asyncio

    async def _main():
        stock_data = await get_all_stock_data()

        if stock_data.empty:
            print("[ERROR] 无可用数据，请先确保数据库连接正常。")
            return

        rs = await compute_rs_rating(stock_data)

        print("\n===== RS Rating Top 20 =====")
        print(rs.head(20).to_string(index=False))

        print("\n===== RS Rating Bottom 10 =====")
        print(rs.tail(10).to_string(index=False))

        print(f"\n总计: {len(rs)} 只股票")

    _asyncio.run(_main())
