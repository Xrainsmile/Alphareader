"""新闻预筛模块测试。

覆盖：
  1. 内容完整性 / 低价值模式拦截
  2. 硬信息信号评分
  3. 权威 / 重大事件兜底强制送评
  4. 信源分级（A/B/C/D）
  5. prefilter_score 加权
  6. 同事件新事实检测（needs_individual_scoring）
  7. compute_source_quality 统计
  8. 编排 prefilter_news：影子模式 / 正常模式 / 事件继承
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config import settings
from app.models.news import News
from app.services import prefilter as pf


def _now():
    return datetime.now(timezone.utc)


def make_item(title, content="", source="CNBC", url="https://x.com/1", related_to_url=None):
    return SimpleNamespace(
        title=title, content=content, source=source, url=url, related_to_url=related_to_url
    )


# ───────────────────────── 1. 内容完整性 ─────────────────────────

class TestMinimumInformation:
    def test_short_title_empty_content_dropped(self):
        it = make_item("突发", content="")
        assert pf.has_minimum_information(it) is False

    def test_normal_passes(self):
        it = make_item("美联储维持利率不变", content="美联储今日宣布维持联邦基金利率不变。")
        assert pf.has_minimum_information(it) is True

    def test_low_value_pattern_dropped(self):
        it = make_item("本周精选：报名开启免费课程", content="欢迎报名")
        assert pf.has_minimum_information(it) is False

    def test_title_equals_content_dropped(self):
        it = make_item("公司A发布财报", content="公司A发布财报")
        assert pf.has_minimum_information(it) is False


# ───────────────────────── 2. 硬信息信号 ─────────────────────────

class TestHardSignalScore:
    def test_rich_news(self):
        it = make_item("公司X发布Q2财报，营收增长20%", content="公司X宣布上调全年指引")
        score = pf.hard_signal_score(it)
        # 实体 + 数字 + 动作 + 政策/公告
        assert score >= 4

    def test_empty(self):
        assert pf.hard_signal_score(make_item("", "")) == 0


# ───────────────────────── 3. 兜底强制送评 ─────────────────────────

class TestOverrides:
    def test_official_source_by_name(self):
        assert pf.is_official_source("美联储", "") is True

    def test_official_source_by_domain(self):
        assert pf.is_official_source("某站", "https://www.sec.gov/filing") is True

    def test_major_event_signal(self):
        assert pf.contains_major_event_signal("公司宣布重大并购交易") is True
        assert pf.contains_major_event_signal("市场情绪乐观") is False


# ───────────────────────── 4. 信源分级 ─────────────────────────

class TestClassifySource:
    def test_official_always_a(self):
        assert pf.classify_source(None, "美联储", "") == "A"

    def test_none_quality_is_b(self):
        assert pf.classify_source(None, "Unknown", "") == "B"

    def test_low_display_rate_many_samples_is_d(self):
        q = pf.SourceQuality(source="spam", sample_count=300, display_pass_rate=0.01)
        assert pf.classify_source(q, "spam", "") == "D"

    def test_mid_display_rate_is_c(self):
        q = pf.SourceQuality(source="x", sample_count=50, display_pass_rate=0.05)
        assert pf.classify_source(q, "x", "") == "C"

    def test_high_display_rate_is_a(self):
        q = pf.SourceQuality(source="y", sample_count=50, display_pass_rate=0.5)
        assert pf.classify_source(q, "y", "") == "A"


# ───────────────────────── 5. prefilter_score ─────────────────────────

class TestPrefilterScore:
    def test_promo_without_facts_low(self):
        it = make_item("限时优惠立即下载", content="免费领取扫码关注")
        score = pf.compute_prefilter_score(it, None, "B")
        assert score <= 1

    def test_rich_finance_high(self):
        it = make_item("英伟达Q2营收增长122%并上调指引", content="公司宣布回购计划")
        score = pf.compute_prefilter_score(it, None, "A")
        assert score >= 5


# ───────────────────────── 6. 同事件新事实检测 ─────────────────────────

class TestEventCompression:
    def test_same_event_no_new_fact(self):
        root = {"title": "美联储维持利率不变", "content": "美联储宣布维持联邦基金利率不变"}
        it = make_item("美联储维持利率不变", content="美联储宣布维持联邦基金利率不变，符合预期")
        need, sim = pf.needs_individual_scoring(it, root)
        assert need is False
        assert sim >= 0.85

    def test_new_number_needs_scoring(self):
        root = {"title": "美联储维持利率不变", "content": "美联储宣布维持联邦基金利率不变"}
        it = make_item("美联储维持利率不变", content="美联储宣布维持联邦基金利率在5.25%不变")
        need, _ = pf.needs_individual_scoring(it, root)
        assert need is True

    def test_new_entity_needs_scoring(self):
        root = {"title": "公司A发布财报", "content": "公司A营收增长"}
        it = make_item("公司A发布财报", content="公司A营收增长，公司B参与合作")
        need, _ = pf.needs_individual_scoring(it, root)
        assert need is True

    def test_title_dissimilar_needs_scoring(self):
        root = {"title": "美联储维持利率不变", "content": "xxx"}
        it = make_item("苹果发布新款iPhone", content="yyy")
        need, sim = pf.needs_individual_scoring(it, root)
        assert need is True
        assert sim < 0.85


# ───────────────────────── 7. 信源质量统计 ─────────────────────────

class TestSourceQuality:
    @pytest.mark.asyncio
    async def test_aggregates_rates(self, db_session):
        base = _now() - timedelta(hours=1)
        scores = [9, 8, 7, 5, 3, 2]
        rows = [
            News(id=uuid.uuid4(), title=f"t{i}", source="Bloomberg",
                 url=f"https://b.com/{i}", ai_score=scores[i],
                 is_highlight=(i == 0), published_at=base,
                 content_hash="x", simhash_fingerprint=1)
            for i in range(6)
        ]
        for r in rows:
            db_session.add(r)
        await db_session.commit()

        quality = await pf.compute_source_quality(db_session)
        q = quality["Bloomberg"]
        assert q.sample_count == 6
        assert q.score_pass_rate == pytest.approx(4 / 6)   # 9,8,7,5 >=5
        assert q.display_pass_rate == pytest.approx(3 / 6)  # 9,8,7 >=6
        assert q.highlight_rate == pytest.approx(1 / 6)


# ───────────────────────── 8. 编排 prefilter_news ─────────────────────────

@pytest.fixture
async def seeded_root(db_session):
    root = News(
        id=uuid.uuid4(), title="美联储维持利率不变",
        source="Reuters", url="https://root.com/r",
        content="美联储宣布维持联邦基金利率不变",
        ai_score=8, published_at=_now(),
        content_hash="r", simhash_fingerprint=2,
    )
    db_session.add(root)
    await db_session.commit()
    return root


class TestPrefilterOrchestration:
    @pytest.mark.asyncio
    async def test_shadow_mode_keeps_all(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "PREFILTER_SHADOW_MODE", True)
        items = [
            make_item("报名开启免费课程", content="欢迎报名", url="https://x.com/drop"),
            make_item("英伟达Q2营收增长122%", content="公司宣布回购", url="https://x.com/keep"),
        ]
        result = await pf.prefilter_news(items, session=db_session, source_quality={}, shadow=True)
        assert len(result.kept) == 2  # 影子模式全部送评
        # 决策里记录了本应 drop 的项
        drop_decisions = [d for d in result.decisions.values() if d.shadow_action == "drop"]
        assert drop_decisions

    @pytest.mark.asyncio
    async def test_live_mode_drops_low_value(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "PREFILTER_SHADOW_MODE", False)
        monkeypatch.setattr(settings, "PREFILTER_AUDIT_SAMPLE_RATE", 0.0)
        items = [
            make_item("报名开启免费课程", content="欢迎报名", url="https://x.com/drop"),
            make_item("英伟达Q2营收增长122%", content="公司宣布回购", url="https://x.com/keep"),
        ]
        result = await pf.prefilter_news(items, session=db_session, source_quality={}, shadow=False)
        assert "https://x.com/drop" in result.dropped_urls
        assert "https://x.com/keep" in [i.url for i in result.kept]

    @pytest.mark.asyncio
    async def test_official_forced_score(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "PREFILTER_SHADOW_MODE", False)
        monkeypatch.setattr(settings, "PREFILTER_AUDIT_SAMPLE_RATE", 0.0)
        # 标题很短、正文空，但来源是官方 → 强制送评
        it = make_item("简报", content="", source="美联储", url="https://fed.gov/1")
        result = await pf.prefilter_news([it], session=db_session, source_quality={}, shadow=False)
        assert result.decisions[it.url].action == "score"
        assert "官方" in result.decisions[it.url].reason_string()

    @pytest.mark.asyncio
    async def test_event_inherit(self, db_session, seeded_root, monkeypatch):
        monkeypatch.setattr(settings, "PREFILTER_SHADOW_MODE", False)
        monkeypatch.setattr(settings, "PREFILTER_AUDIT_SAMPLE_RATE", 0.0)
        it = make_item(
            "美联储维持利率不变",
            content="美联储宣布维持联邦基金利率不变，符合预期",
            source="CNBC", url="https://x.com/follow",
            related_to_url="https://root.com/r",
        )
        result = await pf.prefilter_news([it], session=db_session, source_quality={}, shadow=False)
        assert len(result.inherited) == 1
        assert result.inherited[0].root_score == 8
        assert "https://x.com/follow" not in [i.url for i in result.kept]
