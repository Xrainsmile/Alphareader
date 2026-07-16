"""VCP（Volatility Contraction Pattern）自动识别算法。

纯 OHLCV 数据驱动，不依赖任何模型 / 图像，可回测、可解释、可复现。

算法流程：
  1. 取标的近 N 日（默认 90，覆盖约 80 个交易日）OHLCV
  2. ZigZag 检测显著转折点（滤掉 < 阈值的噪音波动）
  3. 以窗口内最高 swing high 为「枢轴」（基底左峰）
  4. 从枢轴往右，把相邻 (高→低) 配对成「收缩段」
  5. 五项硬指标判定 VCP 是否成立：
       - 收缩次数 ∈ [MIN, MAX]
       - 各次收缩振幅逐次递减（允许 1 次例外）
       - 末段振幅 ≤ LAST_AMP_MAX（收缩充分）
       - 量能逐段递减（允许 1 次例外）
       - 后续高点逐次降低（lower highs，允许 1 次例外）

阈值初值「宽松」（用户决策：先宽松跑回测，再据结果收紧）。
严格值已注释在常量旁，回测校准后切换。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("alphareader.vcp_detector")

# ───────────────────────────────────────────────────────────
# 可调阈值（初值"宽松"；严格值见注释，回测后切换）
# ───────────────────────────────────────────────────────────
ZIGZAG_THRESHOLD = 0.02   # 2%（严格 3%）：转折点最小反向波动才确认
MIN_CONTRACTIONS = 2      # 最少收缩次数（标准 VCP 2~4）
MAX_CONTRACTIONS = 5      # 宽松允许 5 次（严格 4）
AMP_DECAY_RATIO = 0.90    # 每段振幅 ≤ 上段 90%（严格 0.85）
LAST_AMP_MAX = 0.08       # 末段振幅 ≤ 8%（严格 5%）：收缩充分
HIGH_TOL = 0.02           # 后续高点允许比前高高出 ≤2%（严格 0）：lower highs
VOL_DECAY_RATIO = 0.95    # 量能 ≤ 上段 95%（严格 0.95）：量能萎缩
NEAR_PIVOT_PCT = 0.05     # 距枢轴 ±5% 视为买点区间
LOOKBACK_DAYS = 90        # 分析窗口（约 80 个交易日 + 缓冲）
MIN_BARS = 40             # 最少 K 线数（低于此直接判数据不足）
ALLOW_EXCEPTIONS = 1      # 振幅/量能/高点 各自允许违反次数


def _zigzag(prices: list[float], threshold: float) -> list[tuple[int, float, str]]:
    """标准 ZigZag 转折点检测。

    Args:
        prices: 收盘价序列（oldest→newest）
        threshold: 反向波动超过该比例才确认一个转折点
    Returns:
        转折点列表 [(index, price, type), ...]，type ∈ {'H','L'}，按时间升序、基本交替。
        注意：记录的 price 是传入的 prices 值（收盘价）。调用方应传入
        对高点用 high、对低点用 low，见 detect_vcp 中的 post-process。
    """
    n = len(prices)
    if n < 2:
        return []

    pivots: list[tuple[int, float, str]] = []
    trend = 0  # 1=上行跟踪中, -1=下行跟踪中, 0=未定
    extreme_idx = 0
    extreme_val = prices[0]

    for i in range(1, n):
        p = prices[i]
        if trend >= 0:
            # 当前在跟踪高点（或方向未定）
            if p > extreme_val:
                extreme_val = p
                extreme_idx = i
            elif (extreme_val - p) / extreme_val >= threshold:
                # 从极值回落超阈值 → 确认一个 swing HIGH
                pivots.append((extreme_idx, extreme_val, "H"))
                trend = -1
                extreme_val = p
                extreme_idx = i
        if trend <= 0:
            # 当前在跟踪低点
            if p < extreme_val:
                extreme_val = p
                extreme_idx = i
            elif (p - extreme_val) / extreme_val >= threshold:
                # 从极值反弹超阈值 → 确认一个 swing LOW
                pivots.append((extreme_idx, extreme_val, "L"))
                trend = 1
                extreme_val = p
                extreme_idx = i

    # 收尾：把最后仍在跟踪的极值作为最后一个转折点
    if pivots:
        if pivots[-1][0] != extreme_idx:
            final_type = "L" if trend < 0 else "H"
            pivots.append((extreme_idx, extreme_val, final_type))
    else:
        # 全程无一次超阈值反向 → 仅有一个转折点（起点极值）
        pivots.append((0, prices[0], "H" if prices[-1] >= prices[0] else "L"))

    return pivots


def _monotonic_decreasing(seq: list[float], ratio: float, allow: int) -> bool:
    """判断 seq 是否整体递减（每段 ≤ 前段 * ratio），允许 allow 次例外。"""
    violations = 0
    for i in range(len(seq) - 1):
        if seq[i + 1] > seq[i] * ratio:
            violations += 1
    return violations <= allow


def detect_vcp(
    bars: list[dict],
    *,
    params: dict | None = None,
    pivot_override: float | None = None,
) -> dict:
    """识别 VCP 形态。

    Args:
        bars: K 线列表，按时间升序（oldest→newest），每根含
              {date:str, open, high, low, close, volume}
        params: 可选，覆盖默认阈值（用于回测敏感性分析）
        pivot_override: 可选，用户/系统指定的枢轴价，仅用于 near_pivot 计算与展示
    Returns:
        可直接 JSON 序列化的 dict，含 vcp_detected / contractions / amplitudes /
        vol_decays / decay_ok / vol_decay_ok / high_ok / near_pivot / pivot_price /
        pivot_suggested / reason / swing_points / segments / data_points
    """
    p = {
        "zigzag": ZIGZAG_THRESHOLD,
        "min_c": MIN_CONTRACTIONS,
        "max_c": MAX_CONTRACTIONS,
        "amp_decay": AMP_DECAY_RATIO,
        "last_amp": LAST_AMP_MAX,
        "high_tol": HIGH_TOL,
        "vol_decay": VOL_DECAY_RATIO,
        "near_pivot": NEAR_PIVOT_PCT,
        "min_bars": MIN_BARS,
        "allow_exc": ALLOW_EXCEPTIONS,
    }
    if params:
        p.update(params)

    result: dict = {
        "vcp_detected": False,
        "contractions": 0,
        "amplitudes": [],
        "vol_decays": [],
        "decay_ok": False,
        "vol_decay_ok": False,
        "high_ok": False,
        "near_pivot": None,
        "pivot_price": pivot_override,
        "pivot_suggested": None,
        "buy_zone": False,
        "reason": "",
        "variant": "standard",
        "data_points": len(bars),
        "swing_points": [],
        "segments": [],
    }

    if not bars or len(bars) < p["min_bars"]:
        result["reason"] = f"数据不足（需≥{p['min_bars']}根K线，现有{len(bars) if bars else 0}根）"
        return result

    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    vols = [float(b.get("volume") or 0) for b in bars]
    dates = [str(b["date"]) for b in bars]

    # 1) ZigZag 转折点（先按收盘价找转向，再回填真实 high/low）
    raw = _zigzag(closes, p["zigzag"])
    pivots: list[tuple[int, float, str]] = []
    for idx, _px, typ in raw:
        price = highs[idx] if typ == "H" else lows[idx]
        pivots.append((idx, price, typ))

    # 前端标注用
    result["swing_points"] = [
        {"date": dates[idx], "price": round(price, 4), "type": typ}
        for idx, price, typ in pivots
    ]

    # 2) 找枢轴 = 窗口内最高 swing high
    high_positions = [k for k, (_i, _v, t) in enumerate(pivots) if t == "H"]
    if not high_positions:
        result["reason"] = "未检测到显著 swing high"
        return result
    max_k = max(high_positions, key=lambda k: pivots[k][1])
    pivot_idx, pivot_price = pivots[max_k][0], pivots[max_k][1]
    result["pivot_suggested"] = round(pivot_price, 4)

    # 3) 从枢轴往右配对收缩段 (H → L → 下一个 H 为一段)
    base = pivots[max_k:]
    contractions: list[dict] = []
    i = 0
    while i + 2 < len(base):
        h0, l0, h1 = base[i], base[i + 1], base[i + 2]
        if not (h0[2] == "H" and l0[2] == "L" and h1[2] == "H"):
            break
        hi_price, lo_price = h0[1], l0[1]
        amp = (hi_price - lo_price) / hi_price if hi_price else 0.0
        seg_vols = vols[h0[0]: l0[0] + 1]
        seg_vols = [v for v in seg_vols if v and v > 0]
        avg_vol = sum(seg_vols) / len(seg_vols) if seg_vols else 0.0
        contractions.append({
            "high": round(hi_price, 4),
            "low": round(lo_price, 4),
            "amplitude": round(amp, 4),
            "amplitude_pct": round(amp * 100, 2),
            "avg_volume": round(avg_vol, 2),
            "start_idx": h0[0],
            "end_idx": l0[0],
            "start_date": dates[h0[0]],
            "end_date": dates[l0[0]],
        })
        i += 2

    n = len(contractions)
    result["contractions"] = n
    result["segments"] = contractions
    result["amplitudes"] = [round(c["amplitude"], 4) for c in contractions]
    amps = [c["amplitude"] for c in contractions]
    vols_seq = [c["avg_volume"] for c in contractions]

    # 4) 量能相对前段的比值
    if vols_seq:
        result["vol_decays"] = [
            round(vols_seq[k + 1] / vols_seq[k], 3) if vols_seq[k] else 1.0
            for k in range(len(vols_seq) - 1)
        ]

    # ── 五项硬指标 ──
    reasons: list[str] = []

    if n < p["min_c"] or n > p["max_c"]:
        reasons.append(f"收缩次数{n}不在[{p['min_c']},{p['max_c']}]")
    decay_ok = _monotonic_decreasing(amps, p["amp_decay"], p["allow_exc"]) if n >= 2 else False
    result["decay_ok"] = decay_ok
    if n >= 2 and not decay_ok:
        reasons.append("振幅未逐次递减（波动率未收缩）")

    # 高点序列：经典 VCP 多为 lower highs，但末次回升常逼近枢轴而略高于前高，
    # 故「高点递减」仅作信息参考，不作为硬性门槛（核心是振幅/量能递减）。
    high_seq = [base[k][1] for k in range(0, len(base) - 1, 2) if base[k][2] == "H"]
    high_ok = _monotonic_decreasing(high_seq, 1 + p["high_tol"], p["allow_exc"]) if len(high_seq) >= 2 else False
    result["high_ok"] = high_ok

    last_amp_ok = amps[-1] <= p["last_amp"] if amps else False
    if amps and not last_amp_ok:
        reasons.append(f"末段振幅{amps[-1]*100:.1f}% > {p['last_amp']*100:.0f}%")

    vol_decay_ok = _monotonic_decreasing(vols_seq, p["vol_decay"], p["allow_exc"]) if len(vols_seq) >= 2 else False
    result["vol_decay_ok"] = vol_decay_ok
    if len(vols_seq) >= 2 and not vol_decay_ok:
        reasons.append("量能未逐段递减")

    # near_pivot：相对枢轴（用户覆盖优先，否则算法建议）
    ref_pivot = pivot_override if pivot_override else pivot_price
    last_close = closes[-1]
    if ref_pivot:
        dist = (last_close - ref_pivot) / ref_pivot
        result["near_pivot"] = abs(dist) <= p["near_pivot"]
        result["pivot_distance_pct"] = round(dist * 100, 2)
        result["buy_zone"] = result["near_pivot"]

    # 末段振幅偏大但其余都通过 → 记为变体（人工复核），不致命
    structural_ok = (
        p["min_c"] <= n <= p["max_c"]
        and decay_ok and vol_decay_ok
    )
    if structural_ok and not last_amp_ok:
        result["variant"] = "wide_final"
        result["vcp_detected"] = True
        result["reason"] = "结构成立但末段振幅偏大，建议人工复核"
    elif structural_ok:
        result["vcp_detected"] = True
        result["reason"] = "VCP 结构成立"
    else:
        result["reason"] = "；".join(reasons) if reasons else "不符合 VCP"

    return result
