"""市场指标计算 — 为 VCP 市场适配度提供底层数据。

依赖：stock_daily_quote（个股日行情）、index_daily（基准指数日行情）。

计算项：
  - 基准指数序列（优先真实指数，缺失时合成等权代理）
  - 大盘趋势衍生：收盘 / MA20 / MA60 / MA20 斜率 / MA60 斜率
  - 波动环境：20 日实现波动率、近 250 日波动率分位、近 5 日波动冲击
  - 市场宽度：收盘价位于 20 日均线上方的股票占比
  - 交易活跃度：当日总成交额 / 近 20 日平均日成交额
  - 突破有效性：近 30 个交易日内突破事件、突破后 5 日正收益比例

所有计算均基于「交易日历」，非交易日沿用最近交易日数据。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.market import IndexDaily
from app.models.stock import StockDailyQuote
from app.services.strategy_config import BENCHMARK_INDEX

logger = logging.getLogger("alphareader.market_metrics")

# 市场宽度股票池过滤：剔除 ST / 当日无有效收盘 / 无成交
_POOL_FILTER = "AND name NOT LIKE '%ST%' AND close IS NOT NULL AND close > 0 AND volume IS NOT NULL AND volume > 0"


# ============================================================
# 1. 基准指数序列
# ============================================================

async def load_benchmark_index(market: str, target_date: date) -> pd.DataFrame:
    """加载基准指数收盘价序列（升序 trade_date）。

    优先使用 index_daily 中的真实指数（CN=000300 / US=^GSPC）；
    若不足 250 个交易日（波动率分位需要），则用个股等权收益率合成代理，
    保证适配度在指数采集缺失时仍可计算（并在 reason 中标记）。

    Returns:
        DataFrame[ trade_date, close, source ]  source ∈ {real, synthetic}
    """
    bench = BENCHMARK_INDEX.get(market, BENCHMARK_INDEX["CN"])
    codes = [bench["primary"]] + list(bench.get("alternatives", []))

    df = None
    for code in codes:
        async with async_session() as session:
            result = await session.execute(
                select(IndexDaily.trade_date, IndexDaily.close, IndexDaily.source)
                .where(IndexDaily.index_code == code)
                .where(IndexDaily.trade_date <= target_date)
                .order_by(IndexDaily.trade_date.asc())
            )
            rows = result.all()
        if rows and len(rows) >= 250:
            df = pd.DataFrame(
                [(r.trade_date, float(r.close), r.source or "real") for r in rows],
                columns=["trade_date", "close", "source"],
            )
            break

    if df is not None:
        return df

    # 真实指数不足 → 合成等权代理（基于全市场日收益率均值滚动累计）
    logger.info("基准指数 %s 数据不足，改用个股等权合成代理（market=%s）", code, market)
    return await _synthetic_benchmark(market, target_date)


async def _synthetic_benchmark(market: str, target_date: date) -> pd.DataFrame:
    """用个股日收益率均值合成等权市场指数（起点 1000）。"""
    start = target_date - timedelta(days=420)
    async with async_session() as session:
        result = await session.execute(
            text(
                """
                SELECT trade_date, AVG(pct_change) AS avg_ret
                FROM stock_daily_quote
                WHERE market = :m
                  AND trade_date <= :target
                  AND trade_date >= :start
                  AND pct_change IS NOT NULL
                  AND name NOT LIKE '%ST%'
                GROUP BY trade_date
                ORDER BY trade_date ASC
                """
            ),
            {"m": market, "target": target_date, "start": start},
        )
        rows = result.all()

    if not rows:
        return pd.DataFrame(columns=["trade_date", "close", "source"])

    s = pd.DataFrame([(r[0], float(r[1])) for r in rows], columns=["trade_date", "avg_ret"])
    s["ret"] = s["avg_ret"] / 100.0
    s["close"] = (1 + s["ret"]).cumprod() * 1000.0
    s["source"] = "synthetic"
    return s[["trade_date", "close", "source"]]


# ============================================================
# 2. 大盘趋势 & 波动环境 衍生指标
# ============================================================

def _benchmark_derived(series: pd.DataFrame) -> dict:
    """从基准指数序列计算趋势 / 波动衍生指标。

    返回 dict：close, ma20, ma60, ma20_slope_up, ma60_slope_down,
              vol_20d, vol_pct_250, vol_shock (近5日波动率增幅)
    """
    out = {
        "close": None, "ma20": None, "ma60": None,
        "ma20_slope_up": None, "ma60_slope_down": None,
        "vol_20d": None, "vol_pct_250": None, "vol_shock": None,
    }
    if series is None or len(series) < 2:
        return out

    close = series["close"].astype(float).reset_index(drop=True)
    n = len(close)
    out["close"] = float(close.iloc[-1])

    if n >= 20:
        ma20_now = float(close.iloc[-20:].mean())
        out["ma20"] = ma20_now
        if n >= 25:
            ma20_prev = float(close.iloc[-25:-5].mean())
            out["ma20_slope_up"] = ma20_now > ma20_prev
    if n >= 60:
        ma60_now = float(close.iloc[-60:].mean())
        out["ma60"] = ma60_now
        if n >= 65:
            ma60_prev = float(close.iloc[-65:-5].mean())
            out["ma60_slope_down"] = ma60_now < ma60_prev

    # 日收益率
    rets = close.pct_change().dropna()
    if len(rets) >= 20:
        vol_now = float(rets.iloc[-20:].std() * np.sqrt(252))
        out["vol_20d"] = vol_now
        # MA20 斜率（5 个交易日前）
        if len(rets) >= 25:
            vol_prev = float(rets.iloc[-25:-5].std() * np.sqrt(252))
            if vol_prev and vol_prev > 0:
                out["vol_shock"] = vol_now / vol_prev - 1.0

    # 近 250 日波动率分位
    if len(rets) >= 60:
        roll_vol = rets.rolling(20).std() * np.sqrt(252)
        roll_vol = roll_vol.dropna()
        if len(roll_vol) >= 20:
            recent = roll_vol.iloc[-250:]
            vol_now_v = roll_vol.iloc[-1]
            out["vol_pct_250"] = float((recent <= vol_now_v).mean() * 100)
    return out


# ============================================================
# 3. 市场宽度（收盘价位于 20 日均线上方占比）
# ============================================================

async def compute_breadth(market: str, target_date: date) -> float | None:
    """返回 (0,100] 区间内「收盘价 >= 20 日均线」的股票占比。

    股票池：剔除 ST、当日无有效收盘、无成交、上市不足 20 个交易日的股票。
    """
    async with async_session() as session:
        result = await session.execute(
            text(
                f"""
                WITH ranked AS (
                    SELECT ts_code, trade_date, close,
                        ROW_NUMBER() OVER (
                            PARTITION BY ts_code ORDER BY trade_date DESC
                        ) AS rn,
                        AVG(close) OVER (
                            PARTITION BY ts_code ORDER BY trade_date
                            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                        ) AS ma20
                    FROM stock_daily_quote
                    WHERE market = :m
                      AND trade_date <= :target
                      AND trade_date >= :target - make_interval(days => 130)
                      {_POOL_FILTER}
                )
                SELECT
                    COUNT(*) FILTER (WHERE close >= ma20) AS above,
                    COUNT(*) FILTER (WHERE close < ma20)  AS below
                FROM ranked
                WHERE rn = 1 AND trade_date = :target AND ma20 IS NOT NULL
                """
            ),
            {"m": market, "target": target_date},
        )
        row = result.first()
        if row is None or (row.above is None and row.below is None):
            return None
        above = row.above or 0
        below = row.below or 0
        total = above + below
        if total == 0:
            return None
        return round(above / total * 100, 2)
    return None


# ============================================================
# 4. 交易活跃度（成交额比）
# ============================================================

async def compute_turnover_ratio(market: str, target_date: date) -> float | None:
    """当日总成交额 / 最近 20 个交易日（不含当日）平均日成交额。"""
    async with async_session() as session:
        result = await session.execute(
            text(
                """
                SELECT trade_date, SUM(amount) AS amt
                FROM stock_daily_quote
                WHERE market = :m
                  AND trade_date <= :target
                  AND trade_date >= :target - make_interval(days => 25)
                  AND amount IS NOT NULL
                GROUP BY trade_date
                ORDER BY trade_date ASC
                """
            ),
            {"m": market, "target": target_date},
        )
        rows = result.all()
    if not rows:
        return None
    by_date = {r[0]: float(r[1]) for r in rows}
    today = by_date.get(target_date)
    prior = [v for d, v in by_date.items() if d < target_date]
    if today is None or len(prior) < 5:
        return None
    avg20 = sum(prior) / len(prior)
    if avg20 <= 0:
        return None
    return round(today / avg20 * 100, 2)


# ============================================================
# 5. 突破有效性（突破事件 + 突破后 5 日正收益比例）
# ============================================================

async def compute_breakout(market: str, target_date: date) -> dict:
    """计算突破有效性。

    突破定义（PRD 6.4）：当日收盘价突破过去 60 日最高收盘价，
    且当日成交量 >= 20 日均量 × 1.2。

    统计窗口：事件日落在 [target-30, target-5]（保证有 5 个交易日
    后续收益），计算突破后 5 日正收益比例。
    同时返回 target 当日突破股票数（用于筛选摘要「突破确认」）。

    Returns:
        { sample_count, positive_ratio(0-100 or None), breakout_today }
    """
    start = target_date - timedelta(days=140)  # 需 60 日前高 + 5 日后向
    async with async_session() as session:
        result = await session.execute(
            text(
                f"""
                SELECT ts_code, trade_date, close, volume, name
                FROM stock_daily_quote
                WHERE market = :m
                  AND trade_date <= :target
                  AND trade_date >= :start
                  {_POOL_FILTER}
                ORDER BY ts_code, trade_date ASC
                """
            ),
            {"m": market, "target": target_date, "start": start},
        )
        rows = result.all()

    empty = {"sample_count": 0, "positive_ratio": None, "breakout_today": 0}
    if not rows:
        return empty

    df = pd.DataFrame(
        [(r[0], r[1], float(r[2]), float(r[3])) for r in rows],
        columns=["ts_code", "trade_date", "close", "volume"],
    )
    df["prev60_high"] = (
        df.groupby("ts_code")["close"]
        .transform(lambda s: s.shift(1).rolling(60, min_periods=60).max())
    )
    df["vol20"] = (
        df.groupby("ts_code")["volume"]
        .transform(lambda s: s.rolling(20, min_periods=20).mean())
    )
    df["fwd5_close"] = df.groupby("ts_code")["close"].shift(-5)
    df["breakout"] = (
        df["close"] > df["prev60_high"].fillna(-1)
    ) & (df["volume"] >= 1.2 * df["vol20"].fillna(0))

    # 当日突破数
    today_mask = (df["trade_date"] == target_date) & df["breakout"]
    breakout_today = int(today_mask.sum())

    # 事件窗口 [target-30, target-5]
    lo = target_date - timedelta(days=30)
    hi = target_date - timedelta(days=5)
    ev_mask = df["breakout"] & (df["trade_date"] >= lo) & (df["trade_date"] <= hi)
    ev = df[ev_mask].copy()
    if ev.empty:
        return {"sample_count": 0, "positive_ratio": None, "breakout_today": breakout_today}

    ev["fwd_ret"] = ev["fwd5_close"] / ev["close"] - 1.0
    ev = ev.dropna(subset=["fwd_ret"])
    sample = len(ev)
    if sample == 0:
        return {"sample_count": 0, "positive_ratio": None, "breakout_today": breakout_today}
    pos = float((ev["fwd_ret"] > 0).mean() * 100)
    return {
        "sample_count": sample,
        "positive_ratio": round(pos, 2),
        "breakout_today": breakout_today,
    }


# ============================================================
# 6. 聚合：单次调用拿到全部指标
# ============================================================

async def compute_market_metrics(market: str, target_date: date) -> dict:
    """聚合市场指标，供 VCP 适配度服务使用。"""
    bench_df = await load_benchmark_index(market, target_date)
    derived = _benchmark_derived(bench_df)

    breadth = await compute_breadth(market, target_date)
    turnover = await compute_turnover_ratio(market, target_date)
    breakout = await compute_breakout(market, target_date)

    return {
        "market": market,
        "trade_date": target_date,
        "benchmark_source": bench_df["source"].iloc[-1] if not bench_df.empty else None,
        "benchmark_derived": derived,
        "breadth_pct": breadth,
        "turnover_ratio": turnover,
        "breakout": breakout,
    }
