"""事件合成器（事件化新闻）单元测试。

覆盖：报道选取（高分+最新保底）、prompt 构造、LLM 事件包解析、
版本机制（首次 v1 / 实质更新 +1 / 无实质更新不增版）与主流程。
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.news import News
from app.services.event_synthesizer import (
    _build_update_params,
    _build_user_prompt,
    _parse_llm_response,
    _parse_material_update,
    _select_articles,
    auto_stabilize_events,
    synthesize_events,
)


# ── _select_articles ──


class TestSelectArticles:
    def _arts(self, n):
        return [
            {"title": f"t{i}", "ai_score": i % 10, "ts": f"2026-08-0{i % 9 + 1}"}
            for i in range(n)
        ]

    def test_few_articles_all_kept(self):
        arts = self._arts(5)
        assert len(_select_articles(arts)) == 5

    def test_high_score_prioritized(self):
        arts = self._arts(12)
        selected = _select_articles(arts, max_n=8)
        assert len(selected) == 8
        scores = sorted(a["ai_score"] for a in selected)
        # 最高分的一定在（9 分那条）
        assert 9 in scores

    def test_recent_guaranteed(self):
        """最新 2 条即使评分低也必须入选（避免遗漏最新实质更新）。"""
        old_high = [{"title": f"old{i}", "ai_score": 9, "ts": f"2026-07-0{i}"} for i in range(1, 8)]
        new_low = [
            {"title": "new1", "ai_score": 1, "ts": "2026-08-02T01:00"},
            {"title": "new2", "ai_score": 2, "ts": "2026-08-02T02:00"},
        ]
        selected = _select_articles(old_high + new_low, max_n=8)
        titles = {a["title"] for a in selected}
        assert "new1" in titles and "new2" in titles

    def test_sorted_by_time_ascending(self):
        """选满后必须按发布时间升序重排，使提示词'第 1 条为最早报道'成立，
        避免'先放最新两条、再按评分补齐'造成的顺序混乱误导模型对事件起点的判断。"""
        # 乱序输入：先最新、再最早、再中间
        arts = [
            {"title": "mid", "ai_score": 5, "ts": "2026-08-01T12:00:00"},
            {"title": "latest", "ai_score": 9, "ts": "2026-08-03T08:00:00"},
            {"title": "earliest", "ai_score": 3, "ts": "2026-08-01T06:00:00"},
            {"title": "new_2", "ai_score": 1, "ts": "2026-08-03T09:00:00"},
            {"title": "old_1", "ai_score": 8, "ts": "2026-08-01T07:00:00"},
        ]
        selected = _select_articles(arts, max_n=8)
        ts_seq = [a["ts"] for a in selected]
        assert ts_seq == sorted(ts_seq)
        # 第 1 条是时间最早者
        assert selected[0]["title"] == "earliest"


# ── _parse_material_update（严格布尔解析）──


class TestParseMaterialUpdate:
    def test_bool_true(self):
        assert _parse_material_update(True) is True

    def test_bool_false(self):
        # 干净的 JSON 布尔 false：明确"无实质更新"，不应触发重试
        assert _parse_material_update(False) is False

    def test_string_true(self):
        assert _parse_material_update("true") is True
        assert _parse_material_update("TRUE") is True

    def test_string_false(self):
        # 关键回归：字符串 "false" 在旧逻辑里被 bool() 误判为 True，
        # 会错误递增事件版本。修复后应为 False（无实质更新）。
        assert _parse_material_update("false") is False
        assert _parse_material_update("False") is False

    def test_garbage_returns_none(self):
        # 数字 / 其它字符串 / None / 空 → 解析失败，触发重试
        assert _parse_material_update(None) is None
        assert _parse_material_update(1) is None
        assert _parse_material_update(0) is None
        assert _parse_material_update("maybe") is None
        assert _parse_material_update("") is None


# ── _build_user_prompt ──


class TestBuildUserPrompt:
    def test_first_synthesis_no_prev(self):
        articles = [{"title": "t", "source": "s", "ai_score": 7,
                     "ai_summary": "x", "catalyst_type": None}]
        prompt = _build_user_prompt(articles, None)
        assert "此前事件状态" not in prompt
        assert "【报道1】" in prompt

    def test_publish_time_in_article(self):
        """每条报道须明确提供发布时间（ts），且开头提示已按时间升序排列。"""
        articles = [{"title": "t", "source": "s", "ai_score": 7,
                     "ai_summary": "x", "catalyst_type": None, "ts": "2026-08-01T09:30:00"}]
        prompt = _build_user_prompt(articles, None)
        assert "发布时间" in prompt
        assert "2026-08-01T09:30:00" in prompt
        assert "第 1 条为最早报道" in prompt

    def test_prev_state_included(self):
        articles = [{"title": "t", "source": "s", "ai_score": 7,
                     "ai_summary": "x", "catalyst_type": None}]
        prev = {"event_title": "旧标题", "event_summary": "旧摘要",
                "event_version": 2, "event_latest_change": "旧变化"}
        prompt = _build_user_prompt(articles, prev)
        assert "旧标题" in prompt and "v2" in prompt and "旧变化" in prompt

    def test_memory_block_injected_before_articles(self):
        """历史同类事件应出现在报道列表之前，保证「本次新信息」离输出最近。"""
        articles = [{"title": "t", "source": "s", "ai_score": 7,
                     "ai_summary": "x", "catalyst_type": None}]
        block = "【历史同类事件（仅作背景参照，不是本次报道内容）】\n1. [2026-05-01｜resolved｜v3] 旧事件"
        prompt = _build_user_prompt(articles, None, block)
        assert prompt.index("历史同类事件") < prompt.index("【报道1】")

    def test_no_memory_block_when_empty(self):
        articles = [{"title": "t", "source": "s", "ai_score": 7,
                     "ai_summary": "x", "catalyst_type": None}]
        prompt = _build_user_prompt(articles, None, "")
        assert "历史同类事件" not in prompt


# ── _parse_llm_response ──


def _event_json(**overrides):
    base = {
        "event_title": "英伟达Q3财报超预期",
        "event_summary": "多家媒体报道英伟达财报……",
        "latest_change": "官方首次确认下季指引上调",
        "why_important": "算力供应链订单预期上修",
        "uncertainty": "产能爬坡节奏未披露",
        "watch_next": "关注下周台积电法说会",
        "status": "developing",
        "has_material_update": True,
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


class TestParseLlmResponse:
    def test_full_json(self):
        parsed = _parse_llm_response(_event_json())
        assert parsed["event_title"] == "英伟达Q3财报超预期"
        assert parsed["has_material_update"] is True
        assert parsed["status"] == "developing"
        assert parsed["watch_next"] == "关注下周台积电法说会"

    def test_json_with_fence(self):
        parsed = _parse_llm_response("```json\n" + _event_json() + "\n```")
        assert parsed is not None

    def test_invalid_json_returns_none(self):
        assert _parse_llm_response("not json") is None

    def test_missing_required_returns_none(self):
        assert _parse_llm_response('{"latest_change": "x"}') is None

    def test_invalid_status_normalized(self):
        parsed = _parse_llm_response(_event_json(status="爆炸"))
        assert parsed["status"] == ""

    def test_optional_fields_default_empty(self):
        parsed = _parse_llm_response(_event_json(
            latest_change=None, uncertainty=None, watch_next=None,
        ))
        assert parsed["latest_change"] == ""
        assert parsed["uncertainty"] == ""
        assert parsed["watch_next"] == ""

    def test_string_false_is_no_update_not_failure(self):
        """模型返回字符串 \"false\" 应被正确解析为无实质更新，
        而非旧逻辑 bool(\"false\")==True 般误判导致错误递增版本。"""
        parsed = _parse_llm_response(_event_json(has_material_update="false"))
        assert parsed is not None
        assert parsed["has_material_update"] is False

    def test_garbage_material_update_triggers_retry(self):
        """has_material_update 为数字 / None / 其它字符串 → 整段解析失败 → None（触发重试）。"""
        assert _parse_llm_response(_event_json(has_material_update=1)) is None
        assert _parse_llm_response(_event_json(has_material_update="maybe")) is None
        assert _parse_llm_response(_event_json(has_material_update=None)) is None


# ── _build_update_params（版本机制）──


def _cluster(event_version=None, child_cnt=4, event_source_cnt=4):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "child_cnt": child_cnt,
        "event_source_cnt": event_source_cnt,
        "event_version": event_version,
        "published_at": None,
        "created_at": None,
    }


