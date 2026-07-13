"""Full-stack parser tests — from raw LLM text to scored news items.

Tests three layers:
  1. JSON extraction: extract_llm_json() on every mock response
  2. Parse pipeline: _extract_json_array() + _parse_response() end-to-end
  3. filter_batch() with mocked httpx, verifying the complete flow
     without any real API calls

Run:
    cd backend && python3 -m pytest tests/test_parser.py -v
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.llm_news_filter import (
    FilterResult,
    ScoredNewsItem,
    _build_user_prompt,
    _extract_json_array,
    _parse_response,
    filter_batch,
    filter_news,
)
from app.services.rss_fetcher import RawNewsItem
from app.utils.json_extractor import extract_llm_json

from tests.mock_responses import (
    ALL_MOCK_POOL,
    CN_MOCK_POOL,
    EN_MOCK_POOL,
    CN_MOCK_PURE_JSON,
    CN_MOCK_THINK_ONLY,
    CN_MOCK_MARKDOWN_FENCE,
    CN_MOCK_THINK_FENCE_FILLER,
    CN_MOCK_DICT_WRAPPER,
    EN_MOCK_PURE_JSON,
    EN_MOCK_THINK_FENCE_FILLER,
    EN_MOCK_EDGE_SCORES,
    EN_MOCK_MULTIPLE_THINK_BLOCKS,
)

logger = logging.getLogger(__name__)


# ── Helpers ──

def _make_batch(n: int, is_english: bool = False) -> list[RawNewsItem]:
    """Create a batch of N dummy RawNewsItem for testing."""
    items = []
    for i in range(n):
        if is_english:
            items.append(RawNewsItem(
                title=f"Test English News Title {i+1}",
                content=f"This is test content for English news article number {i+1}.",
                url=f"https://example.com/en/news/{i+1}",
                source="Reuters",
                published_at=datetime(2026, 2, 10, 12, 0, 0),
                tags=["test"],
            ))
        else:
            items.append(RawNewsItem(
                title=f"测试中文新闻标题{i+1}",
                content=f"这是第{i+1}条测试新闻的正文内容。",
                url=f"https://example.com/cn/news/{i+1}",
                source="财联社",
                published_at=datetime(2026, 2, 10, 12, 0, 0),
                tags=["测试"],
            ))
    return items


def _make_api_response(content: str, status_code: int = 200) -> httpx.Response:
    """Build a fake httpx.Response wrapping LLM content in the OpenAI-compatible structure."""
    body = {
        "id": "mock-chatcmpl-001",
        "object": "chat.completion",
        "model": "deepseek-chat",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
    }
    return httpx.Response(
        status_code=status_code,
        json=body,
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
    )


# ═══════════════════════════════════════════════════════════════
# Layer 1: JSON Extraction — every mock must parse successfully
# ═══════════════════════════════════════════════════════════════

class TestJsonExtractionOnAllMocks:
    """extract_llm_json() must return non-None for every mock."""

    @pytest.mark.parametrize(
        "desc, raw_text, expected_count",
        ALL_MOCK_POOL,
        ids=[m[0] for m in ALL_MOCK_POOL],
    )
    def test_extraction_succeeds(self, desc: str, raw_text: str, expected_count: int):
        result = extract_llm_json(raw_text)
        assert result is not None, (
            f"[FAIL] extract_llm_json returned None\n"
            f"Scenario: {desc}\n"
            f"Raw text ({len(raw_text)} chars):\n{raw_text[:500]}"
        )
        # result can be list or dict (dict wrapper case)
        if isinstance(result, list):
            assert len(result) == expected_count, (
                f"Expected {expected_count} items, got {len(result)}\nScenario: {desc}"
            )
        elif isinstance(result, dict):
            # Dict wrapper — should have a list inside
            found_list = False
            for key in ("results", "data", "items", "news"):
                if key in result and isinstance(result[key], list):
                    assert len(result[key]) == expected_count
                    found_list = True
                    break
            if not found_list:
                # All values are dicts — also valid
                assert len(result) == expected_count


# ═══════════════════════════════════════════════════════════════
# Layer 2: _extract_json_array + _parse_response end-to-end
# ═══════════════════════════════════════════════════════════════

class TestParseResponseChinese:
    """_parse_response() with Chinese mock data."""

    @pytest.mark.parametrize(
        "desc, raw_text, item_count",
        CN_MOCK_POOL,
        ids=[m[0] for m in CN_MOCK_POOL],
    )
    def test_parse_cn_mocks(self, desc: str, raw_text: str, item_count: int):
        batch = _make_batch(item_count, is_english=False)
        scored = _parse_response(raw_text, batch, is_english=False)

        # At minimum, items with score >= 6 should be returned
        assert isinstance(scored, list), f"Expected list, got {type(scored)}"
        for item in scored:
            assert isinstance(item, ScoredNewsItem)
            assert item.score >= 6, f"Score below threshold: {item.score}"
            assert item.summary, "Summary should not be empty"
            assert len(item.tags) >= 0

        logger.info("[%s] Parsed %d/%d items above threshold", desc, len(scored), item_count)

    def test_cn_pure_json_specific_scores(self):
        """Verify specific items from CN_MOCK_PURE_JSON pass/fail threshold."""
        _, raw_text, count = CN_MOCK_PURE_JSON
        batch = _make_batch(count, is_english=False)
        scored = _parse_response(raw_text, batch, is_english=False)

        # id=1 score=9 should pass, id=2 score=3 should be filtered, id=3 score=8 should pass
        assert len(scored) == 2
        scores = {s.score for s in scored}
        assert 9 in scores
        assert 8 in scores

    def test_cn_dict_wrapper_unwrapped(self):
        """Verify _extract_json_array unwraps {"results": [...]}."""
        _, raw_text, count = CN_MOCK_DICT_WRAPPER
        result = _extract_json_array(raw_text)
        assert isinstance(result, list), "Dict wrapper should be unwrapped to list"
        assert len(result) == count


class TestParseResponseEnglish:
    """_parse_response() with English mock data."""

    @pytest.mark.parametrize(
        "desc, raw_text, item_count",
        EN_MOCK_POOL,
        ids=[m[0] for m in EN_MOCK_POOL],
    )
    def test_parse_en_mocks(self, desc: str, raw_text: str, item_count: int):
        batch = _make_batch(item_count, is_english=True)
        scored = _parse_response(raw_text, batch, is_english=True)

        assert isinstance(scored, list)
        for item in scored:
            assert isinstance(item, ScoredNewsItem)
            assert item.score >= 6
            # English items should have chinese_title with CJK chars
            if item.chinese_title:
                import re
                assert re.search(r"[\u4e00-\u9fff]", item.chinese_title), (
                    f"chinese_title lacks CJK characters: '{item.chinese_title}'"
                )

        logger.info("[%s] Parsed %d/%d EN items above threshold", desc, len(scored), item_count)

    def test_en_edge_scores(self):
        """Score 0 filtered, 6 passes, 10 passes, 11 capped to 10."""
        _, raw_text, count = EN_MOCK_EDGE_SCORES
        batch = _make_batch(count, is_english=True)
        scored = _parse_response(raw_text, batch, is_english=True)

        # score=0 filtered out, score=6,10,11(→10) should pass → 3 items
        assert len(scored) == 3
        score_values = sorted(s.score for s in scored)
        assert score_values == [6, 10, 10], f"Expected [6, 10, 10], got {score_values}"


# ═══════════════════════════════════════════════════════════════
# Layer 3: filter_batch() with mocked httpx — full integration
# ═══════════════════════════════════════════════════════════════

class TestFilterBatchMocked:
    """Test filter_batch() by mocking httpx.AsyncClient.post()."""

    @pytest.fixture(autouse=True)
    def _patch_api_key(self):
        """Ensure DEEPSEEK_API_KEY is set so filter_batch doesn't bail out."""
        with patch("app.services.llm_news_filter.settings") as mock_settings:
            mock_settings.DEEPSEEK_API_KEY = "sk-test-mock-key"
            mock_settings.DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
            mock_settings.DEEPSEEK_MODEL = "deepseek-chat"
            mock_settings.LLM_BATCH_SIZE = 20
            mock_settings.LLM_SCORE_THRESHOLD = 6
            mock_settings.LLM_MAX_RETRIES = 2
            # P1 ⑤：既有测试假设 content_risk 只调 1 次；关闭二分以保持兼容
            mock_settings.LLM_CONTENT_RISK_BISECT_ENABLED = False
            mock_settings.LLM_CONTENT_RISK_MAX_DEPTH = 6
            # P3 ②：既有英文测试假设单阶段；关闭两阶段以保持兼容
            mock_settings.LLM_TWO_STAGE_EN_ENABLED = False
            mock_settings.LLM_TRANSLATE_BATCH_SIZE = 20
            # P3 ⑤：并发度（既有测试不依赖并发，但需避免 MagicMock truthy 问题）
            mock_settings.LLM_MAX_CONCURRENCY = 3
            yield

    @pytest.mark.parametrize(
        "desc, raw_text, item_count",
        CN_MOCK_POOL,
        ids=[m[0] for m in CN_MOCK_POOL],
    )
    @pytest.mark.asyncio
    async def test_cn_filter_batch_with_mock(self, desc: str, raw_text: str, item_count: int):
        """Mock the HTTP call, verify filter_batch returns scored items."""
        batch = _make_batch(item_count, is_english=False)
        mock_response = _make_api_response(raw_text)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(
            type(mock_response), "raise_for_status", lambda self: None
        ):
            scored = await filter_batch(batch, is_english=False, client=mock_client)

        assert isinstance(scored, list)
        for item in scored:
            assert isinstance(item, ScoredNewsItem)
            assert item.score >= 6

        mock_client.post.assert_called_once()
        logger.info("[%s] filter_batch returned %d items", desc, len(scored))

    @pytest.mark.parametrize(
        "desc, raw_text, item_count",
        EN_MOCK_POOL,
        ids=[m[0] for m in EN_MOCK_POOL],
    )
    @pytest.mark.asyncio
    async def test_en_filter_batch_with_mock(self, desc: str, raw_text: str, item_count: int):
        """Mock the HTTP call for English news."""
        batch = _make_batch(item_count, is_english=True)
        mock_response = _make_api_response(raw_text)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(
            type(mock_response), "raise_for_status", lambda self: None
        ):
            scored = await filter_batch(batch, is_english=True, client=mock_client)

        assert isinstance(scored, list)
        for item in scored:
            assert isinstance(item, ScoredNewsItem)
            assert item.score >= 6

        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_batch_no_api_key(self):
        """filter_batch should return [] when API key is not configured."""
        batch = _make_batch(3)
        # Override the autouse fixture's key with empty
        with patch("app.services.llm_news_filter.settings") as mock_settings:
            mock_settings.DEEPSEEK_API_KEY = ""
            result = await filter_batch(batch, is_english=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_filter_batch_content_risk_no_retry(self):
        """400 Content Exists Risk should skip immediately without retry."""
        batch = _make_batch(5)
        error_response = httpx.Response(
            status_code=400,
            json={"error": {"message": "Content Exists Risk", "type": "content_filter"}},
            request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Bad Request", request=error_response.request, response=error_response
            )
        )

        scored = await filter_batch(batch, is_english=False, client=mock_client)
        assert scored == []
        # Should only call once (no retry for content risk)
        assert mock_client.post.call_count == 1


