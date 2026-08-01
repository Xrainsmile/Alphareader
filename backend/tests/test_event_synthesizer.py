"""事件合成器（方案A 事件中心化）单元测试。

覆盖纯函数（prompt 构造 / LLM 响应解析）与合成主流程
（mock DB 查询 + mock LLM HTTP 调用），不依赖真实数据库与 API。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.event_synthesizer import (
    _build_user_prompt,
    _parse_llm_response,
    synthesize_events,
)


# ── _build_user_prompt ──


class TestBuildUserPrompt:
    def test_includes_all_articles(self):
        articles = [
            {"title": "英伟达财报超预期", "source": "富途新闻", "ai_score": 8,
             "ai_summary": "营收350亿", "catalyst_type": "业绩超预期"},
            {"title": "NVDA beats", "source": "Finnhub", "ai_score": 7,
             "ai_summary": "Revenue beat", "catalyst_type": None},
        ]
        prompt = _build_user_prompt(articles)
        assert "英伟达财报超预期" in prompt
        assert "NVDA beats" in prompt
        assert "富途新闻" in prompt
        assert "Finnhub" in prompt
        assert "业绩超预期" in prompt
        assert "【报道1】" in prompt and "【报道2】" in prompt

    def test_summary_truncated(self):
        articles = [{"title": "t", "source": "s", "ai_score": 6,
                     "ai_summary": "x" * 500, "catalyst_type": None}]
        prompt = _build_user_prompt(articles)
        assert "x" * 201 not in prompt

    def test_missing_summary_ok(self):
        articles = [{"title": "t", "source": "s", "ai_score": 6,
                     "ai_summary": None, "catalyst_type": None}]
        prompt = _build_user_prompt(articles)
        assert "摘要" not in prompt


# ── _parse_llm_response ──


class TestParseLlmResponse:
    def test_plain_json(self):
        raw = '{"event_title": "英伟达Q3财报超预期", "event_summary": "多家媒体报道……"}'
        assert _parse_llm_response(raw) == ("英伟达Q3财报超预期", "多家媒体报道……")

    def test_json_with_fence(self):
        raw = '```json\n{"event_title": "标题", "event_summary": "综述"}\n```'
        assert _parse_llm_response(raw) == ("标题", "综述")

    def test_invalid_json_returns_none(self):
        assert _parse_llm_response("not json at all") is None

    def test_missing_fields_returns_none(self):
        assert _parse_llm_response('{"event_title": "只有标题"}') is None
        assert _parse_llm_response('{"event_summary": "只有综述"}') is None

    def test_empty_input(self):
        assert _parse_llm_response("") is None
        assert _parse_llm_response(None) is None


# ── synthesize_events 主流程 ──


def _make_cluster(event_article_count=None, child_cnt=2):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "根报道标题",
        "source": "富途新闻",
        "ai_summary": "根摘要",
        "ai_score": 8,
        "catalyst_type": "业绩超预期",
        "event_article_count": event_article_count,
        "child_cnt": child_cnt,
        "children": [
            {"title": "子报道A", "source": "Finnhub", "ai_summary": "a",
             "ai_score": 7, "catalyst_type": None},
            {"title": "子报道B", "source": "MarketWatch", "ai_summary": "b",
             "ai_score": 6, "catalyst_type": None},
        ],
    }


def _mock_llm_client(title="合成事件标题", summary="合成事件综述"):
    """构造 mock httpx.AsyncClient，LLM 返回合法 JSON。"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(
            {"event_title": title, "event_summary": summary}, ensure_ascii=False
        )}}]
    }
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    return client


class TestSynthesizeEvents:
    @pytest.mark.asyncio
    async def test_disabled_by_config(self):
        with patch("app.services.event_synthesizer.settings") as mock_settings:
            mock_settings.EVENT_SYNTH_ENABLED = False
            result = await synthesize_events()
        assert result == {"enabled": False, "synthesized": 0}

    @pytest.mark.asyncio
    async def test_no_candidates(self):
        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch(
                "app.services.event_synthesizer._find_candidate_clusters",
                new=AsyncMock(return_value=[]),
            ),
        ):
            ms.EVENT_SYNTH_ENABLED = True
            ms.LLM_API_KEY = "k"
            result = await synthesize_events()
        assert result["synthesized"] == 0
        assert result["candidates"] == 0

    @pytest.mark.asyncio
    async def test_synthesizes_and_updates_root(self):
        cluster = _make_cluster()
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch(
                "app.services.event_synthesizer._find_candidate_clusters",
                new=AsyncMock(return_value=[cluster]),
            ),
            patch("app.services.event_synthesizer.async_session", return_value=mock_ctx),
            patch("app.services.event_synthesizer.httpx.AsyncClient") as mock_client_cls,
        ):
            ms.EVENT_SYNTH_ENABLED = True
            ms.LLM_API_KEY = "k"
            ms.LLM_MODEL = "deepseek-chat"
            ms.LLM_API_URL = "https://api.deepseek.com/v1/chat/completions"
            ms.EVENT_SYNTH_WINDOW_HOURS = 12
            ms.EVENT_SYNTH_MIN_SOURCES = 2
            ms.EVENT_SYNTH_MAX_EVENTS = 10

            client = _mock_llm_client()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await synthesize_events()

        assert result["synthesized"] == 1
        # 验证回写 SQL 携带了合成结果与报道总数（根+2子=3）
        update_call = mock_session.execute.call_args
        params = update_call[0][1]
        assert params["t"] == "合成事件标题"
        assert params["s"] == "合成事件综述"
        assert params["n"] == 3

    @pytest.mark.asyncio
    async def test_llm_failure_skips_cluster(self):
        cluster = _make_cluster()
        bad_client = MagicMock()
        bad_client.post = AsyncMock(side_effect=Exception("api down"))

        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch(
                "app.services.event_synthesizer._find_candidate_clusters",
                new=AsyncMock(return_value=[cluster]),
            ),
            patch("app.services.event_synthesizer.httpx.AsyncClient") as mock_client_cls,
        ):
            ms.EVENT_SYNTH_ENABLED = True
            ms.LLM_API_KEY = "k"
            ms.LLM_MODEL = "deepseek-chat"
            ms.LLM_API_URL = "https://api.deepseek.com/v1/chat/completions"
            ms.EVENT_SYNTH_WINDOW_HOURS = 12
            ms.EVENT_SYNTH_MIN_SOURCES = 2
            ms.EVENT_SYNTH_MAX_EVENTS = 10

            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=bad_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await synthesize_events()

        assert result["synthesized"] == 0
        assert bad_client.post.await_count == 2  # 失败重试 1 次
