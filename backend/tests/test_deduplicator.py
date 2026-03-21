"""Tests for app.utils.deduplicator — 长短文本路由去重。"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from app.utils.deduplicator import (
    NewsDeduplicator,
    _cosine_sim,
    SHORT_TEXT_LENGTH_THRESHOLD,
)


@dataclass
class FakeNewsItem:
    """Minimal news item for dedup tests."""
    title: str
    source: str
    url: str = ""
    content: str = ""


class TestNewsDeduplicator:
    """Test the multi-channel deduplication logic."""

    @pytest.fixture
    def dedup(self):
        return NewsDeduplicator()

    # ────────────────────────────────────────────
    # 长文本通道测试（原有逻辑）
    # ────────────────────────────────────────────

    @patch("app.utils.deduplicator.get_redis")
    async def test_exact_duplicate_removed(self, mock_get_redis, dedup):
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        mock_get_redis.return_value = mock_redis

        await dedup.load_index()

        items = [
            FakeNewsItem(title="英伟达发布最新GPU芯片", source="财联社",
                         content="英伟达今天发布了最新一代GPU芯片，性能较上一代提升了50%以上。该芯片采用最新的制程工艺，功耗大幅降低，适用于数据中心和AI训练场景。业内人士表示，这将进一步巩固英伟达在AI芯片市场的领导地位。"),
            FakeNewsItem(title="英伟达发布最新GPU芯片", source="东方财富",
                         content="英伟达今天发布了最新一代GPU芯片，性能较上一代提升了50%以上。该芯片采用最新的制程工艺，功耗大幅降低，适用于数据中心和AI训练场景。业内人士表示，这将进一步巩固英伟达在AI芯片市场的领导地位。"),
        ]
        unique = await dedup.deduplicate(items)
        assert len(unique) == 1
        assert unique[0].source == "财联社"

    @patch("app.utils.deduplicator.get_redis")
    async def test_similar_titles_deduped(self, mock_get_redis, dedup):
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        mock_get_redis.return_value = mock_redis

        await dedup.load_index()

        items = [
            FakeNewsItem(title="特斯拉第三季度营收超预期达到251亿美元", source="财联社",
                         content="特斯拉公布第三季度财报，营收达到251亿美元，超出市场预期。公司表示，Model Y和Model 3的交付量创下新纪录，全球销量持续增长。分析师认为，特斯拉的生产效率提升和新市场拓展是营收增长的关键。"),
            FakeNewsItem(title="特斯拉第三季度营收超预期，达到251亿美元", source="新浪财经",
                         content="特斯拉公布第三季度财报，营收达到251亿美元，超出市场预期。公司表示，Model Y和Model 3的交付量创下新纪录，全球销量持续增长。分析师认为，特斯拉的生产效率提升和新市场拓展是营收增长的关键。"),
        ]
        unique = await dedup.deduplicate(items)
        assert len(unique) == 1

    @patch("app.utils.deduplicator.get_redis")
    async def test_different_titles_kept(self, mock_get_redis, dedup):
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        mock_get_redis.return_value = mock_redis

        await dedup.load_index()

        items = [
            FakeNewsItem(title="英伟达发布最新GPU芯片", source="财联社",
                         content="英伟达今天发布了最新一代GPU芯片，性能较上一代提升了50%以上，适用于数据中心和AI训练场景。业内人士表示，这将进一步巩固英伟达在AI芯片市场的领导地位，推动行业技术革新。"),
            FakeNewsItem(title="美联储宣布加息25个基点", source="东方财富",
                         content="美联储今日宣布加息25个基点，将联邦基金利率目标区间上调至5.25%-5.50%。这是美联储今年以来的第三次加息，符合市场预期。美联储主席鲍威尔表示，未来政策将取决于经济数据表现。"),
        ]
        unique = await dedup.deduplicate(items)
        assert len(unique) == 2

    @patch("app.utils.deduplicator.get_redis")
    async def test_empty_list(self, mock_get_redis, dedup):
        unique = await dedup.deduplicate([])
        assert unique == []

    @patch("app.utils.deduplicator.get_redis")
    async def test_source_priority_keeps_higher(self, mock_get_redis, dedup):
        """Higher priority source (lower number) should be kept."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        mock_get_redis.return_value = mock_redis

        await dedup.load_index()

        items = [
            FakeNewsItem(title="比亚迪新能源销量创新高", source="同花顺",
                         content="比亚迪今日公布最新销量数据，新能源汽车销量再创历史新高。公司表示，旗下多款车型持续热销，尤其是海洋系列和王朝系列表现强劲。业内分析认为，比亚迪在技术和成本控制方面的优势将持续推动其市场份额增长。"),
            FakeNewsItem(title="比亚迪新能源销量创新高", source="华尔街见闻",
                         content="比亚迪今日公布最新销量数据，新能源汽车销量再创历史新高。公司表示，旗下多款车型持续热销，尤其是海洋系列和王朝系列表现强劲。业内分析认为，比亚迪在技术和成本控制方面的优势将持续推动其市场份额增长。"),
        ]
        unique = await dedup.deduplicate(items)
        assert len(unique) == 1
        assert unique[0].source == "华尔街见闻"

    def test_hamming_distance(self, dedup):
        assert dedup._hamming(0b1100, 0b1010) == 2
        assert dedup._hamming(0, 0) == 0
        assert dedup._hamming(0xFF, 0x00) == 8

    def test_clean_title(self, dedup):
        assert dedup._clean("【快讯】测试标题！") == "测试标题"
        assert dedup._clean("[Breaking] Test") == "Test"

    # ────────────────────────────────────────────
    # 文本路由测试
    # ────────────────────────────────────────────

    def test_routing_short_text(self, dedup):
        """≤150 字的文本应被路由到短文本通道。"""
        short = FakeNewsItem(title="美国12月新屋开工环比 6.2%，预期 1.1%。", source="财联社")
        text = dedup._get_clean_text(short)
        assert len(text) <= SHORT_TEXT_LENGTH_THRESHOLD

    def test_routing_long_text(self, dedup):
        """>150 字的文本应被路由到长文本通道。"""
        long_item = FakeNewsItem(
            title="英伟达发布最新GPU芯片",
            source="财联社",
            content="英伟达今天发布了最新一代GPU芯片，性能较上一代提升了50%以上。" * 10,
        )
        text = dedup._get_clean_text(long_item)
        assert len(text) > SHORT_TEXT_LENGTH_THRESHOLD

    # ────────────────────────────────────────────
    # 数值抗误杀测试
    # ────────────────────────────────────────────

    def test_extract_numbers_percentage(self, dedup):
        nums = dedup._extract_numbers("美国12月新屋开工环比 6.2%，预期 1.1%。")
        assert "6.2%" in nums
        assert "1.1%" in nums

    def test_extract_numbers_unit(self, dedup):
        nums = dedup._extract_numbers("新屋开工 140.4万户，预期 130.4万户。")
        assert "140.4万户" in nums
        assert "130.4万户" in nums

    def test_extract_numbers_excludes_dates(self, dedup):
        nums = dedup._extract_numbers("财联社2月18日电")
        assert len(nums) == 0

    def test_number_safeguard_different_numbers_kept(self, dedup):
        """不同数值的短讯应该被保留（不误杀）。"""
        a = FakeNewsItem(title="美国12月新屋开工环比 6.2%，预期 1.1%。", source="财联社")
        b = FakeNewsItem(title="美国12月新屋开工 140.4万户，预期 130.4万户。", source="华尔街见闻")
        # 模拟高相似度灰色地带
        is_dup = dedup._number_safeguard(
            "美国12月新屋开工环比6.2%预期1.1%",
            "美国12月新屋开工140.4万户预期130.4万户",
            0.82, a, b,
        )
        assert is_dup is False  # 数值不同，应保留

    # ────────────────────────────────────────────
    # 短文本降级测试
    # ────────────────────────────────────────────

    @patch("app.utils.deduplicator.get_redis")
    @patch("app.utils.deduplicator._call_embedding", return_value=None)
    async def test_short_text_fallback_when_api_fails(
        self, mock_embedding, mock_get_redis, dedup
    ):
        """Embedding API 失败时，短文本应降级到 SequenceMatcher。"""
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        mock_get_redis.return_value = mock_redis

        await dedup.load_index()

        items = [
            FakeNewsItem(title="美国12月新屋开工环比 6.2%", source="财联社"),
            FakeNewsItem(title="美国12月新屋开工环比 6.2%", source="东方财富"),
        ]
        unique = await dedup.deduplicate(items)
        # 完全相同标题应被去重（即使 API 失败）
        assert len(unique) == 1

    # ────────────────────────────────────────────
    # 余弦相似度工具函数测试
    # ────────────────────────────────────────────

    def test_cosine_sim_identical(self):
        assert _cosine_sim([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_cosine_sim_orthogonal(self):
        assert _cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_cosine_sim_opposite(self):
        assert _cosine_sim([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