class TestBuildUpdateParams:
    def test_first_synthesis_v1(self):
        params = _build_update_params(_cluster(event_version=None), {
            "event_title": "t", "event_summary": "s", "latest_change": "首次",
            "why_important": "w", "uncertainty": "", "watch_next": "",
            "status": "new", "has_material_update": True,
        })
        assert params["version"] == 1
        assert params["material"] is True
        assert params["is_first"] is True
        assert params["article_count"] == 5
        assert params["source_count"] == 4  # 去重后 4 个独立信源（根与子报道来源各不相同）

    def test_material_update_increments_version(self):
        params = _build_update_params(_cluster(event_version=2), {
            "event_title": "t", "event_summary": "s", "latest_change": "新确认",
            "why_important": "w", "uncertainty": "", "watch_next": "",
            "status": "", "has_material_update": True,
        })
        assert params["version"] == 3
        assert params["material"] is True
        assert params["status"] == "developing"  # 缺省回落

    def test_non_material_no_version_bump(self):
        """重复转述：不增版、不写内容字段，只更新计数（PRD 6.4）。"""
        params = _build_update_params(_cluster(event_version=2), {
            "event_title": "t", "event_summary": "s", "latest_change": "",
            "why_important": "w", "uncertainty": "", "watch_next": "",
            "status": "", "has_material_update": False,
        })
        assert "version" not in params
        assert "event_title" not in params
        assert params["material"] is False
        assert params["article_count"] == 5  # 计数仍更新（增量闸门）