# ═══════════════════════════════════════════════════════════════
# Layer 4: filter_news() end-to-end with language split
# ═══════════════════════════════════════════════════════════════

class TestFilterNewsMocked:
    """Test filter_news() with mocked httpx — verifies language split logic."""

    @pytest.mark.asyncio
    async def test_mixed_language_batch(self):
        """CN + EN items should be split and processed with correct prompts."""
        cn_items = _make_batch(3, is_english=False)
        en_items = _make_batch(2, is_english=True)
        all_items = cn_items + en_items

        _, cn_raw, _ = CN_MOCK_PURE_JSON
        _, en_raw, _ = EN_MOCK_PURE_JSON

        cn_response = _make_api_response(cn_raw)
        en_response = _make_api_response(en_raw)

        call_count = 0

        async def mock_post(url, json=None, headers=None):
            nonlocal call_count
            call_count += 1
            return cn_response if call_count == 1 else en_response

        with (
            patch("app.services.llm_news_filter.httpx.AsyncClient") as MockClient,
            patch("app.services.llm_news_filter.settings") as mock_settings,
            patch.object(type(cn_response), "raise_for_status", lambda self: None),
            patch.object(type(en_response), "raise_for_status", lambda self: None),
        ):
            mock_settings.DEEPSEEK_API_KEY = "sk-test-mock-key"
            mock_settings.DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
            mock_settings.DEEPSEEK_MODEL = "deepseek-chat"
            mock_settings.LLM_BATCH_SIZE = 20
            mock_settings.LLM_SCORE_THRESHOLD = 6
            mock_settings.LLM_MAX_RETRIES = 2

            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(side_effect=mock_post)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            result = await filter_news(all_items)

        assert isinstance(result, FilterResult)
        assert result.skipped_batches == 0
        assert result.total_batches == 2  # 1 CN batch + 1 EN batch
        assert len(result.scored) > 0
        assert not result.had_errors


