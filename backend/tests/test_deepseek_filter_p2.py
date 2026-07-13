"""P2 ③：is_highlight 两层筛选自测。

覆盖点：
- 模型返回 is_highlight=true 且 score>=8 → 落到 ScoredNewsItem
- 模型返回 is_highlight=true 但 score<8 → 硬降级为 false
- 模型未返回 is_highlight 字段 → 默认 false
- 字符串 "true"/"false" 兼容
- 非 bool 且非合法字符串 → 默认 false
"""
from __future__ import annotations

import json

import pytest

from app.services.deepseek_filter import (
    RawNewsItem,
    ScoredNewsItem,
    _parse_response_detailed,
)


def _make_batch(n: int, is_english: bool = False) -> list[RawNewsItem]:
    items = []
    for i in range(n):
        if is_english:
            items.append(RawNewsItem(
                title=f"Test News {i+1}",
                content="This is content for news " + str(i + 1),
                url=f"https://example.com/en/{i+1}",
                source="Reuters",
            ))
        else:
            items.append(RawNewsItem(
                title=f"测试新闻{i+1}",
                content=f"这是第{i+1}条正文",
                url=f"https://example.com/cn/{i+1}",
                source="财联社",
            ))
    return items


class TestIsHighlightParsing:
    """中文分支的 is_highlight 提取。"""

    def test_true_with_high_score(self):
        raw = json.dumps([
            {"id": 1, "score": 8, "is_highlight": True,
             "reason": "强催化", "tags": [], "relevant_tickers": []}
        ], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(raw, _make_batch(1), False)
        assert ok
        assert len(scored) == 1
        assert scored[0].is_highlight is True
        assert scored[0].score == 8

    def test_true_downgraded_when_score_low(self):
        """is_highlight=true 但 score<8 → 强制降级为 false。"""
        raw = json.dumps([
            {"id": 1, "score": 6, "is_highlight": True,
             "reason": "有数据", "tags": [], "relevant_tickers": []}
        ], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(raw, _make_batch(1), False)
        assert ok and len(scored) == 1
        assert scored[0].is_highlight is False
        assert scored[0].score == 6

    def test_missing_defaults_to_false(self):
        raw = json.dumps([
            {"id": 1, "score": 8,
             "reason": "无 is_highlight 字段", "tags": [], "relevant_tickers": []}
        ], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(raw, _make_batch(1), False)
        assert ok and len(scored) == 1
        assert scored[0].is_highlight is False

    def test_string_true_accepted(self):
        raw = json.dumps([
            {"id": 1, "score": 8, "is_highlight": "true",
             "reason": "", "tags": [], "relevant_tickers": []}
        ], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(raw, _make_batch(1), False)
        assert ok
        assert scored[0].is_highlight is True

    def test_string_false_rejected(self):
        raw = json.dumps([
            {"id": 1, "score": 8, "is_highlight": "false",
             "reason": "", "tags": [], "relevant_tickers": []}
        ], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(raw, _make_batch(1), False)
        assert ok
        assert scored[0].is_highlight is False

    def test_invalid_type_defaults_false(self):
        """整数/字典/None 应被安全降级为 false（不报错）。"""
        for bad in (123, {"x": 1}, None, [1, 2]):
            raw = json.dumps([
                {"id": 1, "score": 8, "is_highlight": bad,
                 "reason": "", "tags": [], "relevant_tickers": []}
            ], ensure_ascii=False)
            scored, _, _, _, ok = _parse_response_detailed(raw, _make_batch(1), False)
            assert ok and len(scored) == 1
            assert scored[0].is_highlight is False, f"bad={bad!r}"


class TestIsHighlightEnglishBranch:
    """英文分支同样支持 is_highlight。"""

    def test_english_true_high_score(self):
        raw = json.dumps([
            {"id": 1, "score": 9, "is_highlight": True,
             "chinese_title": "英伟达业绩超预期",
             "chinese_summary": "英伟达 Q3 营收 350 亿美元同比大增，指引远超预期",
             "why_it_matters": "业绩爆炸，AI 算力龙头",
             "tags": [], "relevant_tickers": ["NVDA"]}
        ], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(
            raw, _make_batch(1, is_english=True), True,
        )
        assert ok and len(scored) == 1
        assert scored[0].is_highlight is True
        assert scored[0].chinese_title.startswith("英伟达")


class TestScoredNewsItemDefault:
    def test_default_is_false(self):
        raw_item = _make_batch(1)[0]
        item = ScoredNewsItem(
            raw=raw_item, score=8, reason="", summary="", tags=[],
        )
        assert item.is_highlight is False
