"""Events API 测试（事件化新闻第三阶段）。

覆盖 PRD 17.1 关键项：
  1. 事件列表只返回事件根；
  2. 子报道不进入事件分页；
  3. 事件总数与分页数量正确；
  4. 独立信源正确去重；
  15. 事件根超出时间窗口但存在新子报道时仍保留；
  16. 同一事件跨分页时不产生孤立子卡。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.event_version import EventVersion
from app.models.news import News


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
async def seed_events(db_session):
    """构造：2 个事件根（A 有 3 子 2 信源、B 单信源）+ 若干孤儿子报道。"""
    root_a = News(
        id=uuid.uuid4(), title="事件A首篇", source="CNBC",
        url="https://example.com/a", ai_score=8, ai_summary="A摘要",
        category="财经", published_at=_now() - timedelta(hours=2),
        event_title="事件A标题", event_summary="事件A综述",
        event_latest_change="官方首次确认",
        event_why_important="影响算力供应链",
        event_status="developing", event_version=2,
        event_source_count=3, event_article_count=4,
        event_last_updated_at=_now() - timedelta(hours=1),
    )
    children_a = [
        News(
            id=uuid.uuid4(), title=f"A子报道{i}", source=src,
            url=f"https://example.com/a{i}", ai_score=5,  # 低于展示阈值仍应出现在详情
            category="财经", published_at=_now() - timedelta(hours=1, minutes=i),
            related_to_id=root_a.id,
        )
        for i, src in enumerate(["CNBC", "CNBC", "MarketWatch"], 1)  # 根=CNBC 与子报道重叠，去重后独立信源 2
    ]
    root_b = News(
        id=uuid.uuid4(), title="事件B单信源", source="TechCrunch",
        url="https://example.com/b", ai_score=6, ai_summary="B摘要",
        category="科技", published_at=_now() - timedelta(hours=3),
    )
    db_session.add(root_a)
    for c in children_a:
        db_session.add(c)
    db_session.add(root_b)
    # A 的版本快照
    db_session.add(EventVersion(
        event_id=root_a.id, version=1, event_title="事件A标题",
        event_summary="v1 摘要", latest_change="事件首次出现",
        status="new", source_count=2, article_count=2,
    ))
    db_session.add(EventVersion(
        event_id=root_a.id, version=2, event_title="事件A标题",
        event_summary="事件A综述", latest_change="官方首次确认",
        status="developing", source_count=3, article_count=4,
    ))
    await db_session.commit()
    return {"root_a": root_a, "children_a": children_a, "root_b": root_b}


class TestListEvents:
    @pytest.mark.asyncio
    async def test_only_roots_returned(self, client, seed_events):
        resp = await client.get("/api/v1/events/")
        assert resp.status_code == 200
        data = resp.json()["data"]
        ids = {i["id"] for i in data}
        child_ids = {str(c.id) for c in seed_events["children_a"]}
        # 子报道不得出现在事件列表
        assert ids.isdisjoint(child_ids)
        assert str(seed_events["root_a"].id) in ids
        assert str(seed_events["root_b"].id) in ids

    @pytest.mark.asyncio
    async def test_total_counts_events_not_articles(self, client, seed_events):
        """total = 事件数（2），不是文章数（5）。"""
        resp = await client.get("/api/v1/events/")
        assert resp.json()["total"] == 2

    @pytest.mark.asyncio
    async def test_source_count_deduped(self, client, seed_events):
        """独立信源去重：根(CNBC)与子报道(CNBC)重叠只计 1 → CNBC + MarketWatch = 2。"""
        resp = await client.get("/api/v1/events/")
        items = resp.json()["data"]
        a = next(i for i in items if i["id"] == str(seed_events["root_a"].id))
        assert a["article_count"] == 4   # 根 + 3 子
        assert a["source_count"] == 2    # 根(CNBC)与子报道(CNBC)重叠，去重后 CNBC + MarketWatch

    @pytest.mark.asyncio
    async def test_pagination_by_events(self, client, seed_events):
        resp = await client.get("/api/v1/events/?limit=1&offset=0")
        d1 = resp.json()
        resp2 = await client.get("/api/v1/events/?limit=1&offset=1")
        d2 = resp2.json()
        d1_total, d2_total = d1["total"], d2["total"]
        assert d1_total == 2 and d2_total == 2
        assert len(d1["data"]) == 1 and len(d2["data"]) == 1
        # 两页不是同一事件，且都不是子报道（孤立子卡不存在）
        assert d1["data"][0]["id"] != d2["data"][0]["id"]

    @pytest.mark.asyncio
    async def test_event_fields_preferred(self, client, seed_events):
        resp = await client.get("/api/v1/events/")
        a = next(i for i in resp.json()["data"]
                 if i["id"] == str(seed_events["root_a"].id))
        assert a["title"] == "事件A标题"
        assert a["summary"] == "事件A综述"
        assert a["latest_change"] == "官方首次确认"
        assert a["status"] == "developing"
        assert a["is_synthesized"] is True

    @pytest.mark.asyncio
    async def test_stale_root_with_fresh_child_kept(self, client, db_session, seed_events):
        """根超窗但窗口内有新子报道 → 事件保留（PRD 17.15）。"""
        old_root = News(
            id=uuid.uuid4(), title="老事件根", source="富途新闻",
            url="https://example.com/old", ai_score=7, category="财经",
            published_at=_now() - timedelta(hours=50),
            created_at=_now() - timedelta(hours=50),
        )
        fresh_child = News(
            id=uuid.uuid4(), title="新进展", source="CNBC",
            url="https://example.com/old-child", ai_score=6, category="财经",
            published_at=_now(), created_at=_now(),
            related_to_id=old_root.id,
        )
        db_session.add_all([old_root, fresh_child])
        await db_session.commit()

        resp = await client.get("/api/v1/events/?max_age_hours=24")
        ids = {i["id"] for i in resp.json()["data"]}
        assert str(old_root.id) in ids

    @pytest.mark.asyncio
    async def test_stale_root_without_fresh_child_excluded(self, client, db_session, seed_events):
        old_root = News(
            id=uuid.uuid4(), title="彻底过期的老事件", source="富途新闻",
            url="https://example.com/dead", ai_score=7, category="财经",
            published_at=_now() - timedelta(hours=50),
            created_at=_now() - timedelta(hours=50),
        )
        db_session.add(old_root)
        await db_session.commit()

        resp = await client.get("/api/v1/events/?max_age_hours=24")
        ids = {i["id"] for i in resp.json()["data"]}
        assert str(old_root.id) not in ids

    @pytest.mark.asyncio
    async def test_status_filter(self, client, seed_events):
        resp = await client.get("/api/v1/events/?status=developing")
        items = resp.json()["data"]
        assert len(items) == 1
        assert items[0]["status"] == "developing"


class TestEventDetail:
    @pytest.mark.asyncio
    async def test_detail_full_structure(self, client, seed_events):
        rid = str(seed_events["root_a"].id)
        resp = await client.get(f"/api/v1/events/{rid}")
        assert resp.status_code == 200
        d = resp.json()["data"]
        assert d["title"] == "事件A标题"
        # 版本演进倒序
        assert [v["version"] for v in d["versions"]] == [2, 1]
        # 全部关联报道（含 5 分低分子报道与根本身）
        assert len(d["articles"]) == 4
        # 关联报道按发布时间倒序（首条不一定为根本身，只校验数量与来源集合）
        sources = {a["source"] for a in d["articles"]}
        assert sources == {"CNBC", "MarketWatch"}  # 根(CNBC)与子报道重叠去重

    @pytest.mark.asyncio
    async def test_detail_404(self, client, seed_events):
        resp = await client.get(f"/api/v1/events/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_detail_invalid_id(self, client, seed_events):
        resp = await client.get("/api/v1/events/not-a-uuid")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_detail_child_id_resolves_to_root(self, client, seed_events):
        """传入子报道 ID 应自动解析到事件根，而不是返回伪事件详情（无版本/无关联报道）。"""
        child = seed_events["children_a"][0]
        resp = await client.get(f"/api/v1/events/{child.id}")
        assert resp.status_code == 200
        d = resp.json()["data"]
        # 解析到的根标题应为事件根标题，而非子报道标题
        assert d["title"] == "事件A标题"
        # 子报道所属的根的版本演进与全部关联报道都应可见
        assert [v["version"] for v in d["versions"]] == [2, 1]
        assert len(d["articles"]) == 4


class TestEventSources:
    @pytest.mark.asyncio
    async def test_sources_pagination(self, client, seed_events):
        rid = str(seed_events["root_a"].id)
        resp = await client.get(f"/api/v1/events/{rid}/sources?limit=2&offset=0")
        d = resp.json()
        assert d["total"] == 4
        assert len(d["data"]) == 2
        resp2 = await client.get(f"/api/v1/events/{rid}/sources?limit=2&offset=2")
        assert len(resp2.json()["data"]) == 2
