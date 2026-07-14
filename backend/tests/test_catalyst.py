"""Tests for catalyst module — model, aggregator service, API endpoints.

测试分层：
  1. Model: NewsCatalystStock ORM 读写
  2. Service: 纯函数（实体提取、聚合、热度计算、分类逻辑） + LLM mock
  3. API: 催化剂排行榜 / 单票检查 / 批量检查端点

注意：
  - catalyst API 端点直接使用 async_session()（不通过 FastAPI DI），
    因此需要 mock `app.api.v1.catalyst.async_session` 来注入测试 DB session。
  - LLM mock 需要正确设置 httpx.AsyncClient 的 async context manager。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.models.catalyst import NewsCatalystStock
from app.models.news import News
from app.models.screener import WatchlistDaily, TrendWatchlistDaily
from app.models.stock import StockRSRating


# ═══════════════════════════════════════════════════════════
#  1. Model Layer Tests
# ═══════════════════════════════════════════════════════════

class TestNewsCatalystStockModel:
    """测试 NewsCatalystStock ORM 模型的基础读写。"""

    async def test_create_and_read(self, db_session):
        """创建一条催化剂记录并读取验证字段完整性。"""
        record = NewsCatalystStock(
            catalyst_date=date(2026, 3, 22),
            ts_code="300750.SZ",
            name="宁德时代",
            news_count=3,
            top_score=9,
            avg_score=8.0,
            catalyst_types=["产品技术突破", "业绩财报"],
            catalyst_summary="宁德时代发布新一代电池技术",
            avg_sentiment=3.5,
            news_titles=["标题1", "标题2", "标题3"],
            in_vcp=True,
            vcp_score=0.85,
            in_trend=False,
            trend_score=None,
            rs_rating=92,
            heat_score=29.0,
            confirm_level="double_confirmed",
        )
        db_session.add(record)
        await db_session.commit()

        stmt = select(NewsCatalystStock).where(
            NewsCatalystStock.ts_code == "300750.SZ"
        )
        result = await db_session.execute(stmt)
        row = result.scalars().first()

        assert row is not None
        assert row.catalyst_date == date(2026, 3, 22)
        assert row.ts_code == "300750.SZ"
        assert row.name == "宁德时代"
        assert row.news_count == 3
        assert row.top_score == 9
        assert row.avg_score == 8.0
        assert row.in_vcp is True
        assert row.vcp_score == 0.85
        assert row.in_trend is False
        assert row.rs_rating == 92
        assert row.heat_score == 29.0
        assert row.confirm_level == "double_confirmed"

    async def test_default_values(self, db_session):
        """测试默认值：confirm_level=catalyst_only, in_vcp=False 等。"""
        record = NewsCatalystStock(
            catalyst_date=date(2026, 3, 22),
            ts_code="600519.SH",
            news_count=1,
            top_score=7,
            avg_score=7.0,
            heat_score=7.0,
        )
        db_session.add(record)
        await db_session.commit()

        stmt = select(NewsCatalystStock).where(
            NewsCatalystStock.ts_code == "600519.SH"
        )
        result = await db_session.execute(stmt)
        row = result.scalars().first()

        assert row.confirm_level == "catalyst_only"
        assert row.in_vcp is False
        assert row.in_trend is False
        assert row.name is None
        assert row.catalyst_types is None

    async def test_unique_constraint(self, db_session):
        """同一天同一只票不能插入两条（唯一约束）。"""
        r1 = NewsCatalystStock(
            catalyst_date=date(2026, 3, 22),
            ts_code="300750.SZ",
            news_count=1,
            top_score=7,
            avg_score=7.0,
            heat_score=7.0,
        )
        db_session.add(r1)
        await db_session.commit()

        r2 = NewsCatalystStock(
            catalyst_date=date(2026, 3, 22),
            ts_code="300750.SZ",
            news_count=2,
            top_score=8,
            avg_score=8.0,
            heat_score=16.0,
        )
        db_session.add(r2)
        # SQLite 下唯一约束会抛出 IntegrityError
        with pytest.raises(Exception):
            await db_session.commit()
        await db_session.rollback()

    async def test_multiple_dates(self, db_session):
        """同一只票不同日期可以各有一条记录。"""
        for d in [date(2026, 3, 21), date(2026, 3, 22)]:
            db_session.add(NewsCatalystStock(
                catalyst_date=d,
                ts_code="300750.SZ",
                news_count=1,
                top_score=7,
                avg_score=7.0,
                heat_score=7.0,
            ))
        await db_session.commit()

        stmt = select(NewsCatalystStock).where(
            NewsCatalystStock.ts_code == "300750.SZ"
        )
        result = await db_session.execute(stmt)
        rows = result.scalars().all()
        assert len(rows) == 2


# ═══════════════════════════════════════════════════════════
#  2. Service Layer Tests — 纯函数（无需 DB/网络）
# ═══════════════════════════════════════════════════════════

class TestEntityExtraction:
    """测试从新闻中提取公司名/实体名的逻辑。"""

    def test_extract_from_tags(self):
        from app.services.catalyst_aggregator import _extract_entities_from_news

        news_list = [
            {
                "title": "宁德时代发布新电池",
                "tags": ["宁德时代", "锂电池", "新能源"],
                "sentiment_entity": "",
            },
        ]
        entities = _extract_entities_from_news(news_list)
        assert "宁德时代" in entities
        assert "锂电池" in entities
        assert "新能源" in entities

    def test_extract_from_sentiment_entity(self):
        from app.services.catalyst_aggregator import _extract_entities_from_news

        news_list = [
            {
                "title": "贵州茅台业绩超预期",
                "tags": [],
                "sentiment_entity": "贵州茅台",
            },
        ]
        entities = _extract_entities_from_news(news_list)
        assert "贵州茅台" in entities

    def test_exclude_known_keywords(self):
        from app.services.catalyst_aggregator import _extract_entities_from_news

        news_list = [
            {
                "title": "A股大盘走势",
                "tags": ["A股", "大盘", "涨停", "证监会", "宁德时代"],
                "sentiment_entity": "央行",
            },
        ]
        entities = _extract_entities_from_news(news_list)
        # A股/大盘/涨停/证监会/央行 应被排除
        assert "A股" not in entities
        assert "大盘" not in entities
        assert "涨停" not in entities
        assert "证监会" not in entities
        assert "央行" not in entities
        # 宁德时代应保留
        assert "宁德时代" in entities

    def test_deduplicate_entities(self):
        from app.services.catalyst_aggregator import _extract_entities_from_news

        news_list = [
            {"title": "n1", "tags": ["宁德时代", "比亚迪"], "sentiment_entity": "宁德时代"},
            {"title": "n2", "tags": ["宁德时代"], "sentiment_entity": ""},
        ]
        entities = _extract_entities_from_news(news_list)
        # "宁德时代" 应只出现一次
        assert entities.count("宁德时代") == 1

    def test_filter_short_ascii_tags(self):
        """短 ASCII 标签（如 "AI", "US"）应被过滤。"""
        from app.services.catalyst_aggregator import _extract_entities_from_news

        news_list = [
            {"title": "t1", "tags": ["AI", "US", "NVIDIA", "宁德时代"], "sentiment_entity": ""},
        ]
        entities = _extract_entities_from_news(news_list)
        assert "AI" not in entities
        assert "US" not in entities
        # 长 ASCII 应保留
        assert "NVIDIA" in entities
        assert "宁德时代" in entities

    def test_filter_digits_and_short(self):
        """纯数字和太短（<2字符）的标签应被过滤。"""
        from app.services.catalyst_aggregator import _extract_entities_from_news

        news_list = [
            {"title": "t1", "tags": ["1", "12345", "宁", "宁德时代"], "sentiment_entity": ""},
        ]
        entities = _extract_entities_from_news(news_list)
        assert "1" not in entities
        assert "12345" not in entities
        assert "宁" not in entities
        assert "宁德时代" in entities

    def test_empty_news_list(self):
        from app.services.catalyst_aggregator import _extract_entities_from_news
        assert _extract_entities_from_news([]) == []


class TestAggregateByTicker:
    """测试按 ts_code 聚合催化剂信息的逻辑。"""

    def test_basic_aggregation(self):
        from app.services.catalyst_aggregator import _aggregate_by_ticker

        news_list = [
            {
                "title": "宁德时代Q1净利大增",
                "ai_score": 9,
                "tags": ["宁德时代"],
                "sentiment_entity": "",
                "catalyst_type": "业绩财报",
                "sentiment_score": 4,
            },
            {
                "title": "宁德时代发布新电池",
                "ai_score": 8,
                "tags": ["宁德时代"],
                "sentiment_entity": "",
                "catalyst_type": "产品技术突破",
                "sentiment_score": 3,
            },
        ]
        entity_map = {"宁德时代": "300750.SZ"}

        result = _aggregate_by_ticker(news_list, entity_map)

        assert "300750.SZ" in result
        agg = result["300750.SZ"]
        assert agg["news_count"] == 2
        assert agg["top_score"] == 9
        assert agg["total_score"] == 17  # 9 + 8
        assert "业绩财报" in agg["catalyst_types"]
        assert "产品技术突破" in agg["catalyst_types"]
        assert len(agg["titles"]) == 2
        assert len(agg["sentiments"]) == 2

    def test_multiple_tickers(self):
        from app.services.catalyst_aggregator import _aggregate_by_ticker

        news_list = [
            {"title": "n1", "ai_score": 9, "tags": ["宁德时代"], "sentiment_entity": "", "catalyst_type": "业绩", "sentiment_score": 3},
            {"title": "n2", "ai_score": 7, "tags": ["比亚迪"], "sentiment_entity": "", "catalyst_type": "产品", "sentiment_score": 2},
        ]
        entity_map = {"宁德时代": "300750.SZ", "比亚迪": "002594.SZ"}

        result = _aggregate_by_ticker(news_list, entity_map)
        assert "300750.SZ" in result
        assert "002594.SZ" in result
        assert result["300750.SZ"]["news_count"] == 1
        assert result["002594.SZ"]["news_count"] == 1

    def test_unmapped_entities_ignored(self):
        from app.services.catalyst_aggregator import _aggregate_by_ticker

        news_list = [
            {"title": "n1", "ai_score": 8, "tags": ["某非上市公司"], "sentiment_entity": "", "catalyst_type": "", "sentiment_score": None},
        ]
        entity_map = {"某非上市公司": None}

        result = _aggregate_by_ticker(news_list, entity_map)
        assert len(result) == 0

    def test_direct_ts_code_in_tags(self):
        """tags 中直接包含 ts_code 格式的标签也应被匹配。"""
        from app.services.catalyst_aggregator import _aggregate_by_ticker

        news_list = [
            {"title": "n1", "ai_score": 8, "tags": ["300750.SZ"], "sentiment_entity": "", "catalyst_type": "", "sentiment_score": None},
        ]
        entity_map = {}

        result = _aggregate_by_ticker(news_list, entity_map)
        assert "300750.SZ" in result

    def test_empty_inputs(self):
        from app.services.catalyst_aggregator import _aggregate_by_ticker
        assert _aggregate_by_ticker([], {}) == {}


class TestHeatScoreComputation:
    """测试催化剂热度评分计算。"""

    def test_basic_heat(self):
        from app.services.catalyst_aggregator import _compute_heat_score
        # 3 × 9 = 27, sentiment_bonus = 3.5 * 2 = 7.0, total = 34.0
        assert _compute_heat_score(3, 9, 3.5) == 34.0

    def test_zero_sentiment(self):
        from app.services.catalyst_aggregator import _compute_heat_score
        assert _compute_heat_score(2, 7, 0) == 14.0

    def test_negative_sentiment(self):
        from app.services.catalyst_aggregator import _compute_heat_score
        # 负面情绪不加分
        assert _compute_heat_score(2, 7, -2.0) == 14.0

    def test_single_news(self):
        from app.services.catalyst_aggregator import _compute_heat_score
        assert _compute_heat_score(1, 7, 0) == 7.0


class TestConfirmLevel:
    """测试交叉验证分类逻辑。"""

    def test_double_confirmed_vcp(self):
        from app.services.catalyst_aggregator import _determine_confirm_level
        assert _determine_confirm_level(in_vcp=True, in_trend=False, rs_rating=50) == "double_confirmed"

    def test_double_confirmed_trend(self):
        from app.services.catalyst_aggregator import _determine_confirm_level
        assert _determine_confirm_level(in_vcp=False, in_trend=True, rs_rating=50) == "double_confirmed"

    def test_double_confirmed_both(self):
        from app.services.catalyst_aggregator import _determine_confirm_level
        assert _determine_confirm_level(in_vcp=True, in_trend=True, rs_rating=95) == "double_confirmed"

    def test_strong_rs(self):
        from app.services.catalyst_aggregator import _determine_confirm_level
        assert _determine_confirm_level(in_vcp=False, in_trend=False, rs_rating=85) == "strong_rs"

    def test_strong_rs_boundary(self):
        from app.services.catalyst_aggregator import _determine_confirm_level
        assert _determine_confirm_level(in_vcp=False, in_trend=False, rs_rating=80) == "strong_rs"

    def test_catalyst_only_low_rs(self):
        from app.services.catalyst_aggregator import _determine_confirm_level
        assert _determine_confirm_level(in_vcp=False, in_trend=False, rs_rating=79) == "catalyst_only"

    def test_catalyst_only_no_rs(self):
        from app.services.catalyst_aggregator import _determine_confirm_level
        assert _determine_confirm_level(in_vcp=False, in_trend=False, rs_rating=None) == "catalyst_only"


# ═══════════════════════════════════════════════════════════
#  3. Service Layer Tests — LLM Mapping (Mocked)
# ═══════════════════════════════════════════════════════════

class TestTickerMappingLLM:
    """测试 LLM 公司名 → ts_code 映射（mock HTTP 调用）。"""

    @pytest.mark.parametrize("api_key,expected_empty", [
        ("", True),   # 无 API Key → 返回空
    ])
    async def test_no_api_key_returns_empty(self, api_key, expected_empty):
        from app.services.catalyst_aggregator import _map_entities_to_tickers
        from app.config import settings

        original = settings.LLM_API_KEY
        settings.LLM_API_KEY = api_key
        try:
            result = await _map_entities_to_tickers(["宁德时代", "比亚迪"])
            if expected_empty:
                assert result == {}
        finally:
            settings.LLM_API_KEY = original

    async def test_empty_entities(self):
        from app.services.catalyst_aggregator import _map_entities_to_tickers
        result = await _map_entities_to_tickers([])
        assert result == {}

    async def test_successful_mapping(self):
        """Mock LLM 返回正确 JSON，验证映射结果。"""
        from app.services.catalyst_aggregator import _call_ticker_mapping_llm
        from app.config import settings

        original_key = settings.LLM_API_KEY
        settings.LLM_API_KEY = "test-key"

        mock_response_data = {
            "choices": [{
                "message": {
                    "content": '{"宁德时代": "300750.SZ", "比亚迪": "002594.SZ", "某非上市": null}'
                }
            }]
        }

        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response_data
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)

            with patch("app.services.catalyst_aggregator.httpx.AsyncClient") as MockClientCls:
                @asynccontextmanager
                async def _fake_client(*a, **kw):
                    yield mock_client
                MockClientCls.return_value = _fake_client()

                result = await _call_ticker_mapping_llm(["宁德时代", "比亚迪", "某非上市"])

            assert result["宁德时代"] == "300750.SZ"
            assert result["比亚迪"] == "002594.SZ"
            assert result["某非上市"] is None
        finally:
            settings.LLM_API_KEY = original_key

    async def test_pure_digits_auto_suffix(self):
        """LLM 返回纯 6 位数字代码时，自动补全后缀。"""
        from app.services.catalyst_aggregator import _call_ticker_mapping_llm
        from app.config import settings

        original_key = settings.LLM_API_KEY
        settings.LLM_API_KEY = "test-key"

        mock_response_data = {
            "choices": [{
                "message": {
                    "content": '{"茅台": "600519", "宁德": "300750"}'
                }
            }]
        }

        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response_data
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)

            with patch("app.services.catalyst_aggregator.httpx.AsyncClient") as MockClientCls:
                @asynccontextmanager
                async def _fake_client(*a, **kw):
                    yield mock_client
                MockClientCls.return_value = _fake_client()

                result = await _call_ticker_mapping_llm(["茅台", "宁德"])

            assert result["茅台"] == "600519.SH"  # 6开头 → SH
            assert result["宁德"] == "300750.SZ"  # 3开头 → SZ
        finally:
            settings.LLM_API_KEY = original_key

    async def test_llm_returns_with_think_tags(self):
        """LLM 返回的 JSON 被 <think> 标签包裹时仍能正确解析。"""
        from app.services.catalyst_aggregator import _call_ticker_mapping_llm
        from app.config import settings

        original_key = settings.LLM_API_KEY
        settings.LLM_API_KEY = "test-key"

        mock_response_data = {
            "choices": [{
                "message": {
                    "content": '<think>让我想想这些公司...</think>\n```json\n{"宁德时代": "300750.SZ"}\n```'
                }
            }]
        }

        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response_data
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)

            with patch("app.services.catalyst_aggregator.httpx.AsyncClient") as MockClientCls:
                @asynccontextmanager
                async def _fake_client(*a, **kw):
                    yield mock_client
                MockClientCls.return_value = _fake_client()

                result = await _call_ticker_mapping_llm(["宁德时代"])

            assert result["宁德时代"] == "300750.SZ"
        finally:
            settings.LLM_API_KEY = original_key


# ═══════════════════════════════════════════════════════════
#  4. API Endpoint Tests
# ═══════════════════════════════════════════════════════════

class TestCatalystAPI:
    """测试催化剂 API 端点。

    注意：catalyst API 端点直接使用 `async_session()`（不走 FastAPI DI），
    所以需要 mock `app.api.v1.catalyst.async_session` 指向测试 DB。
    """

    @pytest.fixture
    async def seed_catalyst_data(self, db_session):
        """插入催化剂测试数据。"""
        records = [
            NewsCatalystStock(
                catalyst_date=date(2026, 3, 22),
                ts_code="300750.SZ",
                name="宁德时代",
                news_count=3,
                top_score=9,
                avg_score=8.3,
                catalyst_types=["业绩财报", "产品技术突破"],
                catalyst_summary="宁德时代发布新电池技术",
                avg_sentiment=3.5,
                news_titles=["标题1", "标题2", "标题3"],
                in_vcp=True,
                vcp_score=0.85,
                in_trend=False,
                rs_rating=92,
                heat_score=34.0,
                confirm_level="double_confirmed",
            ),
            NewsCatalystStock(
                catalyst_date=date(2026, 3, 22),
                ts_code="002594.SZ",
                name="比亚迪",
                news_count=2,
                top_score=8,
                avg_score=7.5,
                catalyst_types=["产品技术突破"],
                catalyst_summary="比亚迪新车发布",
                avg_sentiment=2.0,
                in_vcp=False,
                in_trend=True,
                trend_score=0.72,
                rs_rating=88,
                heat_score=20.0,
                confirm_level="double_confirmed",
            ),
            NewsCatalystStock(
                catalyst_date=date(2026, 3, 22),
                ts_code="600519.SH",
                name="贵州茅台",
                news_count=1,
                top_score=7,
                avg_score=7.0,
                catalyst_types=["业绩财报"],
                catalyst_summary="茅台Q1营收增长",
                avg_sentiment=1.5,
                in_vcp=False,
                in_trend=False,
                rs_rating=85,
                heat_score=10.0,
                confirm_level="strong_rs",
            ),
            NewsCatalystStock(
                catalyst_date=date(2026, 3, 22),
                ts_code="000001.SZ",
                name="平安银行",
                news_count=1,
                top_score=7,
                avg_score=7.0,
                catalyst_types=["行业政策"],
                catalyst_summary="银行业利好政策",
                avg_sentiment=1.0,
                in_vcp=False,
                in_trend=False,
                rs_rating=60,
                heat_score=9.0,
                confirm_level="catalyst_only",
            ),
        ]
        for r in records:
            db_session.add(r)
        await db_session.commit()
        return records

    @pytest.fixture
    def patch_catalyst_session(self, db_session):
        """Patch catalyst API 的 async_session 指向测试 DB。

        catalyst API 端点直接使用 async_session()（contextmanager），
        而不是 FastAPI DI 的 get_db。所以需要 mock 这个导入。
        """
        from tests.conftest import _TestSession
        return patch("app.api.v1.catalyst.async_session", _TestSession)

    async def test_get_catalyst_stocks_empty(self, client, patch_catalyst_session):
        """空数据库返回空列表。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/stocks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["count"] == 0
        assert data["data"]["items"] == []

    async def test_get_catalyst_stocks_all(self, client, seed_catalyst_data, patch_catalyst_session):
        """返回全部催化剂标的，按热度降序。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/stocks")
        assert resp.status_code == 200
        data = resp.json()["data"]

        assert data["count"] == 4
        assert data["date"] == "2026-03-22"

        # 验证排序：heat_score 降序
        items = data["items"]
        heat_scores = [i["heat_score"] for i in items]
        assert heat_scores == sorted(heat_scores, reverse=True)

        # 验证统计
        assert data["stats"]["double_confirmed"] == 2
        assert data["stats"]["strong_rs"] == 1
        assert data["stats"]["catalyst_only"] == 1

    async def test_get_catalyst_stocks_filter_confirm_level(self, client, seed_catalyst_data, patch_catalyst_session):
        """按 confirm_level 筛选。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/stocks?confirm_level=double_confirmed")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["count"] == 2
        for item in data["items"]:
            assert item["confirm_level"] == "double_confirmed"

    async def test_get_catalyst_stocks_filter_min_heat(self, client, seed_catalyst_data, patch_catalyst_session):
        """按最低热度分筛选。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/stocks?min_heat=15")
        assert resp.status_code == 200
        data = resp.json()["data"]
        # heat_score >= 15: 34.0 和 20.0
        assert data["count"] == 2
        for item in data["items"]:
            assert item["heat_score"] >= 15

    async def test_get_catalyst_stocks_filter_by_date(self, client, seed_catalyst_data, patch_catalyst_session):
        """指定日期查询 — 无数据日期返回空。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/stocks?target_date=2026-03-20")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["count"] == 0

    async def test_get_catalyst_stocks_futu_url(self, client, seed_catalyst_data, patch_catalyst_session):
        """验证 futu_url 生成。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/stocks")
        items = resp.json()["data"]["items"]
        for item in items:
            assert item["futu_url"] is not None
            assert "futunn.com" in item["futu_url"]

    async def test_check_catalyst_hit(self, client, seed_catalyst_data, patch_catalyst_session):
        """查询命中的标的。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/check?ts_code=300750.SZ")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["has_catalyst"] is True
        assert data["ts_code"] == "300750.SZ"
        assert data["news_count"] == 3
        assert data["heat_score"] == 34.0
        assert data["confirm_level"] == "double_confirmed"

    async def test_check_catalyst_miss(self, client, seed_catalyst_data, patch_catalyst_session):
        """查询未命中的标的。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/check?ts_code=601398.SH")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["has_catalyst"] is False

    async def test_check_catalyst_empty_db(self, client, patch_catalyst_session):
        """空数据库查询返回 has_catalyst=False。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/check?ts_code=300750.SZ")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["has_catalyst"] is False

    async def test_batch_check_catalyst(self, client, seed_catalyst_data, patch_catalyst_session):
        """批量查询多只标的。"""
        with patch_catalyst_session:
            resp = await client.get(
                "/api/v1/catalyst/batch_check?ts_codes=300750.SZ,002594.SZ,601398.SH"
            )
        assert resp.status_code == 200
        data = resp.json()["data"]

        assert data["date"] == "2026-03-22"
        items = data["items"]

        # 300750 和 002594 有数据
        assert "300750.SZ" in items
        assert items["300750.SZ"]["has_catalyst"] is True
        assert items["300750.SZ"]["heat_score"] == 34.0

        assert "002594.SZ" in items
        assert items["002594.SZ"]["has_catalyst"] is True

        # 601398 无数据
        assert "601398.SH" not in items

    async def test_batch_check_empty_codes(self, client, seed_catalyst_data, patch_catalyst_session):
        """空代码列表返回空。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/batch_check?ts_codes=")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == {}

    async def test_batch_check_empty_db(self, client, patch_catalyst_session):
        """空数据库批量查询返回空。"""
        with patch_catalyst_session:
            resp = await client.get("/api/v1/catalyst/batch_check?ts_codes=300750.SZ")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == {}


# ═══════════════════════════════════════════════════════════
#  5. Service Integration Tests (with DB, mocked LLM)
# ═══════════════════════════════════════════════════════════

class TestCatalystAggregationPipeline:
    """测试催化剂聚合 pipeline 的端到端流程（mock LLM，真实 DB session）。"""

    @pytest.fixture
    async def seed_news_data(self, db_session):
        """插入测试用高分新闻。"""
        news_items = []
        for i, (title, tags, entity, score, cat_type, sentiment) in enumerate([
            ("宁德时代Q1净利大增50%", ["宁德时代", "锂电池"], "宁德时代", 9, "业绩财报", 4),
            ("宁德时代发布新一代固态电池", ["宁德时代", "固态电池"], "宁德时代", 8, "产品技术突破", 3),
            ("比亚迪新款车型销量破纪录", ["比亚迪", "新能源汽车"], "比亚迪", 8, "产品技术突破", 3),
            ("贵州茅台提价10%", ["贵州茅台", "白酒"], "贵州茅台", 7, "业绩财报", 2),
            ("低分新闻不应被提取", ["某公司"], "某公司", 5, "其他", 0),
        ]):
            n = News(
                id=uuid.uuid4(),
                title=title,
                source="财联社",
                url=f"https://example.com/news/{i}",
                ai_score=score,
                ai_summary=f"摘要{i}",
                tags=tags,
                sentiment_entity=entity,
                catalyst_type=cat_type,
                sentiment_score=sentiment,
                published_at=datetime.now(timezone.utc),
            )
            news_items.append(n)
            db_session.add(n)
        await db_session.commit()
        return news_items

    @pytest.fixture
    async def seed_vcp_data(self, db_session):
        """插入 VCP 白名单数据（宁德时代在白名单中）。"""
        db_session.add(WatchlistDaily(
            run_date=date(2026, 3, 22),
            ts_code="300750.SZ",
            name="宁德时代",
            vcp_score=0.85,
            industry="锂电池",
        ))
        await db_session.commit()

    @pytest.fixture
    async def seed_trend_data(self, db_session):
        """插入趋势白名单数据（比亚迪在白名单中）。"""
        db_session.add(TrendWatchlistDaily(
            run_date=date(2026, 3, 22),
            ts_code="002594.SZ",
            name="比亚迪",
            trend_score=0.72,
            industry="新能源汽车",
        ))
        await db_session.commit()

    @pytest.fixture
    async def seed_rs_data(self, db_session):
        """插入 RS Rating 数据。"""
        for code, rs in [("300750.SZ", 92), ("002594.SZ", 88), ("600519.SH", 85)]:
            db_session.add(StockRSRating(
                ts_code=code,
                name="",
                trade_date=date(2026, 3, 22),
                score=0.0,
                rs_rating=rs,
            ))
        await db_session.commit()

    async def test_fetch_high_score_news(self, db_session, seed_news_data):
        """验证只获取 ai_score >= 7 的新闻。"""
        from app.services.catalyst_aggregator import _fetch_high_score_news

        # Mock async_session 以使用测试的 db session
        with patch("app.services.catalyst_aggregator.async_session") as mock_session_factory:
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            news = await _fetch_high_score_news(date(2026, 3, 22))

        assert len(news) == 4  # 9, 8, 8, 7（排除了5分的）
        assert all(n["ai_score"] >= 7 for n in news)
        # 按分数降序
        scores = [n["ai_score"] for n in news]
        assert scores == sorted(scores, reverse=True)

    async def test_fetch_vcp_map(self, db_session, seed_vcp_data):
        """验证 VCP 白名单数据获取。"""
        from app.services.catalyst_aggregator import _fetch_vcp_map

        with patch("app.services.catalyst_aggregator.async_session") as mock_session_factory:
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            vcp_map = await _fetch_vcp_map(date(2026, 3, 22))

        assert "300750.SZ" in vcp_map
        assert vcp_map["300750.SZ"]["name"] == "宁德时代"
        assert vcp_map["300750.SZ"]["vcp_score"] == 0.85

    async def test_fetch_trend_map(self, db_session, seed_trend_data):
        """验证趋势白名单数据获取。"""
        from app.services.catalyst_aggregator import _fetch_trend_map

        with patch("app.services.catalyst_aggregator.async_session") as mock_session_factory:
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            trend_map = await _fetch_trend_map(date(2026, 3, 22))

        assert "002594.SZ" in trend_map
        assert trend_map["002594.SZ"]["name"] == "比亚迪"

    async def test_fetch_rs_map(self, db_session, seed_rs_data):
        """验证 RS Rating 数据获取。"""
        from app.services.catalyst_aggregator import _fetch_rs_map

        with patch("app.services.catalyst_aggregator.async_session") as mock_session_factory:
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            rs_map = await _fetch_rs_map(date(2026, 3, 22))

        assert rs_map["300750.SZ"] == 92
        assert rs_map["002594.SZ"] == 88
        assert rs_map["600519.SH"] == 85


# ═══════════════════════════════════════════════════════════
#  6. Helper Function Tests
# ═══════════════════════════════════════════════════════════

class TestFutuUrlGeneration:
    """测试富途链接生成。"""

    def test_sz_stock(self):
        from app.api.v1.catalyst import _generate_futu_url
        url = _generate_futu_url("300750.SZ")
        assert url == "https://www.futunn.com/stock/300750-SZ"

    def test_sh_stock(self):
        from app.api.v1.catalyst import _generate_futu_url
        url = _generate_futu_url("600519.SH")
        assert url == "https://www.futunn.com/stock/600519-SH"

    def test_bj_stock(self):
        from app.api.v1.catalyst import _generate_futu_url
        url = _generate_futu_url("430047.BJ")
        assert url == "https://www.futunn.com/stock/430047-SZ"


class TestCatalystStockItemSchema:
    """测试 Pydantic schema 序列化。"""

    def test_catalyst_stock_item(self):
        from app.api.v1.catalyst import CatalystStockItem

        item = CatalystStockItem(
            ts_code="300750.SZ",
            name="宁德时代",
            news_count=3,
            top_score=9,
            avg_score=8.3,
            catalyst_types=["业绩财报"],
            heat_score=34.0,
            confirm_level="double_confirmed",
            in_vcp=True,
            vcp_score=0.85,
        )
        data = item.model_dump()
        assert data["ts_code"] == "300750.SZ"
        assert data["name"] == "宁德时代"
        assert data["heat_score"] == 34.0
        assert data["confirm_level"] == "double_confirmed"
        assert data["in_vcp"] is True

    def test_catalyst_stock_item_defaults(self):
        from app.api.v1.catalyst import CatalystStockItem

        item = CatalystStockItem(ts_code="000001.SZ")
        data = item.model_dump()
        assert data["news_count"] == 0
        assert data["heat_score"] == 0.0
        assert data["confirm_level"] == "catalyst_only"
        assert data["in_vcp"] is False
        assert data["in_trend"] is False
        assert data["futu_url"] is None
