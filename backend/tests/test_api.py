"""Tests for API endpoints — uses TestClient with isolated DB + mocked Redis."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.news import News
from app.models.sandbox import SandboxAnalysis, SandboxNav, SandboxStock, SandboxTrade
from app.models.stock import StockDailyQuote


class TestRootEndpoint:
    async def test_root_returns_service_info(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "AlphaReader"
        assert "version" in data


class TestHealthEndpoint:
    async def test_health_ok(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestNewsListEndpoint:
    @pytest.fixture
    async def seed_news(self, db_session):
        """Insert sample news items for query tests."""
        items = []
        for i in range(5):
            n = News(
                id=uuid.uuid4(),
                title=f"Test News {i}",
                source="财联社" if i % 2 == 0 else "东方财富",
                url=f"https://example.com/news/{i}",
                ai_score=5 + i,  # scores: 5, 6, 7, 8, 9
                ai_summary=f"Summary {i}",
                tags=["科技"] if i % 2 == 0 else ["金融"],
                published_at=datetime.now(timezone.utc),
            )
            items.append(n)
            db_session.add(n)
        await db_session.commit()
        return items

    async def test_list_news_empty(self, client):
        resp = await client.get("/api/v1/news/")
        assert resp.status_code == 200
        data = resp.json()
        # PaginatedResponse: {code, message, data: [], total, limit, offset}
        assert data["code"] == 0
        assert data["data"] == []
        assert data["total"] == 0

    async def test_list_news_with_data(self, client, seed_news):
        resp = await client.get("/api/v1/news/?min_score=6")
        assert resp.status_code == 200
        data = resp.json()
        # scores 6,7,8,9 pass min_score=6
        assert data["total"] == 4
        assert len(data["data"]) == 4

    async def test_list_news_pagination(self, client, seed_news):
        resp = await client.get("/api/v1/news/?min_score=5&limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["data"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

    async def test_list_news_source_filter(self, client, seed_news):
        resp = await client.get("/api/v1/news/?min_score=5&source=财联社")
        assert resp.status_code == 200
        data = resp.json()
        for item in data["data"]:
            assert item["source"] == "财联社"

    async def test_list_news_ordered_by_score_desc(self, client, seed_news):
        """With sort=score, items should be ordered by ai_score descending."""
        resp = await client.get("/api/v1/news/?min_score=5&sort=score")
        assert resp.status_code == 200
        items = resp.json()["data"]
        scores = [i["ai_score"] for i in items]
        assert scores == sorted(scores, reverse=True)

    async def test_list_news_hot_sort_returns_ranking_score(self, client, seed_news):
        """Default sort=hot should include ranking_score in response."""
        resp = await client.get("/api/v1/news/?min_score=5&sort=hot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        for item in data["data"]:
            assert "ranking_score" in item
            assert isinstance(item["ranking_score"], (int, float))

    async def test_list_news_latest_sort(self, client, seed_news):
        """sort=latest should return items ordered by created_at desc."""
        resp = await client.get("/api/v1/news/?min_score=5&sort=latest")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0


class TestPipelineEndpoints:
    async def test_pipeline_status(self, client):
        resp = await client.get("/api/v1/news/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        # APIResponse: {code, message, data: {running, last_result}}
        assert data["code"] == 0
        assert "running" in data["data"]

    async def test_trigger_pipeline(self, client, monkeypatch):
        import app.api.v1.news as news_api

        async def _fake_bg():
            news_api._pipeline_status["running"] = False
            news_api._pipeline_status["last_result"] = {"fetched": 1, "stored": 1}

        news_api._pipeline_status["running"] = False
        monkeypatch.setattr(news_api, "_run_pipeline_bg", _fake_bg)

        resp = await client.post("/api/v1/news/pipeline/run")
        assert resp.status_code == 200
        assert "Pipeline started" in resp.json()["message"]

    async def test_clear_cache(self, client):
        resp = await client.delete("/api/v1/news/pipeline/cache")
        assert resp.status_code == 200
        data = resp.json()
        # APIResponse: {code, message, data: {keys_deleted}}
        assert data["code"] == 0
        assert "keys_deleted" in data["data"]


class TestSandboxStocksEndpoint:
    @pytest.fixture
    async def seed_sandbox_data(self, db_session):
        s_holding = SandboxStock(ts_code="600519", name="贵州茅台", status="holding", reason="核心持仓")
        s_watch = SandboxStock(ts_code="000001", name="平安银行", status="watching", reason="观察")
        db_session.add_all([s_holding, s_watch])
        await db_session.flush()

        db_session.add_all(
            [
                SandboxAnalysis(
                    stock_id=s_holding.id,
                    ts_code=s_holding.ts_code,
                    score=3.2,
                    trend="趋势1",
                    pattern="形态1",
                    volume_price="量价1",
                    plan="计划1",
                    pnl_thinking="思考1",
                    verdict="结论1",
                ),
                SandboxAnalysis(
                    stock_id=s_holding.id,
                    ts_code=s_holding.ts_code,
                    score=4.3,
                    trend="趋势2",
                    pattern="形态2",
                    volume_price="量价2",
                    plan="计划2",
                    pnl_thinking="思考2",
                    verdict="结论2",
                ),
                SandboxTrade(
                    stock_id=s_holding.id,
                    ts_code=s_holding.ts_code,
                    action="buy",
                    price=Decimal("10.00"),
                    shares=100,
                    trade_date=date(2026, 2, 14),
                    note="建仓",
                ),
                StockDailyQuote(
                    ts_code=s_holding.ts_code,
                    name=s_holding.name,
                    trade_date=date(2026, 2, 14),
                    close=10.0,
                ),
                SandboxNav(
                    trade_date=date(2026, 2, 14),
                    total_market_value=Decimal("1000.00"),
                    cash=Decimal("9000.00"),
                    nav=1.0,
                    total_pnl=0.0,
                ),
            ]
        )
        await db_session.commit()
        return {"holding_id": s_holding.id, "watch_id": s_watch.id}

    async def test_sandbox_stocks_core_path(self, client, seed_sandbox_data):
        resp = await client.get("/api/v1/sandbox/stocks?holding_only=true")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 1
        assert len(data["items"]) == 1

        item = data["items"][0]
        assert item["id"] == seed_sandbox_data["holding_id"]
        assert item["analysis_count"] == 2
        assert item["latest_analysis"]["score"] == 4.3
        assert item["position_pct"] == 10.0