# ═══════════════════════════════════════════════════════════════
# Layer 5: Stress test — cycle through all mocks repeatedly
# ═══════════════════════════════════════════════════════════════

class TestExtractionStress:
    """Cycle through every mock response multiple times to ensure 100% parse rate."""

    @pytest.mark.parametrize("iteration", range(5))
    def test_all_mocks_parse_100_percent(self, iteration: int):
        """Every mock must parse on every iteration — no flakiness allowed."""
        failures = []
        for desc, raw_text, expected_count in ALL_MOCK_POOL:
            result = extract_llm_json(raw_text)
            if result is None:
                failures.append(
                    f"  FAIL [{desc}]: returned None\n"
                    f"    Raw ({len(raw_text)} chars): {raw_text[:200]}..."
                )

        if failures:
            msg = (
                f"\n{'='*60}\n"
                f"Iteration {iteration+1}: {len(failures)} extraction failure(s):\n"
                + "\n".join(failures)
                + f"\n{'='*60}"
            )
            pytest.fail(msg)


# ═══════════════════════════════════════════════════════════════
# Bonus: _build_user_prompt sanity check
# ═══════════════════════════════════════════════════════════════

class TestBuildUserPrompt:
    """Verify user prompt generation format."""

    def test_cn_prompt_format(self):
        batch = _make_batch(2, is_english=False)
        prompt = _build_user_prompt(batch, is_english=False)
        assert "[1] 标题:" in prompt
        assert "[2] 标题:" in prompt
        assert "来源: 财联社" in prompt

    def test_en_prompt_format(self):
        batch = _make_batch(2, is_english=True)
        prompt = _build_user_prompt(batch, is_english=True)
        assert "[1] Title:" in prompt
        assert "[2] Title:" in prompt
        assert "Source: Reuters" in prompt
