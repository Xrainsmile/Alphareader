"""右侧趋势过滤器 — 双均线趋势突破量化漏斗。

基于 youce.md 的右侧趋势策略（简化为 5 条核心条件），适配 A 股市场。

过滤器设计为纯函数式（输入 DataFrame → 输出 DataFrame），
每个过滤步骤独立可测试、可跳过。

数学公式说明：

  ┌──────────────────────────────────────────────────────────────┐
  │ 右侧趋势过滤器 (5 条核心条件全部满足)                          │
  ├──────────────────────────────────────────────────────────────┤
  │ 基础筛选：                                                     │
  │   - 排除 ST 股票（由 pipeline 层处理）                         │
  │   - 日均成交额 > 2000 万（近 20 日均值）                       │
  │                                                               │
  │ 条件 T1 — MA 多头排列                                         │
  │   Close > SMA20 > SMA50，SMA20 向上（SMA50 向上可选）          │
  │                                                               │
  │ 条件 T2 — ADX 趋势强度                                        │
  │   ADX(14) > 20，确认有趋势（非震荡）                           │
  │                                                               │
  │ 条件 T3 — 近期高点突破                                       │
  │   近 3 天内 Close 曾 >= max(High, 10日)，价格创新高            │
  │                                                               │
  │ 条件 T4 — 近期放量确认                                         │
  │   近 3 天内 Volume 曾 > MA(Volume, 20日) × 1.2                 │
  │                                                               │
  │ 条件 T5 — RSI 动量区间                                         │
  │   45 < RSI(14) < 85，有动量但不过热                            │
  └──────────────────────────────────────────────────────────────┘

趋势得分 (trend_score)：
  = 0.4 × ADX_norm + 0.3 × RSI_norm + 0.3 × VolRatio_norm
  ADX_norm   = min(ADX / 50, 1.0)
  RSI_norm   = clamp((RSI - 50) / 30, 0, 1)
  VolRatio_norm = min(vol_ratio / 3.0, 1.0)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger("alphareader.screener.trend_filters")


# ════════════════════════════════════════════════════════════════
# 技术指标计算函数（纯向量化）
# ════════════════════════════════════════════════════════════════

def _compute_sma(series: pd.Series, window: int) -> pd.Series:
    """计算简单移动平均线 (SMA)。"""
    return series.rolling(window=window, min_periods=window).mean()


def _compute_adx(group: pd.DataFrame, period: int = 14) -> float:
    """计算单只股票的 ADX(period) 值 — Wilder's Average Directional Index。

    步骤：
      1. 计算 +DM / -DM（方向移动）
      2. 计算 TR（真实波幅）
      3. 用 Wilder 平滑（EMA with alpha=1/period）计算 ATR14, +DM14, -DM14
      4. 计算 +DI / -DI
      5. 计算 DX = |+DI - -DI| / (+DI + -DI)
      6. 用 Wilder 平滑 DX 得到 ADX

    Args:
        group: 单只股票的 OHLCV DataFrame（已按日期升序排列）
        period: ADX 周期（默认 14）

    Returns:
        最新一天的 ADX 值（float），数据不足时返回 NaN
    """
    if len(group) < period * 2 + 1:
        return np.nan

    high = group["high"].values
    low = group["low"].values
    close = group["close"].values

    n = len(high)

    # ── Step 1: +DM / -DM ──
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        h_diff = high[i] - high[i - 1]
        l_diff = low[i - 1] - low[i]

        plus_dm[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
        minus_dm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0

        # True Range
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # ── Step 2: Wilder 平滑（用 EMA with alpha = 1/period）──
    alpha = 1.0 / period

    # 初始值：前 period 个的简单平均
    atr = np.zeros(n)
    plus_dm_smooth = np.zeros(n)
    minus_dm_smooth = np.zeros(n)

    atr[period] = np.mean(tr[1 : period + 1])
    plus_dm_smooth[period] = np.mean(plus_dm[1 : period + 1])
    minus_dm_smooth[period] = np.mean(minus_dm[1 : period + 1])

    for i in range(period + 1, n):
        atr[i] = atr[i - 1] * (1 - alpha) + tr[i] * alpha
        plus_dm_smooth[i] = plus_dm_smooth[i - 1] * (1 - alpha) + plus_dm[i] * alpha
        minus_dm_smooth[i] = minus_dm_smooth[i - 1] * (1 - alpha) + minus_dm[i] * alpha

    # ── Step 3: +DI / -DI ──
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)

    for i in range(period, n):
        if atr[i] > 0:
            plus_di[i] = 100.0 * plus_dm_smooth[i] / atr[i]
            minus_di[i] = 100.0 * minus_dm_smooth[i] / atr[i]

        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum

    # ── Step 4: ADX = Wilder 平滑 DX ──
    adx = np.zeros(n)
    # ADX 需要第二轮平滑，从 2*period 开始
    start_idx = period * 2
    if start_idx >= n:
        return np.nan

    adx[start_idx] = np.mean(dx[period : start_idx + 1])
    for i in range(start_idx + 1, n):
        adx[i] = adx[i - 1] * (1 - alpha) + dx[i] * alpha

    return float(adx[-1])


def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    """计算 Wilder's RSI(period)。

    使用 Wilder 平滑法（EMA with alpha=1/period）计算平均涨跌幅。

    Args:
        closes: 收盘价数组（时间升序）
        period: RSI 周期

    Returns:
        最新一天的 RSI 值，数据不足时返回 NaN
    """
    if len(closes) < period + 1:
        return np.nan

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # 初始 avg_gain / avg_loss：前 period 个的简单平均
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    # Wilder 平滑
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


# ════════════════════════════════════════════════════════════════
# 配置类
# ════════════════════════════════════════════════════════════════

@dataclass
class TrendFilterConfig:
    """右侧趋势过滤器的可调参数。

    v2 调整说明（2026-03）：
      - T1: 仅要求 SMA20 向上，SMA50 向上为可选（require_ma50_up=False）
      - T2: ADX 阈值 25→20，捕捉趋势初期
      - T3: 突破从"当日新高"改为"近 3 天内曾创 10 日新高"
      - T4: 放量从"当日放量"改为"近 3 天内曾放量 1.2x"
      - T5: RSI 区间 50-80→45-85，放宽两端
    """

    # 基础筛选
    min_avg_amount: float = 2e7         # 日均成交额下限（2000 万元）
    amount_window: int = 20             # 成交额计算窗口（交易日）

    # 条件 T1: MA 多头排列
    ma_short: int = 20                  # 短期均线周期 (SMA20)
    ma_long: int = 50                   # 长期均线周期 (SMA50)
    ma_slope_window: int = 5            # 均线方向判断窗口（SMA 比 N 天前高则"向上"）
    require_ma50_up: bool = False       # 是否要求 SMA50 也向上（False=仅 SMA20 向上）

    # 条件 T2: ADX 趋势强度
    adx_period: int = 14                # ADX 周期
    adx_threshold: float = 20.0         # ADX 下限（v2: 25→20，捕捉趋势初期）

    # 条件 T3: 突破确认
    breakout_window: int = 10           # 突破回溯窗口（10 日新高）
    breakout_lookback: int = 3          # 近 N 天内曾出现突破即可（v2: 1→3）

    # 条件 T4: 放量确认
    volume_ratio: float = 1.2           # 放量倍数（v2: 1.5→1.2）
    volume_ma_window: int = 20          # 均量计算窗口
    volume_lookback: int = 3            # 近 N 天内曾放量即可（v2: 1→3）

    # 条件 T5: RSI 动量
    rsi_period: int = 14                # RSI 周期
    rsi_lower: float = 45.0             # RSI 下限（v2: 50→45）
    rsi_upper: float = 85.0             # RSI 上限（v2: 80→85）


# ════════════════════════════════════════════════════════════════
# 右侧趋势过滤器
# ════════════════════════════════════════════════════════════════

class TrendScreener:
    """右侧趋势过滤器 — 5 条技术面漏斗。

    输入：全市场 OHLCV 数据（已剔除 ST）
    输出：通过所有条件的股票及其指标

    用法：
        screener = TrendScreener(config)
        result_df = screener.apply(ohlcv)
    """

    def __init__(self, config: TrendFilterConfig | None = None):
        self.config = config or TrendFilterConfig()
        self._stats: dict[str, int] = {}

    @property
    def filter_stats(self) -> dict[str, int]:
        """返回每个过滤步骤的通过数量。"""
        return self._stats

    def apply(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        """执行完整的右侧趋势过滤管道。

        Args:
            ohlcv: 全市场近 80+ 天 OHLCV 数据
                   必须包含: ts_code, trade_date, open, close, high, low, volume, amount

        Returns:
            通过所有条件的股票 DataFrame，含以下额外列：
            ma20, ma50, adx, rsi, volume_ratio_val, trend_score, latest_close
        """
        cfg = self.config
        self._stats = {}

        total_stocks = ohlcv["ts_code"].nunique()
        self._stats["total_input"] = total_stocks
        logger.info("右侧趋势过滤开始 | 输入 %d 只股票", total_stocks)

        # 确保按 ts_code + trade_date 排序
        ohlcv = ohlcv.sort_values(["ts_code", "trade_date"])

        # ════════════════════════════════════════════
        # 基础筛选：日均成交额 > 2000 万
        # ════════════════════════════════════════════
        avg_amount = (
            ohlcv.groupby("ts_code")["amount"]
            .apply(lambda x: x.tail(cfg.amount_window).mean())
        )
        valid_codes = set(avg_amount[avg_amount >= cfg.min_avg_amount].index)
        self._stats["amount_filter"] = len(valid_codes)
        logger.info("基础筛选 日均成交额>%.0f万: %d/%d 通过",
                     cfg.min_avg_amount / 1e4, len(valid_codes), total_stocks)

        if not valid_codes:
            return pd.DataFrame()

        ohlcv = ohlcv[ohlcv["ts_code"].isin(valid_codes)]

        # ════════════════════════════════════════════
        # 逐股计算技术指标（向量化 + groupby apply）
        # ════════════════════════════════════════════
        indicators = []

        for ts_code, group in ohlcv.groupby("ts_code"):
            if len(group) < cfg.ma_long + cfg.ma_slope_window:
                continue

            closes = group["close"].values
            highs = group["high"].values
            volumes = group["volume"].values

            latest_close = closes[-1]
            latest_volume = volumes[-1]

            # ── SMA20 / SMA50 ──
            sma20_series = _compute_sma(group["close"], cfg.ma_short)
            sma50_series = _compute_sma(group["close"], cfg.ma_long)

            ma20 = sma20_series.iloc[-1]
            ma50 = sma50_series.iloc[-1]

            if pd.isna(ma20) or pd.isna(ma50):
                continue

            # 均线方向：最新 SMA > N 天前 SMA
            ma20_prev = sma20_series.iloc[-(cfg.ma_slope_window + 1)] if len(sma20_series) > cfg.ma_slope_window else np.nan
            ma50_prev = sma50_series.iloc[-(cfg.ma_slope_window + 1)] if len(sma50_series) > cfg.ma_slope_window else np.nan

            # ── ADX(14) ──
            adx = _compute_adx(group, cfg.adx_period)

            # ── RSI(14) ──
            rsi = _compute_rsi(closes, cfg.rsi_period)

            # ── T3: 近 breakout_lookback 天内是否曾创 breakout_window 日新高 ──
            breakout_hit = False
            for day_offset in range(cfg.breakout_lookback):
                idx = len(closes) - 1 - day_offset
                if idx < cfg.breakout_window:
                    break
                # 该日收盘价 vs 之前 breakout_window 日的最高 High
                prev_high = highs[idx - cfg.breakout_window : idx].max()
                if closes[idx] >= prev_high:
                    breakout_hit = True
                    break

            # ── T4: 近 volume_lookback 天内是否曾放量 ──
            vol_surge_hit = False
            max_vol_ratio = 0.0
            for day_offset in range(cfg.volume_lookback):
                idx = len(volumes) - 1 - day_offset
                if idx < cfg.volume_ma_window:
                    break
                vol_ma_at = volumes[idx - cfg.volume_ma_window : idx].mean()
                if vol_ma_at > 0:
                    ratio = volumes[idx] / vol_ma_at
                    max_vol_ratio = max(max_vol_ratio, ratio)
                    if ratio >= cfg.volume_ratio:
                        vol_surge_hit = True
                        break

            # 最新一天的量比（用于展示）
            vol_ma = volumes[-cfg.volume_ma_window:].mean() if len(volumes) >= cfg.volume_ma_window else volumes.mean()
            vol_ratio = latest_volume / vol_ma if vol_ma > 0 else 0.0

            indicators.append({
                "ts_code": ts_code,
                "latest_close": latest_close,
                "ma20": round(float(ma20), 2),
                "ma50": round(float(ma50), 2),
                "ma20_up": bool(pd.notna(ma20_prev) and ma20 > ma20_prev),
                "ma50_up": bool(pd.notna(ma50_prev) and ma50 > ma50_prev),
                "adx": round(float(adx), 2) if pd.notna(adx) else None,
                "rsi": round(float(rsi), 2) if pd.notna(rsi) else None,
                "breakout_hit": breakout_hit,
                "vol_surge_hit": vol_surge_hit,
                "max_vol_ratio": round(float(max_vol_ratio), 2),
                "latest_volume": float(latest_volume),
                "vol_ma_20": float(vol_ma),
                "volume_ratio_val": round(float(vol_ratio), 2),
            })

        if not indicators:
            logger.warning("技术指标计算后无有效股票")
            return pd.DataFrame()

        df = pd.DataFrame(indicators)
        self._stats["indicators_computed"] = len(df)
        logger.info("技术指标计算完成: %d 只", len(df))

        # ════════════════════════════════════════════
        # 条件 T1: MA 多头排列
        #   Close > SMA20 > SMA50，SMA20 向上（SMA50 向上可选）
        # ════════════════════════════════════════════
        mask_t1 = (
            (df["latest_close"] > df["ma20"])
            & (df["ma20"] > df["ma50"])
            & df["ma20_up"]
        )
        if cfg.require_ma50_up:
            mask_t1 = mask_t1 & df["ma50_up"]
        df = df[mask_t1]
        self._stats["T1_ma_alignment"] = len(df)
        ma50_label = "SMA50↑必须" if cfg.require_ma50_up else "SMA50↑可选"
        logger.info("T1 MA多头排列 (Close>SMA20>SMA50, SMA20↑, %s): %d 通过",
                     ma50_label, len(df))

        if df.empty:
            return pd.DataFrame()

        # ════════════════════════════════════════════
        # 条件 T2: ADX 趋势强度
        #   ADX(14) > 25
        # ════════════════════════════════════════════
        mask_t2 = df["adx"].notna() & (df["adx"] > cfg.adx_threshold)
        df = df[mask_t2]
        self._stats["T2_adx_strength"] = len(df)
        logger.info("T2 ADX趋势强度 (>%.0f): %d 通过", cfg.adx_threshold, len(df))

        if df.empty:
            return pd.DataFrame()

        # ════════════════════════════════════════════
        # 条件 T3: 近期高点突破
        #   近 breakout_lookback 天内曾创 breakout_window 日新高
        # ════════════════════════════════════════════
        mask_t3 = df["breakout_hit"]
        df = df[mask_t3]
        self._stats["T3_breakout"] = len(df)
        logger.info("T3 %d日高点突破(近%d天): %d 通过",
                     cfg.breakout_window, cfg.breakout_lookback, len(df))

        if df.empty:
            return pd.DataFrame()

        # ════════════════════════════════════════════
        # 条件 T4: 近期放量确认
        #   近 volume_lookback 天内曾放量 volume_ratio 倍
        # ════════════════════════════════════════════
        mask_t4 = df["vol_surge_hit"]
        df = df[mask_t4]
        self._stats["T4_volume_surge"] = len(df)
        logger.info("T4 放量确认 (近%d天≥%.1fx): %d 通过",
                     cfg.volume_lookback, cfg.volume_ratio, len(df))

        if df.empty:
            return pd.DataFrame()

        # ════════════════════════════════════════════
        # 条件 T5: RSI 动量区间
        #   50 < RSI(14) < 80
        # ════════════════════════════════════════════
        mask_t5 = (
            df["rsi"].notna()
            & (df["rsi"] > cfg.rsi_lower)
            & (df["rsi"] < cfg.rsi_upper)
        )
        df = df[mask_t5]
        self._stats["T5_rsi_momentum"] = len(df)
        logger.info("T5 RSI动量区间 (%.0f<RSI<%.0f): %d 通过",
                     cfg.rsi_lower, cfg.rsi_upper, len(df))

        # ════════════════════════════════════════════
        # 计算趋势综合得分 (trend_score)
        # ════════════════════════════════════════════
        if not df.empty:
            adx_norm = (df["adx"] / 50.0).clip(upper=1.0)
            rsi_norm = ((df["rsi"] - 50.0) / 30.0).clip(lower=0.0, upper=1.0)
            vol_norm = (df["volume_ratio_val"] / 3.0).clip(upper=1.0)

            df = df.copy()
            df["trend_score"] = (
                0.4 * adx_norm + 0.3 * rsi_norm + 0.3 * vol_norm
            ).round(3)

            # 按 trend_score 降序排列
            df = df.sort_values("trend_score", ascending=False)

        self._stats["trend_final"] = len(df)
        logger.info("━━━ 右侧趋势最终通过: %d 只 ━━━", len(df))

        return df
