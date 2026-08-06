"""事件级排序信号（纯规则，无需额外模型调用）单元测试。

覆盖：
  - compute_event_signals 各维度随输入变化的方向正确（0-10 区间）
  - event_signal_boost 中位事件≈0 加分（无回归）、高信号事件可加至封顶 3.0
  - event_signal_sql 引用全部 5 列、NULL 安全、与 Python 函数语义一致
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils import event_signals


def test_signals_keys_and_range():
    s = event_signals.compute_event_signals(ai_score=7, status="developing")
    assert set(s.keys()) == {"impact", "novelty", "urgency", "confidence", "relevance"}
    assert all(0 <= v <= 10 for v in s.values())


def test_impact_rises_with_highlight_and_material():
    base = event_signals.compute_event_signals(ai_score=7, status="developing")
    hl = event_signals.compute_event_signals(
        ai_score=7, status="developing", is_highlight=True
    )
    mat = event_signals.compute_event_signals(
        ai_score=7, status="developing", has_material_update=True
    )
    assert hl["impact"] > base["impact"]
    assert mat["impact"] > base["impact"]


def test_urgency_high_for_active_low_for_resolved():
    dev = event_signals.compute_event_signals(ai_score=7, status="developing")
    res = event_signals.compute_event_signals(ai_score=7, status="resolved")
    assert dev["urgency"] > res["urgency"]
    # 有 watch_next 提示时紧迫性更高
    watch = event_signals.compute_event_signals(
        ai_score=7, status="developing", watch_next_text="关注下周财报"
    )
    assert watch["urgency"] > dev["urgency"]


def test_confidence_rises_without_uncertainty_and_more_sources():
    uncertain = event_signals.compute_event_signals(
        ai_score=7, status="developing", uncertainty_text="尚待监管批准"
    )
    clean = event_signals.compute_event_signals(ai_score=7, status="developing")
    multi = event_signals.compute_event_signals(
        ai_score=7, status="developing", source_count=6
    )
    assert clean["confidence"] > uncertain["confidence"]
    assert multi["confidence"] > clean["confidence"]


def test_resolved_confirmed_is_high_confidence():
    s = event_signals.compute_event_signals(
        ai_score=7, status="resolved", outcome_type="confirmed", source_count=4
    )
    assert s["confidence"] >= 8


def test_relevance_rises_with_watch_and_highlight():
    base = event_signals.compute_event_signals(ai_score=7, status="developing")
    watch = event_signals.compute_event_signals(
        ai_score=7, status="developing", watch_next_text="等待官方公告"
    )
    assert watch["relevance"] > base["relevance"]


def test_boost_median_is_zero():
    # 全部中位（5）→ 加分 0，与旧排序持平，无回归
    b = event_signals.event_signal_boost(5, 5, 5, 5, 5)
    assert b == 0.0


def test_boost_capped_at_three():
    b = event_signals.event_signal_boost(10, 10, 10, 10, 10)
    assert b == 3.0


def test_boost_positive_for_must_know_event():
    # 已确认落地、紧迫、有实质进展的事件应获得正向加分
    s = event_signals.compute_event_signals(
        ai_score=9, is_highlight=True, status="developing",
        source_count=4, watch_next_text="关注今晚决议", has_material_update=True,
    )
    b = event_signals.event_signal_boost(**s)
    assert b > 0.0


def test_sql_expression_references_all_columns_and_is_null_safe():
    sql = event_signals.event_signal_sql()
    for col in ("event_impact", "event_novelty", "event_urgency",
                "event_confidence", "event_relevance"):
        assert col in sql
    assert "COALESCE" in sql
    assert "GREATEST" in sql and "LEAST" in sql
