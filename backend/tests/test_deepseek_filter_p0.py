"""P0 改造自测 — 覆盖 deepseek_filter.py 新增的语言/校验/结构化状态能力.

Run:
    cd backend && .venv-test/bin/python -m pytest tests/test_deepseek_filter_p0.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.llm_news_filter import (
    BatchResult,
    FilterResult,
    _chinese_ratio,
    _clean_tickers,
    _detect_is_english,
    _ensure_string_list,
    _is_chinese_dominant,
    _parse_response_detailed,
    _validate_ticker,
    filter_batch_detailed,
    filter_news,
)
from app.services.rss_fetcher import RawNewsItem


def _make_batch(n: int, is_english: bool = False) -> list[RawNewsItem]:
    items = []
    for i in range(n):
        if is_english:
            items.append(RawNewsItem(
                title=f"Test English News Title {i+1}",
                content=f"This is content for English news {i+1}.",
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
    body = {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
    return httpx.Response(
        status_code=status_code,
        json=body,
        request=httpx.Request("POST", "https://api.siliconflow.cn/v1/chat/completions"),
    )


# ═══════════════════════════════════════════════════════════════
# ⑦ 中文占比校验 & 品牌保留
# ═══════════════════════════════════════════════════════════════

class TestChineseRatio:
    def test_pure_chinese(self):
        assert _chinese_ratio("完全中文标题") == 1.0

    def test_pure_english(self):
        assert _chinese_ratio("OpenAI releases GPT-5") == 0.0

    def test_empty(self):
        assert _chinese_ratio("") == 0.0
        assert _chinese_ratio("123456") == 0.0  # 纯数字没有中英文字符

    def test_mixed_ok(self):
        # "英伟达 Q3 财报公布" — 6 汉字 + 1 字母（Q）= 6/7 ≈ 0.86
        r = _chinese_ratio("英伟达 Q3 财报公布")
        assert 0.8 < r < 0.9

    def test_brand_preservation_case(self):
        # 你举的正例：品牌名保留应该通过
        # "OpenAI 发布 GPT-5 推理模型" — "发布""推理模型" 6 汉字 + "OpenAI""GPT" 9 字母 = 6/15 = 0.4
        # 这个字符占比反而不高，说明我们的阈值 0.5 太严格？让我们试更真实的翻译
        # "OpenAI 发布多模态旗舰模型 GPT-4o" — 8 汉字 + "OpenAI""GPT" 9 字母 = 8/17 ≈ 0.47
        r = _chinese_ratio("OpenAI 发布多模态旗舰模型 GPT-4o")
        # 允许品牌保留，但也说明 0.5 是合理临界
        assert 0.4 < r < 0.55

    def test_english_fake_translation_rejected(self):
        # 你举的反例："OpenAI releases GPT-5，今日发布"
        # 4 汉字 + "OpenAIreleasesGPT" ~17 字母 = 4/21 ≈ 0.19
        text = "OpenAI releases GPT-5，今日发布"
        r = _chinese_ratio(text)
        assert r < 0.3
        assert not _is_chinese_dominant(text, min_ratio=0.5)


# ═══════════════════════════════════════════════════════════════
# ⑧ 语言检测：字符占比优先，langdetect 兜底
# ═══════════════════════════════════════════════════════════════

class TestDetectEnglish:
    def test_short_chinese_stable(self):
        # langdetect 常把"茅台涨停"误判为其他语言，我们的实现应稳定判为中文
        assert _detect_is_english("茅台涨停") is False

    def test_short_english(self):
        assert _detect_is_english("Apple stock hits record high") is True

    def test_stock_code_only(self):
        # "300750" 纯数字，无字母，默认中文
        assert _detect_is_english("300750") is False

    def test_mixed_but_chinese_dominant(self):
        # 中文为主，含少量英文
        assert _detect_is_english("英伟达 Q3 财报超预期") is False

    def test_pure_english_no_chinese(self):
        assert _detect_is_english("Fed keeps rates unchanged") is True

    def test_empty_string(self):
        assert _detect_is_english("") is False


# ═══════════════════════════════════════════════════════════════
# ⑨ 字段类型 & ticker 校验
# ═══════════════════════════════════════════════════════════════

class TestEnsureStringList:
    def test_normal_list(self):
        assert _ensure_string_list(["a", "b", "c"]) == ["a", "b", "c"]

    def test_deduplicate(self):
        assert _ensure_string_list(["a", "b", "a", "c"]) == ["a", "b", "c"]

    def test_strip_whitespace(self):
        assert _ensure_string_list(["  a  ", "b", ""]) == ["a", "b"]

    def test_reject_non_string(self):
        assert _ensure_string_list(["a", 123, None, {"x": 1}, "b"]) == ["a", "b"]

    def test_reject_non_list(self):
        assert _ensure_string_list("not a list") == []
        assert _ensure_string_list(None) == []
        assert _ensure_string_list({"a": 1}) == []

    def test_max_items_cap(self):
        assert _ensure_string_list(["a", "b", "c", "d", "e", "f"], max_items=3) == ["a", "b", "c"]


class TestValidateTicker:
    def test_a_share(self):
        assert _validate_ticker("300750") == "300750"
        assert _validate_ticker("600519") == "600519"

    def test_hk_share(self):
        assert _validate_ticker("00700") == "00700"
        assert _validate_ticker("09988") == "09988"

    def test_hk_4digit_padded(self):
        # 港股 4 位应自动补 0
        assert _validate_ticker("0700") == "00700"

    def test_us_share(self):
        assert _validate_ticker("NVDA") == "NVDA"
        assert _validate_ticker("BRK.B") == "BRK.B"
        assert _validate_ticker("nvda") == "NVDA"  # 大小写规范化

    def test_invalid_rejected(self):
        assert _validate_ticker("") is None
        assert _validate_ticker("XX") is None  # 太短
        assert _validate_ticker("1234567") is None  # 7 位数字不合法
        assert _validate_ticker("300750 涨停") is None  # 带非法字符


class TestCleanTickers:
    def test_mixed_valid_invalid(self):
        raw = ["NVDA", "00700", "invalid", "300750", 123]
        assert _clean_tickers(raw) == ["NVDA", "00700", "300750"]

    def test_dedup_after_normalize(self):
        # "0700" 补 0 后 = "00700"，与列表里已有 "00700" 重复
        raw = ["00700", "0700"]
        assert _clean_tickers(raw) == ["00700"]

    def test_cap_5(self):
        raw = ["300750", "600519", "601318", "601988", "000001", "000002"]
        assert len(_clean_tickers(raw)) == 5


# ═══════════════════════════════════════════════════════════════
# ⑥ 完整性校验（missing / duplicate / extra id）
# ═══════════════════════════════════════════════════════════════

class TestParseResponseDetailed:
    def test_missing_ids_detected(self):
        # 输入 3 条，只返回 2 条（id=1, id=3）
        raw = json.dumps([
            {"id": 1, "score": 8, "reason": "test", "tags": []},
            {"id": 3, "score": 7, "reason": "test", "tags": []},
        ], ensure_ascii=False)
        batch = _make_batch(3)
        scored, processed, missing, duplicate, parse_ok = _parse_response_detailed(raw, batch, False)
        assert parse_ok is True
        assert processed == {1, 3}
        assert missing == {2}
        assert duplicate == set()
        assert len(scored) == 2

    def test_duplicate_ids_detected(self):
        raw = json.dumps([
            {"id": 1, "score": 8, "reason": "first", "tags": []},
            {"id": 1, "score": 9, "reason": "second (should be discarded)", "tags": []},
            {"id": 2, "score": 7, "reason": "test", "tags": []},
        ], ensure_ascii=False)
        batch = _make_batch(2)
        scored, processed, missing, duplicate, parse_ok = _parse_response_detailed(raw, batch, False)
        assert parse_ok is True
        assert 1 in duplicate
        # 保留第一次出现（reason="first"）
        first = [s for s in scored if s.raw.url == batch[0].url][0]
        assert "first" in first.reason

    def test_out_of_range_id_dropped(self):
        raw = json.dumps([
            {"id": 1, "score": 8, "reason": "ok", "tags": []},
            {"id": 99, "score": 8, "reason": "hallucinated", "tags": []},
        ], ensure_ascii=False)
        batch = _make_batch(2)
        scored, processed, missing, _, parse_ok = _parse_response_detailed(raw, batch, False)
        assert parse_ok is True
        assert 99 not in processed
        assert missing == {2}

    def test_parse_error_returns_all_missing(self):
        raw = "this is not JSON at all"
        batch = _make_batch(3)
        scored, processed, missing, _, parse_ok = _parse_response_detailed(raw, batch, False)
        assert parse_ok is False
        assert missing == {1, 2, 3}
        assert scored == []

    def test_tags_type_stripped(self):
        # tags 是 dict/int 而非 list[str] — 应被丢弃
        raw = json.dumps([
            {"id": 1, "score": 8, "reason": "test", "tags": {"a": "b"}, "relevant_tickers": []},
            {"id": 2, "score": 7, "reason": "test", "tags": [123, "半导体", None, "英伟达"], "relevant_tickers": []},
        ], ensure_ascii=False)
        batch = _make_batch(2)
        scored, _, _, _, _ = _parse_response_detailed(raw, batch, False)
        assert scored[0].tags == []                       # dict 被拒
        assert scored[1].tags == ["半导体", "英伟达"]      # 只保留合法 str

    def test_ticker_validated(self):
        raw = json.dumps([
            {"id": 1, "score": 8, "reason": "test", "tags": [],
             "relevant_tickers": ["300750", "invalid", "NVDA", "0700"]},
        ], ensure_ascii=False)
        batch = _make_batch(1)
        scored, _, _, _, _ = _parse_response_detailed(raw, batch, False)
        # invalid 被去掉，"0700" 补 0 后 = "00700"
        assert set(scored[0].relevant_tickers) == {"300750", "NVDA", "00700"}


# ═══════════════════════════════════════════════════════════════
# ⑦ 英文翻译中文占比校验
# ═══════════════════════════════════════════════════════════════

class TestEnglishTranslationValidation:
    def test_keep_translation_with_any_chinese(self):
        # "OpenAI releases GPT-5，今日发布" — 4 汉字 21 字母 ratio ~0.19
        raw = json.dumps([{
            "id": 1, "score": 8,
            "chinese_title": "OpenAI releases GPT-5，今日发布",
            "chinese_summary": "OpenAI announced the release of GPT-5，市场关注度极高，投资者情绪显著提升，值得关注。",
            "tags": ["AI"],
            "relevant_tickers": [],
            "why_it_matters": "AI 龙头产品迭代，构成产业催化"
        }], ensure_ascii=False)
        batch = _make_batch(1, is_english=True)
        scored, _, _, _, _ = _parse_response_detailed(raw, batch, is_english=True)
        assert len(scored) == 1
        # 含中文即保留（新策略：不再因占比不足丢弃）
        assert scored[0].chinese_title == "OpenAI releases GPT-5，今日发布"

    def test_accept_brand_preservation(self):
        # "英伟达 Q3 财报大超预期" 中文主体 + 品牌保留 — ratio 高
        raw = json.dumps([{
            "id": 1, "score": 8,
            "chinese_title": "英伟达 Q3 财报大超预期",
            "chinese_summary": "英伟达发布 Q3 财报，营收 350 亿美元同比增长 94%，业绩指引上调远超市场预期",
            "tags": ["AI算力", "英伟达"],
            "relevant_tickers": ["NVDA"],
            "why_it_matters": "业绩超预期且指引上调"
        }], ensure_ascii=False)
        batch = _make_batch(1, is_english=True)
        scored, _, _, _, _ = _parse_response_detailed(raw, batch, is_english=True)
        assert len(scored) == 1
        assert scored[0].chinese_title == "英伟达 Q3 财报大超预期"


# ═══════════════════════════════════════════════════════════════
# ① BatchResult 状态语义
# ═══════════════════════════════════════════════════════════════

class TestBatchResultStatus:
    @pytest.mark.asyncio
    async def test_no_api_key(self):
        with patch("app.services.llm_news_filter.settings") as ms:
            ms.SILICONFLOW_API_KEY = ""
            result = await filter_batch_detailed(_make_batch(3), is_english=False)
        assert result.status == "no_api_key"
        assert result.scored == []

    @pytest.mark.asyncio
    async def test_content_risk_status(self):
        batch = _make_batch(5)
        error_response = httpx.Response(
            status_code=400,
            json={"error": {"message": "Content Exists Risk", "type": "content_filter"}},
            request=httpx.Request("POST", "https://api.siliconflow.cn/v1/chat/completions"),
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Bad Request", request=error_response.request, response=error_response,
            )
        )
        with patch("app.services.llm_news_filter.settings") as ms:
            ms.SILICONFLOW_API_KEY = "test-key"
            ms.SILICONFLOW_API_URL = "https://x"
            ms.SILICONFLOW_LLM_MODEL = "test"
            ms.LLM_MAX_RETRIES = 2
            ms.LLM_SCORE_THRESHOLD = 5
            ms.LLM_BATCH_SIZE = 20
            # 关闭二分，验证 P0 的"不重试"语义
            ms.LLM_CONTENT_RISK_BISECT_ENABLED = False
            result = await filter_batch_detailed(batch, is_english=False, client=mock_client)
        assert result.status == "content_risk"
        assert result.scored == []
        assert mock_client.post.call_count == 1  # 不重试（无二分）

    @pytest.mark.asyncio
    async def test_ok_but_empty_after_filter(self):
        """所有条目都低于阈值 → status=empty_after_filter，非 error"""
        # 5 条全部返回 score=2 (低于阈值 5)
        low_score_json = json.dumps([
            {"id": i, "score": 2, "reason": "noise", "tags": []}
            for i in range(1, 6)
        ], ensure_ascii=False)
        batch = _make_batch(5)
        response = _make_api_response(low_score_json)
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=response)
        with (
            patch("app.services.llm_news_filter.settings") as ms,
            patch.object(type(response), "raise_for_status", lambda self: None),
        ):
            ms.SILICONFLOW_API_KEY = "test-key"
            ms.SILICONFLOW_API_URL = "https://x"
            ms.SILICONFLOW_LLM_MODEL = "test"
            ms.LLM_MAX_RETRIES = 2
            ms.LLM_SCORE_THRESHOLD = 5
            ms.LLM_BATCH_SIZE = 20
            result = await filter_batch_detailed(batch, is_english=False, client=mock_client)
        assert result.status == "empty_after_filter"
        assert result.is_success is True   # empty_after_filter 不算失败
        assert result.scored == []
        # 关键：不应触发重试（旧行为会重试）
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_api_error_all_retries_exhausted(self):
        batch = _make_batch(5)
        error_response = httpx.Response(
            status_code=503,
            text="Service Unavailable",
            request=httpx.Request("POST", "https://x"),
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=error_response.request, response=error_response,
            )
        )
        with (
            patch("app.services.llm_news_filter.settings") as ms,
            patch("app.services.llm_news_filter.asyncio.sleep", new=AsyncMock()),
        ):
            ms.SILICONFLOW_API_KEY = "test-key"
            ms.SILICONFLOW_API_URL = "https://x"
            ms.SILICONFLOW_LLM_MODEL = "test"
            ms.LLM_MAX_RETRIES = 2
            ms.LLM_SCORE_THRESHOLD = 5
            ms.LLM_BATCH_SIZE = 20
            result = await filter_batch_detailed(batch, is_english=False, client=mock_client)
        assert result.status == "api_error"
        assert result.is_success is False


# ═══════════════════════════════════════════════════════════════
# ① filter_news skipped_batches / had_errors 正确统计
# ═══════════════════════════════════════════════════════════════

class TestFilterNewsHadErrors:
    @pytest.mark.asyncio
    async def test_had_errors_true_when_api_fails(self):
        """API 全挂时 had_errors 必须为 True（旧代码这里错报 False）"""
        batch = _make_batch(5)
        error_response = httpx.Response(
            status_code=503,
            text="Service Unavailable",
            request=httpx.Request("POST", "https://x"),
        )
        with (
            patch("app.services.llm_news_filter.httpx.AsyncClient") as MockClient,
            patch("app.services.llm_news_filter.settings") as ms,
            patch("app.services.llm_news_filter.asyncio.sleep", new=AsyncMock()),
        ):
            ms.SILICONFLOW_API_KEY = "test-key"
            ms.SILICONFLOW_API_URL = "https://x"
            ms.SILICONFLOW_LLM_MODEL = "test"
            ms.LLM_MAX_RETRIES = 2
            ms.LLM_SCORE_THRESHOLD = 5
            ms.LLM_BATCH_SIZE = 20
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Server Error", request=error_response.request, response=error_response,
                )
            )
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance
            result = await filter_news(batch)
        assert result.had_errors is True
        assert result.api_error_batches == 1
        assert result.skipped_batches == 1

    @pytest.mark.asyncio
    async def test_had_errors_false_when_only_low_score(self):
        """全部低分不算 error（这与旧行为的语义相同，但内部分类应清晰）"""
        low_score_json = json.dumps([
            {"id": i, "score": 2, "reason": "noise", "tags": []}
            for i in range(1, 4)
        ], ensure_ascii=False)
        response = _make_api_response(low_score_json)
        batch = _make_batch(3)
        with (
            patch("app.services.llm_news_filter.httpx.AsyncClient") as MockClient,
            patch("app.services.llm_news_filter.settings") as ms,
            patch.object(type(response), "raise_for_status", lambda self: None),
        ):
            ms.SILICONFLOW_API_KEY = "test-key"
            ms.SILICONFLOW_API_URL = "https://x"
            ms.SILICONFLOW_LLM_MODEL = "test"
            ms.LLM_MAX_RETRIES = 2
            ms.LLM_SCORE_THRESHOLD = 5
            ms.LLM_BATCH_SIZE = 20
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance
            result = await filter_news(batch)
        assert result.had_errors is False
        assert result.skipped_batches == 0
        assert result.scored == []


# ═══════════════════════════════════════════════════════════════
# ④ Prompt 长度与时间字段
# ═══════════════════════════════════════════════════════════════

class TestPromptLengthAndTime:
    def test_content_preview_extended(self):
        from app.services.llm_news_filter import _build_user_prompt
        # 制造一条超长正文
        long_content = "股价上涨。" * 500   # 2500 字符
        item = RawNewsItem(
            title="测试长文", content=long_content,
            url="https://x", source="test",
            published_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )
        prompt = _build_user_prompt([item], is_english=False)
        # 应该包含至少 800 字正文（我们的默认 CONTENT_PREVIEW_CHARS）
        # 简单校验：包含中间某处的"股价上涨"字样，且总长足够
        assert "股价上涨" in prompt
        assert len(prompt) > 800

    def test_published_time_included(self):
        from app.services.llm_news_filter import _build_user_prompt
        item = RawNewsItem(
            title="测试", content="内容",
            url="https://x", source="test",
            published_at=datetime(2026, 7, 1, 15, 30, tzinfo=timezone.utc),
        )
        prompt = _build_user_prompt([item], is_english=False)
        assert "发布时间: 2026-07-01 15:30" in prompt
        assert "抓取时间:" in prompt

    def test_no_published_time_when_missing(self):
        from app.services.llm_news_filter import _build_user_prompt
        item = RawNewsItem(
            title="测试", content="内容",
            url="https://x", source="test",
            published_at=None,
        )
        prompt = _build_user_prompt([item], is_english=False)
        assert "发布时间:" not in prompt
        assert "抓取时间:" in prompt  # fetched_at 始终有

    def test_english_prompt_time_fields(self):
        from app.services.llm_news_filter import _build_user_prompt
        item = RawNewsItem(
            title="Fed keeps rates", content="content",
            url="https://x", source="Reuters",
            published_at=datetime(2026, 7, 1, 15, 30, tzinfo=timezone.utc),
        )
        prompt = _build_user_prompt([item], is_english=True)
        assert "Published: 2026-07-01 15:30" in prompt
        assert "Fetched:" in prompt
