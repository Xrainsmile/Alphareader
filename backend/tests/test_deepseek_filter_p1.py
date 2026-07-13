"""P1 ⑤：Content Risk 二分隔离自测。

关键期望：
- 单条触发内容审查 → 定位到该条并丢弃，其他条目正常评分
- 递归深度限制生效
- content_risk_dropped 统计正确
- FilterResult.content_risk_dropped_items 累加
- 二分开关关闭时回退到旧行为（整批丢弃）
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.deepseek_filter import (
    BatchResult,
    RawNewsItem,
    filter_batch_detailed,
    filter_news,
    _bisect_content_risk,
    _score_batch_once,
)


def _make_items(n: int, prefix: str = "新闻") -> list[RawNewsItem]:
    return [
        RawNewsItem(
            title=f"{prefix}{i}",
            url=f"https://example.com/{i}",
            content=f"这是第{i}条中文新闻正文，内容充实。" * 3,
            source="mock",
            published_at=None,
        )
        for i in range(1, n + 1)
    ]


def _good_response(batch: list[RawNewsItem], score: int = 8) -> str:
    """给整批返回高分响应。"""
    return json.dumps(
        [
            {
                "id": i + 1,
                "score": score,
                "reason": "test",
                "summary": "摘要",
                "tags": [],
                "relevant_tickers": [],
            }
            for i in range(len(batch))
        ],
        ensure_ascii=False,
    )


# ═══════════════════════════════════════════════════════════════
# 二分核心逻辑
# ═══════════════════════════════════════════════════════════════

class TestBisectCore:
    """直接测 _bisect_content_risk 递归行为（不走 _score_batch_once）。"""

    @pytest.mark.asyncio
    async def test_bisect_locates_single_bad_item(self):
        """4 条里第 3 条为 bad → 应能定位并只丢它，其余 3 条正常评分。"""
        items = _make_items(4)
        bad_titles = {items[2].title}  # 第 3 条

        async def fake_score_once(batch, is_english, client):
            # 只要包含 bad item 就返回 content_risk
            if any(it.title in bad_titles for it in batch):
                return BatchResult(scored=[], status="content_risk")
            # 否则返回 ok（所有条目高分）
            scored = []
            from app.services.deepseek_filter import ScoredNewsItem
            for it in batch:
                scored.append(ScoredNewsItem(
                    raw=it, score=8, reason="ok", summary="", tags=[],
                    relevant_tickers=[], why_it_matters="ok",
                ))
            return BatchResult(scored=scored, status="ok")

        with patch("app.services.deepseek_filter._score_batch_once", side_effect=fake_score_once):
            client = MagicMock()
            result = await _bisect_content_risk(items, False, client, depth=0)

        assert result.content_risk_dropped == 1
        assert len(result.scored) == 3
        # 被丢的正是 bad_title
        scored_titles = {s.raw.title for s in result.scored}
        assert bad_titles.isdisjoint(scored_titles)

    @pytest.mark.asyncio
    async def test_bisect_single_item_bad(self):
        """batch=1 且 bad → 直接丢弃，dropped=1。"""
        items = _make_items(1)

        async def fake_score_once(batch, is_english, client):
            return BatchResult(scored=[], status="content_risk")

        with patch("app.services.deepseek_filter._score_batch_once", side_effect=fake_score_once):
            client = MagicMock()
            result = await _bisect_content_risk(items, False, client, depth=0)

        assert result.content_risk_dropped == 1
        assert result.scored == []
        assert result.status == "content_risk"

    @pytest.mark.asyncio
    async def test_bisect_max_depth_stop(self):
        """depth 达到上限 → 保守丢弃整个 sub-batch。"""
        items = _make_items(4)
        call_count = {"n": 0}

        async def fake_score_once(batch, is_english, client):
            call_count["n"] += 1
            return BatchResult(scored=[], status="content_risk")

        with patch("app.services.deepseek_filter._score_batch_once", side_effect=fake_score_once):
            # 传入 depth=6（已达 max_depth=6）
            client = MagicMock()
            result = await _bisect_content_risk(items, False, client, depth=6)

        # 到达上限时不再拆分，直接丢弃整个 sub-batch
        assert result.content_risk_dropped == 4
        assert call_count["n"] == 0  # 不再调用 API

    @pytest.mark.asyncio
    async def test_bisect_all_bad_two_items(self):
        """2 条都 bad → 递归拆到 batch=1 各自触发丢弃 → dropped=2。"""
        items = _make_items(2)

        async def fake_score_once(batch, is_english, client):
            return BatchResult(scored=[], status="content_risk")

        with patch("app.services.deepseek_filter._score_batch_once", side_effect=fake_score_once):
            client = MagicMock()
            result = await _bisect_content_risk(items, False, client, depth=0)

        assert result.content_risk_dropped == 2
        assert result.scored == []


# ═══════════════════════════════════════════════════════════════
# filter_batch_detailed：完整链路（触发 → 二分 → 合并）
# ═══════════════════════════════════════════════════════════════

class TestFilterBatchWithBisect:

    @pytest.mark.asyncio
    async def test_content_risk_triggers_bisect(self):
        """整批触发 content_risk → 二分定位 → 返回部分 scored + dropped。"""
        items = _make_items(4)
        bad_idx = 1  # 第 2 条

        call_seq = []

        async def fake_call(payload, headers, client):
            # 依据 payload 里的 user prompt 判断有没有 bad item
            user_msg = payload["messages"][1]["content"]
            has_bad = items[bad_idx].title in user_msg
            call_seq.append(("bad" if has_bad else "clean", user_msg.count("URL:")))
            if has_bad:
                return None, "content_risk", "content risk hit"
            # clean 批：为对应 batch 返回全部 8 分
            # 复原 batch 长度：读取 prompt 中 [1] [2] 的数量
            import re
            n = len(re.findall(r"^\[\d+\]", user_msg, re.MULTILINE))
            raw = json.dumps([
                {"id": i, "score": 8, "reason": "ok", "summary": "s", "tags": [], "relevant_tickers": []}
                for i in range(1, n + 1)
            ], ensure_ascii=False)
            return raw, "ok", ""

        mock_settings = MagicMock()
        mock_settings.SILICONFLOW_API_KEY = "k"
        mock_settings.SILICONFLOW_LLM_MODEL = "m"
        mock_settings.SILICONFLOW_API_URL = "http://x"
        mock_settings.DEEPSEEK_BATCH_SIZE = 20
        mock_settings.DEEPSEEK_MAX_RETRIES = 2
        mock_settings.DEEPSEEK_SCORE_THRESHOLD = 5
        mock_settings.DEEPSEEK_CONTENT_PREVIEW_CHARS = 800
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_TITLE = 0.5
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY = 0.6
        mock_settings.DEEPSEEK_CONTENT_RISK_BISECT_ENABLED = True
        mock_settings.DEEPSEEK_CONTENT_RISK_MAX_DEPTH = 6

        with patch("app.services.deepseek_filter.settings", mock_settings), \
             patch("app.services.deepseek_filter._call_llm_once", side_effect=fake_call):
            client = MagicMock()
            result = await filter_batch_detailed(items, is_english=False, client=client)

        assert result.content_risk_dropped == 1
        assert len(result.scored) == 3

    @pytest.mark.asyncio
    async def test_content_risk_bisect_disabled(self):
        """开关关闭 → 老行为：整批丢弃，dropped=len(batch)。"""
        items = _make_items(4)

        async def fake_call(payload, headers, client):
            return None, "content_risk", "hit"

        mock_settings = MagicMock()
        mock_settings.SILICONFLOW_API_KEY = "k"
        mock_settings.SILICONFLOW_LLM_MODEL = "m"
        mock_settings.SILICONFLOW_API_URL = "http://x"
        mock_settings.DEEPSEEK_MAX_RETRIES = 2
        mock_settings.DEEPSEEK_SCORE_THRESHOLD = 5
        mock_settings.DEEPSEEK_CONTENT_PREVIEW_CHARS = 800
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_TITLE = 0.5
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY = 0.6
        mock_settings.DEEPSEEK_CONTENT_RISK_BISECT_ENABLED = False
        mock_settings.DEEPSEEK_CONTENT_RISK_MAX_DEPTH = 6

        with patch("app.services.deepseek_filter.settings", mock_settings), \
             patch("app.services.deepseek_filter._call_llm_once", side_effect=fake_call):
            client = MagicMock()
            result = await filter_batch_detailed(items, is_english=False, client=client)

        assert result.status == "content_risk"
        assert result.content_risk_dropped == 4
        assert result.scored == []

    @pytest.mark.asyncio
    async def test_normal_batch_no_bisect_involved(self):
        """无 content_risk 时不应走二分。"""
        items = _make_items(3)

        async def fake_call(payload, headers, client):
            raw = json.dumps([
                {"id": i, "score": 8, "reason": "ok", "summary": "s", "tags": [], "relevant_tickers": []}
                for i in range(1, 4)
            ], ensure_ascii=False)
            return raw, "ok", ""

        mock_settings = MagicMock()
        mock_settings.SILICONFLOW_API_KEY = "k"
        mock_settings.SILICONFLOW_LLM_MODEL = "m"
        mock_settings.SILICONFLOW_API_URL = "http://x"
        mock_settings.DEEPSEEK_MAX_RETRIES = 2
        mock_settings.DEEPSEEK_SCORE_THRESHOLD = 5
        mock_settings.DEEPSEEK_CONTENT_PREVIEW_CHARS = 800
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_TITLE = 0.5
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY = 0.6
        mock_settings.DEEPSEEK_CONTENT_RISK_BISECT_ENABLED = True
        mock_settings.DEEPSEEK_CONTENT_RISK_MAX_DEPTH = 6

        with patch("app.services.deepseek_filter.settings", mock_settings), \
             patch("app.services.deepseek_filter._call_llm_once", side_effect=fake_call):
            client = MagicMock()
            result = await filter_batch_detailed(items, is_english=False, client=client)

        assert result.status == "ok"
        assert result.content_risk_dropped == 0
        assert len(result.scored) == 3


# ═══════════════════════════════════════════════════════════════
# FilterResult.content_risk_dropped_items 累加
# ═══════════════════════════════════════════════════════════════

class TestFilterNewsAccumulation:

    @pytest.mark.asyncio
    async def test_dropped_items_accumulated(self):
        """跨多个 batch 的 dropped 数应累加进 FilterResult.content_risk_dropped_items。"""
        items = _make_items(6)

        async def fake_filter_batch_detailed(batch, is_english, client):
            # 每个 batch 假装 dropped=1，剩余全部 scored
            from app.services.deepseek_filter import ScoredNewsItem
            scored = [
                ScoredNewsItem(
                    raw=it, score=8, reason="", summary="", tags=[],
                    relevant_tickers=[], why_it_matters="",
                )
                for it in batch[1:]  # 丢第 1 条
            ]
            return BatchResult(
                scored=scored,
                status="ok",
                content_risk_dropped=1,
            )

        mock_settings = MagicMock()
        mock_settings.DEEPSEEK_BATCH_SIZE = 3  # 6 条拆 2 batch
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_TITLE = 0.5
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY = 0.6

        with patch("app.services.deepseek_filter.settings", mock_settings), \
             patch("app.services.deepseek_filter.filter_batch_detailed",
                   side_effect=fake_filter_batch_detailed):
            result = await filter_news(items)

        # 2 个 batch 各丢 1 条
        assert result.content_risk_dropped_items == 2
        assert len(result.scored) == 4
        # 未整批失败，had_errors 应为 False（部分丢弃不算 batch skipped）
        assert result.had_errors is False