# ── synthesize_events 主流程 ──


def _make_cluster(event_version=None):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "根报道标题",
        "source": "富途新闻",
        "ai_summary": "根摘要",
        "ai_score": 8,
        "catalyst_type": "业绩超预期",
        "created_at": None,
        "published_at": None,
        "event_title": None,
        "event_summary": None,
        "event_latest_change": None,
        "event_version": event_version,
        "event_article_count": None,
        "has_embedding": False,
        "child_cnt": 2,
        "event_source_cnt": 3,
        "children": [
            {"title": "子报道A", "source": "Finnhub", "ai_summary": "a",
             "ai_score": 7, "catalyst_type": None, "ts": "2026-08-02T01:00"},
            {"title": "子报道B", "source": "MarketWatch", "ai_summary": "b",
             "ai_score": 6, "catalyst_type": None, "ts": "2026-08-02T02:00"},
        ],
    }


def _mock_llm_client(content=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": content or _event_json()}}]
    }
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    return client


def _mock_session_ctx():
    mock_session = MagicMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, mock_session


class TestSynthesizeEvents:
    @pytest.mark.asyncio
    async def test_disabled_by_config(self):
        with patch("app.services.event_synthesizer.settings") as ms:
            ms.EVENT_SYNTH_ENABLED = False
            result = await synthesize_events()
        assert result == {"enabled": False, "synthesized": 0}

    @pytest.mark.asyncio
    async def test_first_synthesis_writes_version_snapshot(self):
        cluster = _make_cluster()
        ctx, mock_session = _mock_session_ctx()

        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch("app.services.event_synthesizer._find_candidate_clusters",
                  new=AsyncMock(return_value=[cluster])),
            patch("app.services.event_synthesizer.async_session", return_value=ctx),
            patch("app.services.event_synthesizer.httpx.AsyncClient") as mock_cls,
        ):
            ms.EVENT_SYNTH_ENABLED = True
            ms.LLM_API_KEY = "k"
            ms.LLM_MODEL = "deepseek-chat"
            ms.LLM_API_URL = "https://api.deepseek.com/v1/chat/completions"
            ms.EVENT_SYNTH_WINDOW_HOURS = 12
            ms.EVENT_SYNTH_MIN_SOURCES = 2
            ms.EVENT_SYNTH_MAX_EVENTS = 10
            ms.EVENT_MEMORY_ENABLED = False  # 记忆召回单独测试，此处隔离

            client = _mock_llm_client()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await synthesize_events()

        assert result["synthesized"] == 1
        # UPDATE + INSERT event_versions + commit
        assert mock_session.execute.await_count == 2
        update_params = mock_session.execute.call_args_list[0][0][1]
        assert update_params["version"] == 1
        assert update_params["source_count"] == 3
        assert update_params["material"] is True

    @pytest.mark.asyncio
    async def test_non_material_skips_version_snapshot(self):
        cluster = _make_cluster(event_version=1)
        ctx, mock_session = _mock_session_ctx()
        no_update_json = _event_json(has_material_update=False, latest_change="")

        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch("app.services.event_synthesizer._find_candidate_clusters",
                  new=AsyncMock(return_value=[cluster])),
            patch("app.services.event_synthesizer.async_session", return_value=ctx),
            patch("app.services.event_synthesizer.httpx.AsyncClient") as mock_cls,
        ):
            ms.EVENT_SYNTH_ENABLED = True
            ms.LLM_API_KEY = "k"
            ms.LLM_MODEL = "deepseek-chat"
            ms.LLM_API_URL = "https://api.deepseek.com/v1/chat/completions"
            ms.EVENT_SYNTH_WINDOW_HOURS = 12
            ms.EVENT_SYNTH_MIN_SOURCES = 2
            ms.EVENT_SYNTH_MAX_EVENTS = 10
            ms.EVENT_MEMORY_ENABLED = False  # 记忆召回单独测试，此处隔离

            client = _mock_llm_client(content=no_update_json)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await synthesize_events()

        assert result["synthesized"] == 1
        # 仅 UPDATE，不写版本快照
        assert mock_session.execute.await_count == 1
        update_params = mock_session.execute.call_args_list[0][0][1]
        assert update_params["material"] is False
        assert update_params["version"] is None  # COALESCE 不动版本

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_old_event(self):
        cluster = _make_cluster(event_version=1)
        ctx, mock_session = _mock_session_ctx()
        bad_client = MagicMock()
        bad_client.post = AsyncMock(side_effect=Exception("api down"))

        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch("app.services.event_synthesizer._find_candidate_clusters",
                  new=AsyncMock(return_value=[cluster])),
            patch("app.services.event_synthesizer.httpx.AsyncClient") as mock_cls,
        ):
            ms.EVENT_SYNTH_ENABLED = True
            ms.LLM_API_KEY = "k"
            ms.LLM_MODEL = "deepseek-chat"
            ms.LLM_API_URL = "https://api.deepseek.com/v1/chat/completions"
            ms.EVENT_SYNTH_WINDOW_HOURS = 12
            ms.EVENT_SYNTH_MIN_SOURCES = 2
            ms.EVENT_SYNTH_MAX_EVENTS = 10
            ms.EVENT_MEMORY_ENABLED = False  # 记忆召回单独测试，此处隔离

            mock_cls.return_value.__aenter__ = AsyncMock(return_value=bad_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await synthesize_events()

        assert result["synthesized"] == 0
        assert bad_client.post.await_count == 2  # 重试 1 次
        mock_session.execute.assert_not_called()  # 旧事件信息不被破坏


# ── auto_stabilize_events（每日维护：developing 超时 → stable）──


class TestAutoStabilize:
    @pytest.mark.asyncio
    async def test_developing_stale_becomes_stable(self, db_session):
        """developing 且无实质更新超 EVENT_STABLE_AFTER_HOURS 的事件 → stable；
        developing 但近期有更新、以及 resolved 事件应保持不变。"""
        from tests.conftest import _TestSession

        old = datetime.now(timezone.utc) - timedelta(hours=72)
        stale = News(
            id=uuid.uuid4(), title="stale", source="X", url="https://x.example/s",
            ai_score=7, ai_summary="s", event_status="developing",
            event_last_updated_at=old,
        )
        fresh = News(
            id=uuid.uuid4(), title="fresh", source="Y", url="https://y.example/f",
            ai_score=7, ai_summary="s", event_status="developing",
            event_last_updated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        resolved = News(
            id=uuid.uuid4(), title="resolved", source="Z", url="https://z.example/r",
            ai_score=7, ai_summary="s", event_status="resolved",
            event_last_updated_at=old,
        )
        db_session.add_all([stale, fresh, resolved])
        await db_session.commit()

        # auto_stabilize_events 内部用模块级 async_session，替换为测试用 in-memory 会话
        import app.services.event_synthesizer as es
        orig = es.async_session
        es.async_session = _TestSession
        try:
            result = await auto_stabilize_events()
        finally:
            es.async_session = orig

        assert result["stable"] == 1
        await db_session.refresh(stale)
        await db_session.refresh(fresh)
        await db_session.refresh(resolved)
        assert stale.event_status == "stable"
        assert fresh.event_status == "developing"  # 近期有更新，保持
        assert resolved.event_status == "resolved"  # 不依赖时间自动判定
