"""事件级排序信号（Event Ranking Signals）— 纯程序规则，无需额外模型调用。

问题：当前 News「重要」排序只用 根新闻 ai_score + 独立信源加分 + 时间衰减，
没有显式考虑：本轮变化是否重大 / 当前紧迫性 / 是否存在官方确认 /
不确定性有多高 / 用户是否需要行动。导致 Reports 的 LLM 把某事件标为"必须知道"，
News 排序却未必靠前。

解决：每次事件合成（event_synthesizer）时，用既有字段 + 程序规则，算出 5 个
0-10 的事件级信号，并派生一个 0-3 的排序加分 signal_boost 并入现有 HN 重力公式
的 points，使"必须知道"的事件在重要排序里靠前：

  - impact     本轮变化是否重大（重要性）
  - novelty    本轮变化是否新鲜 / 是否仍在演进（新颖度）
  - urgency    当前紧迫性
  - confidence 确定性（含"是否存在官方确认"：多信源交叉验证 / resolved+confirmed）
  - relevance  用户是否需要行动
"""

from __future__ import annotations

# 五个信号在 signal_boost 中的权重（和 = 0.60，配合 OFFSET 3.0：
# 中位事件（信号均=5）→ 0 加分；满分事件（均=10）→ +3.0 封顶）。
# 紧迫性、新颖度权重最高——这是旧排序最缺、又最直接决定"是否该现在看"的维度。
_W_IMPACT = 0.12
_W_NOVELTY = 0.14
_W_URGENCY = 0.16
_W_CONFIDENCE = 0.10
_W_RELEVANCE = 0.08
_SIGNAL_BOOST_OFFSET = 3.0  # 0.6*5=3.0 → 中位(5) 加分归零；0.6*10-3=3.0 封顶
_SIGNAL_BOOST_MAX = 3.0


def _clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def _status_base(status: str) -> dict:
    """状态 → 各信号基准（10 分制）。未知/空状态取 developing 近似。"""
    return {
        "new":        {"novelty": 9, "urgency": 8},
        "developing": {"novelty": 7, "urgency": 9},
        "stable":     {"novelty": 4, "urgency": 4},
        "resolved":   {"novelty": 2, "urgency": 1},
        "":           {"novelty": 6, "urgency": 6},
    }.get(status, {"novelty": 6, "urgency": 6})


def compute_event_signals(
    ai_score: float = 0.0,
    is_highlight: bool = False,
    status: str = "",
    source_count: int = 1,
    uncertainty_text: str = "",
    watch_next_text: str = "",
    has_material_update: bool = False,
    outcome_type: str = "",
) -> dict:
    """由既有字段与程序规则计算 5 个事件级排序信号（每项 0-10）。

    对应合成时已具备的字段，**无需额外 LLM 调用**。
    """
    ai = _clamp(float(ai_score or 0), 0, 10)
    sb = _status_base(status)
    source_count = int(source_count or 1)
    has_uncertainty = bool((uncertainty_text or "").strip())
    has_watch = bool((watch_next_text or "").strip())

    # ── impact：本轮变化是否重大（重要性）──
    impact = ai
    if has_material_update:
        impact += 2.5
    if is_highlight:
        impact += 2.0

    # ── novelty：本轮变化是否新鲜 / 是否仍在演进 ──
    novelty = float(sb["novelty"])
    if has_material_update:
        novelty += 2.0

    # ── urgency：当前紧迫性 ──
    urgency = float(sb["urgency"])
    if has_material_update:
        urgency += 1.5
    if has_watch:
        urgency += 1.5

    # ── confidence：确定性（是否存在官方确认）──
    # 起点 5；明确陈述了不确定性 → 下调；多信源交叉验证 → 上调；
    # 已 resolved（有结论）→ 至少 8；confirmed 结局再 +1。
    confidence = 5.0
    if has_uncertainty:
        confidence -= 3.0
    else:
        confidence += 3.0
    if source_count >= 5:
        confidence += 2.0
    elif source_count >= 3:
        confidence += 1.0
    if status == "resolved":
        confidence = max(confidence, 8.0)
        if outcome_type == "confirmed":
            confidence += 1.0

    # ── relevance：用户是否需要行动 ──
    relevance = 3.0
    if has_watch:
        relevance += 3.0
    if is_highlight:
        relevance += 2.0
    if status in ("new", "developing"):
        relevance += 2.0
    if status == "resolved":
        relevance -= 2.0

    return {
        "impact": int(round(_clamp(impact))),
        "novelty": int(round(_clamp(novelty))),
        "urgency": int(round(_clamp(urgency))),
        "confidence": int(round(_clamp(confidence))),
        "relevance": int(round(_clamp(relevance, 1.0, 10.0))),
    }


def event_signal_boost(
    impact: float = 0,
    novelty: float = 0,
    urgency: float = 0,
    confidence: float = 0,
    relevance: float = 0,
) -> float:
    """由 5 个信号派生排序加分（0 ~ 3.0），并入 HN 重力公式的 points。

    中位事件（信号均=5）→ 0 加分（与旧排序持平，无回归）；
    高信号事件（如"必须知道"）→ 最高 +3.0，足以在重要排序中跃升。
    """
    weighted = (
        _W_IMPACT * float(impact or 0)
        + _W_NOVELTY * float(novelty or 0)
        + _W_URGENCY * float(urgency or 0)
        + _W_CONFIDENCE * float(confidence or 0)
        + _W_RELEVANCE * float(relevance or 0)
    )
    boost = weighted - _SIGNAL_BOOST_OFFSET
    return round(max(0.0, min(_SIGNAL_BOOST_MAX, boost)), 4)


def event_signal_sql() -> str:
    """PostgreSQL 表达式：由 5 个信号列计算 signal_boost（NULL 安全，封顶 3.0）。

    与 event_signal_boost() 语义一致，供 events.py 的 IMPORTANT 排序 ORDER BY 使用。
    """
    col = lambda name: f"COALESCE(event_{name}, 0)"
    weighted = (
        f"{_W_IMPACT} * {col('impact')}"
        f" + {_W_NOVELTY} * {col('novelty')}"
        f" + {_W_URGENCY} * {col('urgency')}"
        f" + {_W_CONFIDENCE} * {col('confidence')}"
        f" + {_W_RELEVANCE} * {col('relevance')}"
    )
    return (
        f"GREATEST(LEAST({weighted} - {_SIGNAL_BOOST_OFFSET}, {_SIGNAL_BOOST_MAX}), 0)"
    )
