"""阶段简报服务（schema v2 事件化简报）测试。

覆盖 PRD 17.1 关键项：
  9. 简报只读取事件根；
  10. 简报条目包含有效 event_id（杜撰的丢弃）；
  11. 旧 Markdown 简报兼容；
  12. LLM JSON 解析异常处理；
  15.8 LLM 失败不覆盖上一版有效简报。
"""

import json
import uuid
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.news import News
from app.models.news_digest import NewsDigest
from app.services.digest_service import (
    GENERATION_TIME,
    DEFAULT_WINDOW,
    _TZ,
    _parse_briefing_json,
    _render_markdown,
    generate_digest,
)

_TZ_SH = None  # period range 内部自带时区


def _period_bounds(label, d):
    """复刻 generate_digest 在「无历史成功简报」时的首份窗口回退逻辑，
    便于测试构造落在目标简报窗口内的种子事件。"""
    gen_h, gen_m = GENERATION_TIME[label]
    period_end = _TZ.localize(datetime.combine(d, time(gen_h, gen_m)))
    ws_h, ws_m = DEFAULT_WINDOW[label]
    period_start = _TZ.localize(datetime.combine(d, time(ws_h, ws_m)))
    return period_start, period_end


# ── _parse_briefing_json ──


def _briefing_json(**overrides):
    base = {
        "period_summary": "本时段AI算力与车企销量为主线。",
        "must_know": [
            {"event_id": "id-1", "title": "事件一", "latest_change": "官方确认",
             "why_important": "影响供应链", "confidence": "high", "watch_next": "下周发布会"},
            {"event_id": "id-fake", "title": "杜撰事件", "latest_change": "",
             "why_important": "", "confidence": "high", "watch_next": ""},
        ],
        "worth_watching": [
            {"event_id": "id-2", "title": "事件二", "latest_change": "",
             "why_important": "值得留意", "confidence": "medium", "watch_next": ""},
        ],
        "cross_event_signals": [
            {"title": "资本开支向AI集中",
             "summary": "三家科技公司同时削减非核心业务",
             "event_ids": ["id-1", "id-fake"]},
        ],
        "upcoming": [{"time": "今晚 22:00", "item": "美联储讲话"}],
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


class TestParseBriefingJson:
    def test_valid_parse(self):
        parsed = _parse_briefing_json(_briefing_json(), {"id-1", "id-2"})
        assert parsed is not None
        assert parsed["period_summary"].startswith("本时段")

    def test_fake_event_id_dropped(self):
        """杜撰的 event_id 必须丢弃（PRD 17.1-10）。"""
        parsed = _parse_briefing_json(_briefing_json(), {"id-1", "id-2"})
        ids = [e["event_id"] for e in parsed["must_know"]]
        assert ids == ["id-1"]
        # 共同信号里的假 id 也被过滤
        assert parsed["cross_event_signals"][0]["event_ids"] == ["id-1"]

    def test_invalid_confidence_normalized(self):
        parsed = _parse_briefing_json(_briefing_json(), {"id-1", "id-2"})
        parsed["must_know"][0]["confidence"] == "high"
        bad = _briefing_json()
        data = json.loads(bad)
        data["must_know"][0]["confidence"] = "超级高"
        parsed2 = _parse_briefing_json(json.dumps(data), {"id-1", "id-2"})
        assert parsed2["must_know"][0]["confidence"] == "medium"

    def test_fence_tolerated(self):
        parsed = _parse_briefing_json("```json\n" + _briefing_json() + "\n```", {"id-1", "id-2"})
        assert parsed is not None

    def test_garbage_returns_none(self):
        assert _parse_briefing_json("不是JSON", {"id-1"}) is None

    def test_missing_summary_returns_none(self):
        assert _parse_briefing_json('{"must_know": []}', {"id-1"}) is None

    def test_empty_signals_allowed(self):
        parsed = _parse_briefing_json(
            _briefing_json(cross_event_signals=[]), {"id-1", "id-2"}
        )
        assert parsed["cross_event_signals"] == []


# ── _render_markdown ──


class TestRenderMarkdown:
    def test_sections_present(self):
        structured = _parse_briefing_json(_briefing_json(), {"id-1", "id-2"})
        md = _render_markdown(structured, "早间简报")
        assert "必须知道" in md
        assert "值得留意" in md
        assert "共同信号" in md
        assert "接下来关注" in md
        assert "事件一" in md
        assert "美联储讲话" in md

    def test_empty_sections_omitted(self):
        structured = {
            "period_summary": "s", "must_know": [], "worth_watching": [],
            "cross_event_signals": [], "upcoming": [],
        }
        md = _render_markdown(structured, "午间简报")
        assert "必须知道" not in md
        assert "s" in md


# ── 时段边界 ──


class TestPeriodRange:
    @pytest.mark.asyncio
    async def test_rolling_window_uses_previous_period_end(self, db_session):
        """本份 period_start 必须等于上一份成功简报的 period_end（滚动窗口，无空档）。"""
        prev_end = datetime.combine(date.today() - timedelta(days=1), time(18, 30))
        db_session.add(NewsDigest(
            digest_date=date.today() - timedelta(days=1), period_label="evening",
            period_start=datetime.combine(date.today() - timedelta(days=1), time(8, 30)),
            period_end=prev_end, news_count=5, content="上一版",
            schema_version=2, structured_content={"period_summary": "prev"},
        ))
        await db_session.commit()

        with patch("app.services.digest_service.async_session", _SessionPatch(db_session)):
            result = await generate_digest("morning", date.today())

        assert result["status"] == "ok"
        row = (
            await db_session.execute(
                __import__("sqlalchemy").select(NewsDigest).where(
                    NewsDigest.digest_date == date.today(),
                    NewsDigest.period_label == "morning",
                )
            )
        ).scalar_one()
        # 早报区间 = 上一份(前一日18:30) ~ 当日08:30，首尾相接
        assert row.period_start == prev_end
        assert row.period_end == datetime.combine(date.today(), time(8, 30))

    @pytest.mark.asyncio
    async def test_first_run_uses_default_window(self, db_session):
        """首份简报（无历史）回退到 DEFAULT_WINDOW，不产生异常。"""
        with patch("app.services.digest_service.async_session", _SessionPatch(db_session)):
            result = await generate_digest("morning", date.today())
        assert result["status"] == "ok"
        row = (
            await db_session.execute(
                __import__("sqlalchemy").select(NewsDigest).where(
                    NewsDigest.digest_date == date.today(),
                    NewsDigest.period_label == "morning",
                )
            )
        ).scalar_one()
        # 首份早报退化到当天 00:00 起
        assert row.period_start == datetime.combine(date.today(), time(0, 0))


# ── generate_digest 主流程 ──


async def _seed_event(db_session, title="事件根", with_child=False, updated=True,
                      period_label="morning"):
    # 种子的发布/更新时间必须落在目标时段内，否则被时段过滤排除。
    # 注意：SQLite 把 timestamptz 存为字符串做词学比较，种子必须与查询边界
    # 保持同一时区后缀（CST），故不做 astimezone(UTC) 转换
    start, _ = _period_bounds(period_label, date.today())
    in_period = start + timedelta(hours=1)
    root = News(
        id=uuid.uuid4(), title=title, source="富途新闻",
        url=f"https://example.com/{uuid.uuid4().hex[:8]}",
        ai_score=8, ai_summary="摘要", category="财经",
        published_at=in_period,
        created_at=in_period,
        event_title=f"{title}(合成)", event_summary="事件综述",
        event_latest_change="官方确认" if updated else "",
        event_status="developing", event_version=1,
        event_source_count=2 if with_child else 1,
        event_last_updated_at=in_period if updated else None,
    )
    db_session.add(root)
    if with_child:
        child = News(
            id=uuid.uuid4(), title=f"{title}子报道", source="CNBC",
            url=f"https://example.com/{uuid.uuid4().hex[:8]}",
            ai_score=5, category="财经",
            published_at=in_period,
            created_at=in_period,
            related_to_id=root.id,
        )
        db_session.add(child)
    await db_session.commit()
    return root


def _llm_json_for(event_id):
    return json.dumps({
        "period_summary": "测试时段概况",
        "must_know": [{"event_id": str(event_id), "title": "事件",
                       "latest_change": "官方确认", "why_important": "重要",
                       "confidence": "high", "watch_next": "下周"}],
        "worth_watching": [],
        "cross_event_signals": [],
        "upcoming": [{"time": "今晚", "item": "数据发布"}],
    }, ensure_ascii=False)


class TestGenerateDigest:
    @pytest.mark.asyncio
    async def test_reads_only_event_roots(self, db_session):
        """简报输入只含事件根；子报道不单独进入（PRD 17.1-9）。"""
        root = await _seed_event(db_session, with_child=True)
        captured = {}

        async def fake_stream(messages, **kw):
            captured["prompt"] = messages[1]["content"]
            return _llm_json_for(root.id)

        with (
            patch("app.services.digest_service.stream_chat", side_effect=fake_stream),
            patch("app.services.digest_service.async_session", _SessionPatch(db_session)),
        ):
            result = await generate_digest("morning", date.today())

        assert result["status"] == "ok"
        assert result["event_count"] == 1
        assert "子报道" not in captured["prompt"]
        assert str(root.id) in captured["prompt"]

    @pytest.mark.asyncio
    async def test_structured_saved_as_v2(self, db_session):
        root = await _seed_event(db_session)

        async def fake_stream(messages, **kw):
            return _llm_json_for(root.id)

        with (
            patch("app.services.digest_service.stream_chat", side_effect=fake_stream),
            patch("app.services.digest_service.async_session", _SessionPatch(db_session)),
        ):
            result = await generate_digest("morning", date.today())

        assert result["status"] == "ok"
        row = (
            await db_session.execute(
                __import__("sqlalchemy").select(NewsDigest).where(
                    NewsDigest.digest_date == date.today(),
                    NewsDigest.period_label == "morning",
                )
            )
        ).scalar_one()
        assert row.schema_version == 2
        assert row.structured_content["must_know"][0]["event_id"] == str(root.id)
        assert row.structured_content["event_count"] == 1
        # Markdown 兼容内容同步生成
        assert "必须知道" in row.content

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_previous(self, db_session):
        """LLM 失败不得覆盖上一版有效简报（PRD 15.8）。

        上一份成功简报（evening，period_end=当日08:30）存在；本份 evening 区间为
        [08:30, 18:30)，种子事件落在窗口内 → 会真正调用 LLM（且失败）→ 保留上一版。
        """
        db_session.add(NewsDigest(
            digest_date=date.today(), period_label="evening",
            period_start=datetime.combine(date.today(), time(0, 0)),
            period_end=datetime.combine(date.today(), time(8, 30)),
            news_count=10, content="上一版有效简报",
            schema_version=2,
            structured_content={"period_summary": "旧"},
        ))
        await _seed_event(db_session, period_label="evening")

        async def fail_stream(messages, **kw):
            return "这不是JSON"

        with (
            patch("app.services.digest_service.stream_chat", side_effect=fail_stream),
            patch("app.services.digest_service.async_session", _SessionPatch(db_session)),
        ):
            result = await generate_digest("evening", date.today())

        assert result["status"] == "error"
        assert result["reason"] == "llm_failed_kept_previous"
        row = (
            await db_session.execute(
                __import__("sqlalchemy").select(NewsDigest).where(
                    NewsDigest.digest_date == date.today(),
                    NewsDigest.period_label == "evening",
                )
            )
        ).scalar_one()
        assert row.content == "上一版有效简报"  # 未被覆盖

    @pytest.mark.asyncio
    async def test_no_events_skip(self, db_session):
        with patch("app.services.digest_service.async_session", _SessionPatch(db_session)):
            result = await generate_digest("evening", date.today())
        # 无事件时仍生成 no-LLM 简报并落库/推送（PRD 跨简报对比），status 为 "ok"
        assert result["status"] == "ok"


# ── 跨简报对比机制（change_type / 重复剔除 / ongoing / links）──


class TestFilterRepeatedEvents:
    def test_same_version_dropped(self):
        """event_version 未前进且非 RESOLVED → 剔除（PRD 第四步）。"""
        from app.services.digest_service import _filter_repeated_events
        events = [{
            "event_id": "e1", "title": "旧事件", "event_version": 2,
            "change_type": "MATERIAL_UPDATE",
        }]
        prev_links = {"e1": {"version": 2, "section": "worth_watching"}}
        kept, quiet = _filter_repeated_events(events, prev_links)
        assert kept == [] and quiet == []

    def test_version_advanced_kept(self):
        """event_version 前进 → 有新变化，保留。"""
        from app.services.digest_service import _filter_repeated_events
        events = [{
            "event_id": "e1", "title": "旧事件", "event_version": 3,
            "change_type": "MATERIAL_UPDATE",
        }]
        prev_links = {"e1": {"version": 2, "section": "must_know"}}
        kept, quiet = _filter_repeated_events(events, prev_links)
        assert len(kept) == 1 and quiet == []

    def test_dropped_must_know_becomes_quiet(self):
        """被剔除的上份 must_know 事件 → quiet_topics。"""
        from app.services.digest_service import _filter_repeated_events
        events = [{
            "event_id": "e1", "title": "旧重点", "event_version": 1,
            "change_type": "MATERIAL_UPDATE",
        }]
        prev_links = {"e1": {"version": 1, "section": "must_know"}}
        kept, quiet = _filter_repeated_events(events, prev_links)
        assert kept == []
        assert quiet[0]["title"] == "旧重点"

    def test_resolved_always_kept(self):
        """RESOLVED 即使版本未前进也保留（用户需要知道事件结束）。"""
        from app.services.digest_service import _filter_repeated_events
        events = [{
            "event_id": "e1", "title": "结束事件", "event_version": 2,
            "change_type": "RESOLVED",
        }]
        prev_links = {"e1": {"version": 2, "section": "must_know"}}
        kept, _ = _filter_repeated_events(events, prev_links)
        assert len(kept) == 1


class TestOngoingUpdates:
    @pytest.mark.asyncio
    async def test_stale_developing_becomes_ongoing(self, db_session):
        """上份收录、本时段无更新、仍 developing → ongoing 压缩行。"""
        from app.services.digest_service import _build_ongoing_updates
        root = await _seed_event(db_session, title="持续事件", updated=True)
        prev_links = {str(root.id): {"version": 1, "section": "must_know"}}

        with patch("app.services.digest_service.async_session", _SessionPatch(db_session)):
            ongoing, quiet = await _build_ongoing_updates([], prev_links)
        assert len(ongoing) == 1
        assert ongoing[0]["title"] == "持续事件(合成)"
        assert "无实质更新" in ongoing[0]["note"]
        assert quiet == []

    @pytest.mark.asyncio
    async def test_stale_resolved_must_know_becomes_quiet(self, db_session):
        """上份 must_know、本时段无更新、已非 developing → quiet。"""
        from app.services.digest_service import _build_ongoing_updates
        root = await _seed_event(db_session, title="冷却事件", updated=False)
        root.event_status = "stable"
        await db_session.commit()
        prev_links = {str(root.id): {"version": 1, "section": "must_know"}}

        with patch("app.services.digest_service.async_session", _SessionPatch(db_session)):
            ongoing, quiet = await _build_ongoing_updates([], prev_links)
        assert ongoing == []
        assert len(quiet) == 1


class TestDigestEventLinks:
    @pytest.mark.asyncio
    async def test_links_written_and_reused(self, db_session):
        """第一份简报写 links；第二份同版本事件被剔除，不重复入选。"""
        from app.models.digest_event_link import DigestEventLink
        from sqlalchemy import select as sa_select
        root = await _seed_event(db_session, title="对比事件")

        async def fake_stream(messages, **kw):
            return _llm_json_for(root.id)

        with (
            patch("app.services.digest_service.stream_chat", side_effect=fake_stream),
            patch("app.services.digest_service.async_session", _SessionPatch(db_session)),
        ):
            r1 = await generate_digest("morning", date.today())

        assert r1["status"] == "ok"
        links = (await db_session.execute(sa_select(DigestEventLink))).scalars().all()
        assert len(links) == 1
        assert links[0].section == "must_know"
        assert links[0].event_version == 1

        # 第二轮：事件版本未前进（仍 v1）→ 被剔除 → 无候选 → 仍生成 no-LLM 简报，status 为 "ok"
        with (
            patch("app.services.digest_service.stream_chat", side_effect=fake_stream),
            patch("app.services.digest_service.async_session", _SessionPatch(db_session)),
        ):
            r2 = await generate_digest("evening", date.today())
        assert r2["status"] == "ok"


def _SessionPatch(shared_session):
    """把 digest_service 里的 async_session 替换为共享测试 session 的工厂。

    digest_service 内部每次 `async with async_session() as db` 都开新会话；
    测试里需要读写同一 in-memory DB，故让其返回同一 session 的 CM。
    """
    class _CM:
        async def __aenter__(self):
            return shared_session

        async def __aexit__(self, *args):
            return False

    return lambda: _CM()
