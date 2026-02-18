"""Tests for app.utils.deduplicator — SimHash + SequenceMatcher dedup."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from app.utils.deduplicator import NewsDeduplicator


@dataclass
class FakeNewsItem:
    """Minimal news item for dedup tests."""
    title: str
    source: str
    url: str = ""
    content: str = ""


class TestNewsDeduplicator:
    """Test the two-layer deduplication logic."""

    @pytest.fixture
    def dedup(self):
        return NewsDeduplicator()

    @patch("app.utils.deduplicator.get_redis")
    async def test_exact_duplicate_removed(self, mock_get_redis, dedup):
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        mock_get_redis.return_value = mock_redis

        await dedup.load_index()

        items = [
            FakeNewsItem(title="英伟达发布最新GPU芯片", source="财联社"),
            FakeNewsItem(title="英伟达发布最新GPU芯片", source="东方财富"),
        ]
        unique = await dedup.deduplicate(items)
        # 财联社 priority higher, should keep it and drop 东方财富
        assert len(unique) == 1
        assert unique[0].source == "财联社"

    @patch("app.utils.deduplicator.get_redis")
    async def test_similar_titles_deduped(self, mock_get_redis, dedup):
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}
        mock_get_redis.return_value = mock_redis

        await dedup.load_index()

        items = [
            FakeNewsItem(title="特斯拉第三季度营收超预期达到251亿美元", source="财联社"),
            FakeNewsItem(title="特斯拉第三季度营收超预期，达到251亿美元", source="新浪财经"),
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
            FakeNewsItem(title="英伟达发布最新GPU芯片", source="财联社"),
            FakeNewsItem(title="美联储宣布加息25个基点", source="东方财富"),
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
            FakeNewsItem(title="比亚迪新能源销量创新高", source="同花顺"),  # priority 10
            FakeNewsItem(title="比亚迪新能源销量创新高", source="华尔街见闻"),  # priority 2
        ]
        unique = await dedup.deduplicate(items)
        assert len(unique) == 1
        assert unique[0].source == "华尔街见闻"

    def test_hamming_distance(self, dedup):
        assert dedup._hamming(0b1100, 0b1010) == 2
        assert dedup._hamming(0, 0) == 0
        assert dedup._hamming(0xFF, 0x00) == 8

    def test_clean_title(self, dedup):
        # 【快讯】 is a bracket block — entirely removed by _BRACKET_RE
        assert dedup._clean("【快讯】测试标题！") == "测试标题"
        assert dedup._clean("[Breaking] Test") == "Test"
