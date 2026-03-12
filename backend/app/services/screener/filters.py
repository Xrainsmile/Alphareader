"""Stage2 趋势过滤器 + 基本面过滤器 — Minervini 量化漏斗。

过滤器设计为纯函数式（输入 DataFrame → 输出 DataFrame），
每个过滤步骤独立可测试、可跳过。

数学公式说明：

  ┌────────────────────────────────────────────────────────────┐
  │ Stage2 趋势过滤器 (3 层条件全部满足)                          │
  ├──────────────────────────────────────────────────────────────┤
  │ 条件 A — 趋势与底部确立                                       │
  │   ① EMA20 > EMA50 > EMA120                    (均线多头排列)  │
  │   ② Close ≥ min(Low, 120日) × 1.30            (脱离底部≥30%)  │
  │   ③ Close ≥ max(High, 60日) × 0.85            (逼近前高≤15%) │
  │                                                              │
  │ 条件 B — 筹码支撑 + 箱体突破 + 放量确认                       │
  │   ④ Close > Price_POC(120日)                   (站上筹码峰值) │
  │   ⑤ Close > Quantile(Close, 60日, 0.90)       (箱体突破)      │
  │   ⑥ Volume > MA(Volume, 50日) × 1.5           (放量≥1.5倍)    │
  │                                                              │
  │ 条件 C — 标准化区间振幅收敛 (NRC) + 资金活跃度                │
  │   ⑦ VCP 形态判定 — 三重条件同时满足：                          │
  │     a) Range_10d% ≤ Range_40d% × 0.5          (深度收敛)      │
  │     b) Range_10d% ≤ 8%                         (微观紧凑极限)  │
  │     c) 近5日跌日均量 < 50日均量                 (缩量洗盘)      │
  │   ⑧ 20 日内至少 1 根涨幅≥7% 的大阳线           (主力活跃)      │
  └──────────────────────────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────────┐
  │ 基本面过滤器 (4 层条件)                                       │
  ├──────────────────────────────────────────────────────────────┤
  │ ① 财务防雷（一票否决）：                                       │
  │   - 净利润连续 2 期为负 且 最新营收 < 1 亿 → 剔除              │
  │   - 经营性现金流长期为负 且 净利润极高 → 剔除                   │
  │ ② 营收驱动：最新季度营收同比 > 20%                             │
  │ ③ EPS 环比加速：EPS_Q0 > EPS_Q-1 > EPS_Q-2                   │
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger("alphareader.screener.filters")


# ════════════════════════════════════════════════════════════════
# 辅助计算函数（纯向量化）
# ════════════════════════════════════════════════════════════════

def _compute_vcp_nrc(
    ohlcv: pd.DataFrame,
    latest_close_map: pd.Series,
    long_window: int = 40,
    short_window: int = 10,
    down_vol_window: int = 5,
    avg_vol_window: int = 50,
) -> pd.DataFrame:
    """计算 VCP 标准化区间振幅收敛 (Normalized Range Contraction) 指标。

    三重条件：
      A) 深度收敛：Range_10d% ≤ Range_40d% × vcp_contraction_ratio
      B) 微观紧凑：Range_10d% ≤ max_tightness_threshold
      C) 缩量洗盘：近 5 日下跌日均量 < 50 日均量

    公式：
      Range_Nd% = (Highest_Nd - Lowest_Nd) / Close_latest
      用当前收盘价做标准化，消除股价翻倍对绝对振幅的干扰。

    Args:
        ohlcv: 含 ts_code, trade_date, open, high, low, close, volume 的 DataFrame（已排序）
        latest_close_map: ts_code → 最新收盘价 的 Series（用于标准化）
        long_window: 长期箱体窗口天数（默认 40）
        short_window: 短期箱体窗口天数（默认 10）
        down_vol_window: 缩量洗盘检测窗口（默认 5）
        avg_vol_window: 均量基准窗口（默认 50）

    Returns:
        DataFrame: ts_code, range_long_pct, range_short_pct, down_vol_avg, avg_vol_base
    """
    results = []

    for ts_code, group in ohlcv.groupby("ts_code"):
        # 取最新的数据（已按 trade_date 排序）
        g = group.tail(max(long_window, avg_vol_window))
        if len(g) < short_window:
            continue

        latest_close = latest_close_map.get(ts_code)
        if not latest_close or latest_close <= 0:
            continue

        highs = g["high"].values
        lows = g["low"].values
        closes = g["close"].values
        opens = g["open"].values
        volumes = g["volume"].values

        # ── 长期箱体振幅百分比 (Range_40d%) ──
        if len(g) >= long_window:
            long_h = highs[-long_window:].max()
            long_l = lows[-long_window:].min()
        else:
            long_h = highs.max()
            long_l = lows.min()
        range_long_pct = (long_h - long_l) / latest_close

        # ── 短期箱体振幅百分比 (Range_10d%) ──
        short_h = highs[-short_window:].max()
        short_l = lows[-short_window:].min()
        range_short_pct = (short_h - short_l) / latest_close

        # ── 近 N 日下跌日均量 & 50 日均量 ──
        recent_closes = closes[-down_vol_window:]
        recent_opens = opens[-down_vol_window:]
        recent_volumes = volumes[-down_vol_window:]

        down_mask = recent_closes < recent_opens
        if down_mask.any():
            down_vol_avg = recent_volumes[down_mask].mean()
        else:
            # 无下跌日 → 说明极强势，给一个极小值以确保条件通过
            down_vol_avg = 0.0

        if len(volumes) >= avg_vol_window:
            avg_vol_base = volumes[-avg_vol_window:].mean()
        else:
            avg_vol_base = volumes.mean()

        results.append({
            "ts_code": ts_code,
            "range_long_pct": range_long_pct,
            "range_short_pct": range_short_pct,
            "down_vol_avg": down_vol_avg,
            "avg_vol_base": avg_vol_base,
        })

    if not results:
        return pd.DataFrame(columns=["ts_code", "range_long_pct", "range_short_pct", "down_vol_avg", "avg_vol_base"])

    return pd.DataFrame(results)


def _compute_poc(ohlcv: pd.DataFrame, window: int = 120) -> pd.DataFrame:
    """计算筹码峰值价格 Price_POC（Point of Control）。

    POC = 过去 window 个交易日中，按价格分桶后成交量最大的桶中位价。

    采用向量化逐股计算（groupby apply），每只股票取最近 window 天的数据，
    按价格等分 20 个桶，找到成交量最大的桶，取该桶的中位价。

    Args:
        ohlcv: 含 ts_code, close, volume 的 DataFrame
        window: 回溯交易日数

    Returns:
        DataFrame: ts_code, price_poc
    """
    def _stock_poc(group: pd.DataFrame) -> float:
        """单只股票的 POC 计算。"""
        recent = group.tail(window)
        if len(recent) < 20:
            return np.nan

        closes = recent["close"].values
        volumes = recent["volume"].values

        # 将价格区间等分为 20 个桶
        price_min, price_max = closes.min(), closes.max()
        if price_max <= price_min:
            return price_min

        n_bins = 20
        bins = np.linspace(price_min, price_max, n_bins + 1)
        bin_indices = np.digitize(closes, bins) - 1
        bin_indices = np.clip(bin_indices, 0, n_bins - 1)

        # 每个桶的成交量之和
        bin_volumes = np.zeros(n_bins)
        for i in range(len(closes)):
            bin_volumes[bin_indices[i]] += volumes[i]

        # POC = 成交量最大桶的中位价
        max_bin = np.argmax(bin_volumes)
        poc = (bins[max_bin] + bins[max_bin + 1]) / 2
        return poc

    poc_series = ohlcv.groupby("ts_code").apply(_stock_poc, include_groups=False)
    return poc_series.reset_index().rename(columns={0: "price_poc"})


def _compute_quantile_close(ohlcv: pd.DataFrame, window: int = 60, q: float = 0.90) -> pd.DataFrame:
    """计算过去 window 日收盘价的 q 分位数。

    Args:
        ohlcv: 含 ts_code, close 的 DataFrame
        window: 窗口天数
        q: 分位数

    Returns:
        DataFrame: ts_code, quantile_close
    """
    def _quantile(group: pd.DataFrame) -> float:
        recent = group.tail(window)
        if len(recent) < 10:
            return np.nan
        return recent["close"].quantile(q)

    result = ohlcv.groupby("ts_code").apply(_quantile, include_groups=False)
    return result.reset_index().rename(columns={0: "quantile_close_90"})


def _check_big_yang_line(ohlcv: pd.DataFrame, window: int = 20, threshold: float = 7.0) -> pd.DataFrame:
    """检测过去 window 天内是否出现过涨幅 ≥ threshold% 的大阳线。

    Args:
        ohlcv: 含 ts_code, pct_change 的 DataFrame
        window: 窗口天数
        threshold: 涨幅阈值（%）

    Returns:
        DataFrame: ts_code, has_big_yang (bool)
    """
    def _check(group: pd.DataFrame) -> bool:
        recent = group.tail(window)
        if recent.empty:
            return False
        return (recent["pct_change"] >= threshold).any()

    result = ohlcv.groupby("ts_code").apply(_check, include_groups=False)
    return result.reset_index().rename(columns={0: "has_big_yang"})


# ════════════════════════════════════════════════════════════════
# Stage2 趋势过滤器
# ════════════════════════════════════════════════════════════════

@dataclass
class Stage2FilterConfig:
    """Stage2 过滤器的可调参数。"""

    # 条件 A: 趋势与底部确立
    ema_trend_check: bool = True            # EMA20 > EMA50 > EMA120
    bottom_rebound_pct: float = 1.30        # 脱离底部：Close >= min(Low, 120) * 1.30
    near_high_pct: float = 0.85             # 逼近前高：Close >= max(High, 60) * 0.85

    # 条件 B: 筹码支撑 + 箱体突破 + 放量
    volume_ratio: float = 1.5               # 放量倍数：Volume > MA(Vol, 50) * 1.5
    quantile_close_q: float = 0.90          # 箱体突破分位数
    quantile_close_window: int = 60         # 箱体窗口（交易日）

    # 条件 C: 标准化区间振幅收敛 (NRC) + 资金活跃度
    vcp_contraction_ratio: float = 0.6      # 深度收敛：Range_10d% ≤ Range_40d% × ratio
    max_tightness_threshold: float = 0.15   # 微观紧凑极限：Range_10d% ≤ 15%
    big_yang_threshold: float = 5.0         # 大阳线涨幅阈值（%）
    big_yang_window: int = 20               # 大阳线检测窗口


class MinerviniScreener:
    """Minervini Stage2 趋势过滤器 — 技术面量化漏斗。

    输入：全市场 OHLCV + EMA 数据
    输出：通过所有技术条件的股票列表
    """

    def __init__(self, config: Stage2FilterConfig | None = None):
        self.config = config or Stage2FilterConfig()
        self._stats: dict[str, int] = {}

    @property
    def filter_stats(self) -> dict[str, int]:
        """返回每个过滤步骤的通过/淘汰数量。"""
        return self._stats

    def apply(
        self,
        ohlcv: pd.DataFrame,
        ema: pd.DataFrame,
        extremes: pd.DataFrame,
    ) -> pd.DataFrame:
        """执行完整的 Stage2 趋势过滤管道。

        Args:
            ohlcv: 全市场近 130 天 OHLCV 数据（ts_code, trade_date, ...）
            ema: 最新 EMA 快照（Code, EMA20, EMA50, EMA120, ...）
            extremes: 价格极值统计（ts_code, min_low_120, max_high_60, avg_vol_50, latest_volume, latest_close）

        Returns:
            通过所有条件的股票 DataFrame
        """
        cfg = self.config
        self._stats = {}

        # ── 准备 EMA 数据 ──
        ema_df = ema.rename(columns={"Code": "ts_code"}).copy()
        total_start = len(ema_df)
        self._stats["total_input"] = total_start

        # ============================================================
        # 条件 A: 趋势与底部确立
        # ============================================================

        # A1: EMA20 > EMA50 > EMA120（均线多头排列）
        if cfg.ema_trend_check:
            mask_a1 = (ema_df["EMA20"] > ema_df["EMA50"]) & (ema_df["EMA50"] > ema_df["EMA120"])
            passed_a1 = ema_df.loc[mask_a1, "ts_code"].values
            self._stats["A1_ema_trend"] = len(passed_a1)
            logger.info("A1 均线多头排列 (EMA20>EMA50>EMA120): %d/%d 通过", len(passed_a1), total_start)
        else:
            passed_a1 = ema_df["ts_code"].values

        # 合并 EMA 与 extremes 进行后续过滤
        merged = ema_df[ema_df["ts_code"].isin(passed_a1)].merge(
            extremes, on="ts_code", how="inner"
        )

        # A2: 脱离底部 — Close >= min(Low, 120日) × 1.30
        mask_a2 = merged["latest_close"] >= merged["min_low_120"] * cfg.bottom_rebound_pct
        merged = merged[mask_a2]
        self._stats["A2_bottom_rebound"] = len(merged)
        logger.info("A2 脱离底部 (≥30%%反弹): %d 通过", len(merged))

        # A3: 逼近前高 — Close >= max(High, 60日) × 0.85
        mask_a3 = merged["latest_close"] >= merged["max_high_60"] * cfg.near_high_pct
        merged = merged[mask_a3]
        self._stats["A3_near_high"] = len(merged)
        logger.info("A3 逼近前高 (≤15%%差距): %d 通过", len(merged))

        if merged.empty:
            logger.warning("Stage2 条件 A 已过滤完所有股票")
            return pd.DataFrame()

        # ============================================================
        # 条件 B: 筹码支撑 + 箱体突破 + 放量确认
        # ============================================================

        candidates = set(merged["ts_code"].values)
        ohlcv_subset = ohlcv[ohlcv["ts_code"].isin(candidates)].copy()

        # B1: 筹码支撑 — Close > Price_POC(120日)
        poc_df = _compute_poc(ohlcv_subset, window=120)
        merged = merged.merge(poc_df, on="ts_code", how="left")
        mask_b1 = merged["latest_close"] > merged["price_poc"]
        merged = merged[mask_b1 | merged["price_poc"].isna()]  # NaN 时不淘汰
        self._stats["B1_above_poc"] = len(merged)
        logger.info("B1 站上筹码峰值 (POC): %d 通过", len(merged))

        # B2: 箱体突破 — Close > Quantile(Close, 60日, 0.90)
        q_df = _compute_quantile_close(ohlcv_subset, window=cfg.quantile_close_window, q=cfg.quantile_close_q)
        merged = merged.merge(q_df, on="ts_code", how="left")
        mask_b2 = merged["latest_close"] > merged["quantile_close_90"]
        merged = merged[mask_b2 | merged["quantile_close_90"].isna()]
        self._stats["B2_breakout"] = len(merged)
        logger.info("B2 箱体突破 (90%%分位): %d 通过", len(merged))

        # B3: 放量确认 — Volume > MA(Volume, 50日) × 1.5
        mask_b3 = merged["latest_volume"] > merged["avg_vol_50"] * cfg.volume_ratio
        merged = merged[mask_b3 | merged["avg_vol_50"].isna()]
        self._stats["B3_volume_surge"] = len(merged)
        logger.info("B3 放量确认 (≥1.5x): %d 通过", len(merged))

        if merged.empty:
            logger.warning("Stage2 条件 B 已过滤完所有股票")
            return pd.DataFrame()

        # ============================================================
        # 条件 C: 形态收敛与资金活跃度
        # ============================================================

        candidates = set(merged["ts_code"].values)
        ohlcv_subset2 = ohlcv[ohlcv["ts_code"].isin(candidates)].copy()

        # C1: VCP 标准化区间振幅收敛 (NRC) — 三重条件
        #   a) Range_10d% ≤ Range_40d% × vcp_contraction_ratio  (深度收敛)
        #   b) Range_10d% ≤ max_tightness_threshold              (微观紧凑极限)
        #   c) 近5日下跌日均量 < 50日均量                          (缩量洗盘)
        latest_close_map = merged.set_index("ts_code")["latest_close"]
        nrc_df = _compute_vcp_nrc(ohlcv_subset2, latest_close_map)

        merged = merged.merge(nrc_df, on="ts_code", how="left")

        # 条件 a: 深度收敛
        mask_c1a = merged["range_short_pct"] <= merged["range_long_pct"] * cfg.vcp_contraction_ratio
        # 条件 b: 微观紧凑极限
        mask_c1b = merged["range_short_pct"] <= cfg.max_tightness_threshold
        # 条件 c: 缩量洗盘（下跌日均量 < 50日均量）
        mask_c1c = merged["down_vol_avg"] < merged["avg_vol_base"]

        # NaN 时不淘汰
        has_nrc = merged["range_short_pct"].notna()
        mask_c1 = (mask_c1a & mask_c1b & mask_c1c) | ~has_nrc

        merged = merged[mask_c1]
        self._stats["C1_vcp_contraction"] = len(merged)
        logger.info(
            "C1 VCP-NRC 收敛 (Range10d%%≤Range40d%%*%.2f & ≤%.0f%% & 缩量): %d 通过",
            cfg.vcp_contraction_ratio, cfg.max_tightness_threshold * 100, len(merged),
        )

        # C2: 活跃基因 — 20 日内至少 1 根涨幅≥7% 的大阳线
        yang_df = _check_big_yang_line(
            ohlcv_subset2, window=cfg.big_yang_window, threshold=cfg.big_yang_threshold,
        )
        merged = merged.merge(yang_df, on="ts_code", how="left")
        mask_c2 = merged["has_big_yang"] == True  # noqa: E712
        merged = merged[mask_c2 | merged["has_big_yang"].isna()]
        self._stats["C2_big_yang"] = len(merged)
        logger.info("C2 大阳线活跃 (%d日内≥%.0f%%): %d 通过", cfg.big_yang_window, cfg.big_yang_threshold, len(merged))

        self._stats["stage2_final"] = len(merged)
        logger.info("━━━ Stage2 最终通过: %d 只 ━━━", len(merged))

        return merged


# ════════════════════════════════════════════════════════════════
# 基本面过滤器
# ════════════════════════════════════════════════════════════════

@dataclass
class FundamentalFilterConfig:
    """基本面过滤器的可调参数。"""

    # 财务防雷
    min_revenue_for_loss: float = 1e8       # 净利润连亏时最低营收（1 亿元）
    cashflow_fraud_threshold: float = -0.5  # 经营现金流/净利润比值下限

    # 营收驱动
    min_revenue_yoy: float = 20.0           # 最新季度营收同比增长下限（%）

    # EPS 环比加速
    eps_acceleration: bool = True           # 是否启用 EPS 环比加速检查


class FundamentalFilter:
    """基本面防雷与拐点捕捉过滤器。

    输入：全市场季度业绩报告
    输出：通过基本面筛选的股票代码集合
    """

    def __init__(self, config: FundamentalFilterConfig | None = None):
        self.config = config or FundamentalFilterConfig()
        self._stats: dict[str, int] = {}

    @property
    def filter_stats(self) -> dict[str, int]:
        return self._stats

    def apply(self, fundamental_df: pd.DataFrame, candidate_codes: set[str]) -> set[str]:
        """执行基本面过滤。

        Args:
            fundamental_df: 合并后的多季度业绩数据
            candidate_codes: 技术面筛选后的股票代码集合

        Returns:
            通过基本面筛选的股票代码集合
        """
        cfg = self.config
        self._stats = {}

        if fundamental_df.empty:
            logger.warning("基本面数据为空，跳过基本面过滤，全部放行")
            self._stats["skipped"] = True
            return candidate_codes

        # 只看候选池中的股票
        fdf = fundamental_df[fundamental_df["股票代码"].isin(candidate_codes)].copy()
        self._stats["fundamental_input"] = len(candidate_codes)

        # 确保数值列类型正确
        for col in ["eps", "revenue", "revenue_yoy", "net_profit", "net_profit_yoy", "cashflow_per_share"]:
            if col in fdf.columns:
                fdf[col] = pd.to_numeric(fdf[col], errors="coerce")

        # ── 按股票代码分组，按报告期排序 ──
        fdf = fdf.sort_values(["股票代码", "report_date"], ascending=[True, False])

        passed = set()
        failed_reasons: dict[str, str] = {}

        for code in candidate_codes:
            stock_data = fdf[fdf["股票代码"] == code]

            if stock_data.empty:
                # 无基本面数据的股票不一票否决，但降权记录
                logger.debug("基本面数据缺失: %s，放行但标记", code)
                passed.add(code)
                continue

            try:
                ok, reason = self._check_single_stock(stock_data, code)
                if ok:
                    passed.add(code)
                else:
                    failed_reasons[code] = reason
            except Exception as e:
                # 单只股票分析失败不崩溃
                logger.warning("基本面分析异常 %s: %s，放行", code, e)
                passed.add(code)

        self._stats["F1_anti_fraud"] = len(candidate_codes) - len(failed_reasons)
        self._stats["fundamental_passed"] = len(passed)
        self._stats["fundamental_failed"] = len(failed_reasons)

        if failed_reasons:
            logger.info("基本面淘汰 %d 只: %s",
                        len(failed_reasons),
                        list(failed_reasons.items())[:10])

        logger.info("━━━ 基本面最终通过: %d/%d ━━━", len(passed), len(candidate_codes))
        return passed

    def _check_single_stock(self, data: pd.DataFrame, code: str) -> tuple[bool, str]:
        """对单只股票执行基本面检查。

        Returns:
            (通过, 失败原因)
        """
        cfg = self.config
        rows = data.head(3)  # 最近 3 个季度（已按日期降序）

        q0 = rows.iloc[0] if len(rows) >= 1 else None  # 最新季度
        q1 = rows.iloc[1] if len(rows) >= 2 else None  # 上一季度
        q2 = rows.iloc[2] if len(rows) >= 3 else None  # 再上一季度

        # ── 防雷1: 净利润连续两期为负 且 营收 < 1 亿 ──
        if q0 is not None and q1 is not None:
            np0 = q0.get("net_profit")
            np1 = q1.get("net_profit")
            rev0 = q0.get("revenue")

            if (pd.notna(np0) and pd.notna(np1) and pd.notna(rev0)
                    and np0 < 0 and np1 < 0 and rev0 < cfg.min_revenue_for_loss):
                return False, "连续两期净利润为负且营收<1亿"

        # ── 防雷2: 经营现金流长期为负 但 净利润很高（造假疑似）──
        if q0 is not None:
            cf = q0.get("cashflow_per_share")
            eps = q0.get("eps")
            if (pd.notna(cf) and pd.notna(eps) and eps > 0 and cf < 0
                    and cf / max(eps, 0.01) < cfg.cashflow_fraud_threshold):
                return False, "经营现金流为负但EPS很高(疑似造假)"

        # ── 营收驱动: 最新季度营收同比 > 20% ──
        if q0 is not None:
            rev_yoy = q0.get("revenue_yoy")
            if pd.notna(rev_yoy) and rev_yoy < cfg.min_revenue_yoy:
                return False, f"营收同比增长{rev_yoy:.1f}%<{cfg.min_revenue_yoy}%"

        # ── EPS 环比加速: EPS_Q0 > EPS_Q-1 > EPS_Q-2 ──
        if cfg.eps_acceleration and q0 is not None and q1 is not None and q2 is not None:
            eps0 = q0.get("eps")
            eps1 = q1.get("eps")
            eps2 = q2.get("eps")
            if pd.notna(eps0) and pd.notna(eps1) and pd.notna(eps2):
                if not (eps0 > eps1 > eps2):
                    return False, f"EPS未加速({eps0:.3f}<={eps1:.3f}<={eps2:.3f})"

        return True, ""
