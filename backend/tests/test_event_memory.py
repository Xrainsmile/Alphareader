"""事件记忆（方案B：跨周期相似事件召回）单元测试。

覆盖：
  - 余弦召回的阈值边界（min_sim 下界 / max_sim 上界 / 自身排除 / top_k 截断）
  - 维度不匹配时的安全降级
  - prompt 片段渲染
  - 事件合成主流程与记忆层的集成（召回注入 + 向量回写策略）
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.services import event_memory
from app.services.event_memory import (
    EventMemoryIndex,
    MemoryHit,
    cluster_query_text,
    event_doc_text,
    format_memory_block,
    summarize_pattern_evidence,
)


def _vec(sim: float) -> list[float]:
    """构造与基准向量 [1, 0] 余弦恰为 sim 的二维单位向量，让阈值断言一目了然。"""
    return [sim, float(np.sqrt(max(0.0, 1.0 - sim * sim)))]


_QUERY = [1.0, 0.0]


def _index(entries: list[tuple[str, list[float]]]) -> EventMemoryIndex:
    """entries: [(event_id, vector)]，其余元数据填充占位值。"""
    meta = [{
        "event_id": eid,
        "title": f"历史事件-{eid}",
        "summary": "历史摘要内容",
        "status": "resolved",
        "version": 2,
        "seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
    } for eid, _ in entries]
    matrix = np.asarray([v for _, v in entries], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return EventMemoryIndex(meta, matrix / norms)


class _Cfg:
    """替身配置。数值与生产默认值保持一致，顺带守护「阈值语义」不被误改：
    上界 0.67 对齐 deduplicator 的事件聚合线——达到该相似度的属于同一事件，
    应由去重器处理，不能当作「历史同类事件」。"""

    EVENT_MEMORY_MIN_SIM = 0.50
    EVENT_MEMORY_MAX_SIM = 0.67
    EVENT_MEMORY_TOP_K = 3
    EVENT_MEMORY_SUMMARY_CHARS = 60
    EVENT_MEMORY_MIN_PATTERN_COUNT = 2
    EVENT_MEMORY_RECALL_STATUSES = ["stable", "resolved"]


# ── 召回阈值 ──


class TestRecall:
    def test_excludes_self(self):
        idx = _index([("a", _vec(0.60)), ("b", _vec(0.58))])
        with patch.object(event_memory, "settings", _Cfg):
            hits = idx.recall(_QUERY, exclude_ids={"a"})
        assert [h.event_id for h in hits] == ["b"]

    def test_drops_below_min_sim(self):
        idx = _index([("a", _vec(0.49))])
        with patch.object(event_memory, "settings", _Cfg):
            assert idx.recall(_QUERY, exclude_ids=set()) == []

    def test_drops_above_max_sim(self):
        """相似度达到事件聚合线说明是同一事件的不同表述，不是「历史参照」。
        放进来会让 LLM 把同一事件当成「这类事件的历史规律」。"""
        idx = _index([("dup", _vec(0.80))])
        with patch.object(event_memory, "settings", _Cfg):
            assert idx.recall(_QUERY, exclude_ids=set()) == []

    def test_keeps_within_band(self):
        idx = _index([("a", _vec(0.66)), ("b", _vec(0.50))])
        with patch.object(event_memory, "settings", _Cfg):
            hits = idx.recall(_QUERY, exclude_ids=set())
        assert {h.event_id for h in hits} == {"a", "b"}

    def test_top_k_truncation_sorted_desc(self):
        idx = _index([("a", _vec(0.66)), ("b", _vec(0.62)),
                      ("c", _vec(0.58)), ("d", _vec(0.54))])
        with patch.object(event_memory, "settings", _Cfg):
            hits = idx.recall(_QUERY, exclude_ids=set())
        assert [h.event_id for h in hits] == ["a", "b", "c"]  # 降序且截断到 top_k

    def test_dimension_mismatch_returns_empty(self):
        """切换 Embedding 提供商导致维度变化时，绝不能拿异构向量做比对。"""
        idx = _index([("a", _vec(0.60))])
        with patch.object(event_memory, "settings", _Cfg):
            assert idx.recall([1.0, 0.0, 0.0], exclude_ids=set()) == []

    def test_empty_query_returns_empty(self):
        idx = _index([("a", _vec(0.60))])
        with patch.object(event_memory, "settings", _Cfg):
            assert idx.recall([], exclude_ids=set()) == []

    def test_zero_vector_query_returns_empty(self):
        idx = _index([("a", _vec(0.60))])
        with patch.object(event_memory, "settings", _Cfg):
            assert idx.recall([0.0, 0.0], exclude_ids=set()) == []


# ── 文本构造 ──


class TestTextBuilders:
    def test_cluster_query_prefers_event_package(self):
        cluster = {"event_title": "事件标题", "event_summary": "事件摘要",
                   "title": "原标题", "ai_summary": "原摘要"}
        q = cluster_query_text(cluster)
        assert "事件标题" in q and "原标题" not in q

    def test_cluster_query_falls_back_to_root_article(self):
        cluster = {"event_title": None, "event_summary": None,
                   "title": "原标题", "ai_summary": "原摘要"}
        q = cluster_query_text(cluster)
        assert "原标题" in q and "原摘要" in q

    def test_event_doc_text_handles_none(self):
        assert event_doc_text(None, None) == ""
        assert event_doc_text("标题", None) == "标题"


# ── prompt 渲染 ──


class TestFormatMemoryBlock:
    def test_empty_hits_returns_empty_string(self):
        assert format_memory_block([]) == ""

    def test_renders_date_status_version(self):
        hits = [MemoryHit(
            event_id="a", title="某公司被调查", summary="监管介入后股价下跌",
            status="resolved", version=3,
            seen_at=datetime(2026, 5, 12, tzinfo=timezone.utc), similarity=0.71,
        )]
        with patch.object(event_memory, "settings", _Cfg):
            block = format_memory_block(hits)
        assert "2026-05-12" in block
        assert "resolved" in block and "v3" in block
        assert "某公司被调查" in block
        assert "背景参照" in block  # 必须声明非本次内容，防止 LLM 当作新事实

    def test_summary_truncated(self):
        hits = [MemoryHit("a", "标题", "摘" * 200, "stable", 1,
                          datetime(2026, 5, 12, tzinfo=timezone.utc), 0.7)]
        with patch.object(event_memory, "settings", _Cfg):
            block = format_memory_block(hits)
        assert block.count("摘") == _Cfg.EVENT_MEMORY_SUMMARY_CHARS

    def test_renders_outcome_when_present(self):
        """结果记忆：resolved 且带 outcome 时，记忆块应展示真实结局。"""
        hits = [MemoryHit(
            event_id="a", title="某公司被调查", summary="监管介入后股价下跌",
            status="resolved", version=3,
            seen_at=datetime(2026, 5, 12, tzinfo=timezone.utc), similarity=0.71,
            outcome_type="confirmed", final_outcome="处罚落地", watch_result="观察点已兑现",
            resolved_at=datetime(2026, 5, 20, tzinfo=timezone.utc), duration_hours=192,
        )]
        with patch.object(event_memory, "settings", _Cfg):
            block = format_memory_block(hits)
        assert "已确认/落地" in block
        assert "处罚落地" in block
        assert "观察点已兑现" in block
        assert "持续约 192h" in block

    def test_pattern_guardrail_insufficient_consistency(self):
        """结局方向不一致（confirmed vs reversed）→ 提醒逐条引用、勿写通常。"""
        hits = [
            MemoryHit("a", "t", "s", "resolved", 1,
                      datetime(2026, 1, 1, tzinfo=timezone.utc), 0.6, outcome_type="confirmed"),
            MemoryHit("b", "t", "s", "resolved", 1,
                      datetime(2026, 1, 1, tzinfo=timezone.utc), 0.6, outcome_type="reversed"),
        ]
        with patch.object(event_memory, "settings", _Cfg):
            block = format_memory_block(hits)
        assert "逐条引用" in block
        assert "勿臆断" in block

    def test_pattern_guardrail_consistent_allows_summary(self):
        """两个方向一致（confirmed）→ 允许归纳典型走向。"""
        hits = [
            MemoryHit("a", "t", "s", "resolved", 1,
                      datetime(2026, 1, 1, tzinfo=timezone.utc), 0.6, outcome_type="confirmed"),
            MemoryHit("b", "t", "s", "resolved", 1,
                      datetime(2026, 1, 1, tzinfo=timezone.utc), 0.6, outcome_type="confirmed"),
        ]
        with patch.object(event_memory, "settings", _Cfg):
            block = format_memory_block(hits)
        assert "方向一致" in block


class TestPatternEvidence:
    def test_single_event_no_pattern(self):
        hits = [MemoryHit("a", "t", "s", "resolved", 1, None, 0.6, outcome_type="confirmed")]
        with patch.object(event_memory, "settings", _Cfg):
            ev = summarize_pattern_evidence(hits)
        assert ev["has_pattern"] is False

    def test_two_consistent_has_pattern(self):
        hits = [
            MemoryHit("a", "t", "s", "resolved", 1, None, 0.6, outcome_type="confirmed"),
            MemoryHit("b", "t", "s", "resolved", 1, None, 0.6, outcome_type="confirmed"),
        ]
        with patch.object(event_memory, "settings", _Cfg):
            ev = summarize_pattern_evidence(hits)
        assert ev["has_pattern"] is True
        assert ev["consistent_outcome"] == "confirmed"

    def test_unknown_outcome_not_counted(self):
        """outcome_type=unknown 的结局不计入方向一致性判断。"""
        hits = [
            MemoryHit("a", "t", "s", "resolved", 1, None, 0.6, outcome_type="unknown"),
            MemoryHit("b", "t", "s", "resolved", 1, None, 0.6, outcome_type="unknown"),
        ]
        with patch.object(event_memory, "settings", _Cfg):
            ev = summarize_pattern_evidence(hits)
        assert ev["has_pattern"] is False


# ── 与合成主流程的集成 ──


def _cluster(cid="00000000-0000-0000-0000-000000000001", has_embedding=False,
             event_version=None):
    return {
        "id": cid,
        "title": "根报道标题",
        "source": "富途新闻",
        "ai_summary": "根摘要",
        "ai_score": 8,
        "catalyst_type": None,
        "created_at": None,
        "published_at": None,
        "event_title": None,
        "event_summary": None,
        "event_latest_change": None,
        "event_version": event_version,
        "event_article_count": None,
        "has_embedding": has_embedding,
        "child_cnt": 2,
        "event_source_cnt": 3,
        "children": [
            {"title": "子报道A", "source": "Finnhub", "ai_summary": "a",
             "ai_score": 7, "catalyst_type": None, "ts": "2026-08-02T01:00"},
        ],
    }


def _llm_client(material=True):
    body = (
        '{"event_title":"合成标题","event_summary":"合成摘要","latest_change":"变化",'
        '"why_important":"重要性","uncertainty":"","watch_next":"观察点",'
        f'"status":"new","has_material_update":{"true" if material else "false"}}}'
    )
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": body}}]}
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    return client


def _session_ctx():
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


def _synth_settings(ms, memory_enabled=True):
    ms.EVENT_SYNTH_ENABLED = True
    ms.LLM_API_KEY = "k"
    ms.LLM_MODEL = "deepseek-chat"
    ms.LLM_API_URL = "https://api.deepseek.com/v1/chat/completions"
    ms.EVENT_SYNTH_WINDOW_HOURS = 12
    ms.EVENT_SYNTH_MIN_SOURCES = 2
    ms.EVENT_SYNTH_MAX_EVENTS = 10
    ms.EVENT_MEMORY_ENABLED = memory_enabled


class TestSynthesisIntegration:
    @pytest.mark.asyncio
    async def test_recalled_memory_reaches_prompt(self):
        from app.services.event_synthesizer import synthesize_events

        ctx, _ = _session_ctx()
        client = _llm_client()
        idx = _index([("99999999-9999-9999-9999-999999999999", _vec(0.60))])

        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch("app.services.event_synthesizer._find_candidate_clusters",
                  new=AsyncMock(return_value=[_cluster()])),
            patch("app.services.event_synthesizer.async_session", return_value=ctx),
            patch("app.services.event_synthesizer.httpx.AsyncClient") as mock_cls,
            patch.object(event_memory, "settings", _Cfg),
            patch.object(event_memory, "load_index", new=AsyncMock(return_value=idx)),
            patch.object(event_memory, "embed_texts",
                         new=AsyncMock(return_value=[_QUERY])),
            patch.object(event_memory, "persist_embeddings",
                         new=AsyncMock(return_value=1)),
        ):
            _synth_settings(ms)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await synthesize_events()

        assert result["memory_recalled"] == 1
        user_msg = client.post.call_args[1]["json"]["messages"][1]["content"]
        assert "历史同类事件" in user_msg

    @pytest.mark.asyncio
    async def test_cold_start_no_index_still_synthesizes(self):
        """库中还没有任何事件向量时，只写入不召回，主流程不受影响。"""
        from app.services.event_synthesizer import synthesize_events

        ctx, _ = _session_ctx()
        client = _llm_client()
        persist = AsyncMock(return_value=1)

        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch("app.services.event_synthesizer._find_candidate_clusters",
                  new=AsyncMock(return_value=[_cluster()])),
            patch("app.services.event_synthesizer.async_session", return_value=ctx),
            patch("app.services.event_synthesizer.httpx.AsyncClient") as mock_cls,
            patch.object(event_memory, "settings", _Cfg),
            patch.object(event_memory, "load_index", new=AsyncMock(return_value=None)),
            patch.object(event_memory, "embed_texts",
                         new=AsyncMock(return_value=[[1.0, 0.0]])),
            patch.object(event_memory, "persist_embeddings", new=persist),
        ):
            _synth_settings(ms)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await synthesize_events()

        assert result["synthesized"] == 1
        assert result["memory_recalled"] == 0
        assert result["embedded"] == 1
        user_msg = client.post.call_args[1]["json"]["messages"][1]["content"]
        assert "历史同类事件" not in user_msg

    @pytest.mark.asyncio
    async def test_embedding_failure_does_not_break_synthesis(self):
        """Embedding API 挂掉时必须静默降级，绝不能影响事件合成落库。"""
        from app.services.event_synthesizer import synthesize_events

        ctx, _ = _session_ctx()
        client = _llm_client()

        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch("app.services.event_synthesizer._find_candidate_clusters",
                  new=AsyncMock(return_value=[_cluster()])),
            patch("app.services.event_synthesizer.async_session", return_value=ctx),
            patch("app.services.event_synthesizer.httpx.AsyncClient") as mock_cls,
            patch.object(event_memory, "settings", _Cfg),
            patch.object(event_memory, "load_index",
                         new=AsyncMock(side_effect=Exception("db down"))),
            patch.object(event_memory, "embed_texts",
                         new=AsyncMock(side_effect=Exception("api down"))),
        ):
            _synth_settings(ms)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await synthesize_events()

        assert result["synthesized"] == 1
        assert result["memory_recalled"] == 0
        assert result["embedded"] == 0

    @pytest.mark.asyncio
    async def test_non_material_with_existing_vector_skips_embedding(self):
        """无实质更新且已有当前模型向量 → 不重复调用 Embedding API。"""
        from app.services.event_synthesizer import synthesize_events

        ctx, _ = _session_ctx()
        client = _llm_client(material=False)
        persist = AsyncMock(return_value=0)
        embed = AsyncMock(return_value=[[1.0, 0.0]])

        with (
            patch("app.services.event_synthesizer.settings") as ms,
            patch("app.services.event_synthesizer._find_candidate_clusters",
                  new=AsyncMock(return_value=[
                      _cluster(has_embedding=True, event_version=2)])),
            patch("app.services.event_synthesizer.async_session", return_value=ctx),
            patch("app.services.event_synthesizer.httpx.AsyncClient") as mock_cls,
            patch.object(event_memory, "settings", _Cfg),
            patch.object(event_memory, "load_index", new=AsyncMock(return_value=None)),
            patch.object(event_memory, "embed_texts", new=embed),
            patch.object(event_memory, "persist_embeddings", new=persist),
        ):
            _synth_settings(ms)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await synthesize_events()

        assert result["synthesized"] == 1
        assert result["embedded"] == 0
        embed.assert_not_awaited()  # 冷启动跳过召回 + 无需回写 → 零 API 调用
        persist.assert_not_awaited()
