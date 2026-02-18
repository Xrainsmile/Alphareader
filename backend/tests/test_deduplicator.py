"""Tests for app.utils.deduplicator — 长短文本路由去重测试。"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.utils.deduplicator import NewsDeduplicator, _EmbeddingEntry


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
    # 长文本通道测试（原有逻辑保留）
    # ────────────────────────────────────────────

    @patch("app.utils.deduplicator.get_redis")
    async def test_exact_duplicate_removed(self, mock_get_redis, dedup):
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        mock_get_redis.return_value = mock_redis

        await dedup.load_index()

        items = [
            FakeNewsItem(title="英伟达发布最新GPU芯片", source="财联社",
                         content="这是一段很长的正文内容" * 20),
            FakeNewsItem(title="英伟达发布最新GPU芯片", source="东方财富",
                         content="这是一段很长的正文内容" * 20),
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
                         content="特斯拉公司周三公布了第三季度财报" * 20),
            FakeNewsItem(title="特斯拉第三季度营收超预期，达到251亿美元", source="新浪财经",
                         content="特斯拉公司周三公布了第三季度财报" * 20),
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
                         content="英伟达发布了全新的GPU芯片" * 20),
            FakeNewsItem(title="美联储宣布加息25个基点", source="东方财富",
                         content="美联储在周三宣布加息25个基点" * 20),
        ]
        unique = await dedup.deduplicate(items)
        assert len(unique) == 2

    @patch("app.utils.deduplicator.get_redis")
    async def test_empty_list(self, mock_get_redis, dedup):
        unique = await dedup.deduplicate([])
        assert unique == []

    @patch("app.utils.deduplicator.get_redis")
    async def test_source_priority_keeps_higher(self, mock_get_redis, dedup):
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        mock_get_redis.return_value = mock_redis

        await dedup.load_index()

        items = [
            FakeNewsItem(title="比亚迪新能源销量创新高", source="同花顺",
                         content="比亚迪最新销量数据显示" * 20),
            FakeNewsItem(title="比亚迪新能源销量创新高", source="华尔街见闻",
                         content="比亚迪最新销量数据显示" * 20),
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
    # 短文本通道测试（新增）
    # ────────────────────────────────────────────

    def test_extract_numbers(self, dedup):
        """测试金融数值提取。"""
        # 百分比
        nums = dedup._extract_numbers("美国12月新屋开工环比 6.2%，预期 1.1%。")
        assert "6.2%" in nums
        assert "1.1%" in nums
        # 不应包含日期"12"
        assert "12" not in nums

        # 万户
        nums2 = dedup._extract_numbers("美国12月新屋开工 140.4万户，预期 130.4万户。")
        assert "140.4万户" in nums2
        assert "130.4万户" in nums2

        # 混合
        nums3 = dedup._extract_numbers("财联社2月18日电，美国12月营建许可总数录得144.8万户")
        assert "144.8万户" in nums3

    def test_extract_numbers_no_date(self, dedup):
        """日期数字不应被提取。"""
        nums = dedup._extract_numbers("财联社2月18日电，沪指涨0.5%")
        assert "0.5%" in nums
        # "2" 和 "18" 不应出现
        assert all("2" != n and "18" != n for n in nums)

    @patch("app.utils.deduplicator.get_embedding_model")
    async def test_short_text_fallback_dedup(self, mock_get_emb, dedup):
        """Embedding 不可用时，短文本应走 SequenceMatcher 降级通道。"""
        mock_model = MagicMock()
        mock_model.available = False
        mock_get_emb.return_value = mock_model

        items = [
            FakeNewsItem(title="美国12月新屋开工环比6.2%预期1.1%", source="财联社"),
            FakeNewsItem(title="美国12月新屋开工环比6.2%预期1.1%", source="东方财富"),
        ]
        unique, dropped = dedup._dedup_short_text(items)
        assert len(unique) == 1
        assert unique[0].source == "财联社"

    @patch("app.utils.deduplicator.get_embedding_model")
    async def test_short_text_number_safeguard_keeps_different_metrics(
        self, mock_get_emb, dedup
    ):
        """同一事件的不同指标（百分比 vs 万户）应被保留。"""
        mock_model = MagicMock()
        mock_model.available = False
        mock_get_emb.return_value = mock_model

        items = [
            FakeNewsItem(title="美国12月新屋开工环比6.2%预期1.1%", source="财联社"),
            FakeNewsItem(title="美国12月新屋开工140.4万户预期130.4万户", source="华尔街见闻"),
        ]
        unique, dropped = dedup._dedup_short_text(items)
        # 两条数值不同，应都保留
        assert len(unique) == 2

    def test_short_text_routing(self, dedup):
        """测试长短文本路由判定。"""
        short_item = FakeNewsItem(title="美国CPI同比3.2%", source="财联社")
        long_item = FakeNewsItem(
            title="英伟达发布最新GPU芯片", source="财联社",
            content="这是一段超过150字的正文内容" * 20,
        )
        assert len(dedup._get_clean_text(short_item)) <= 150
        assert len(dedup._get_clean_text(long_item)) > 150
