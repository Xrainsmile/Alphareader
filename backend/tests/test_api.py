"""Tests for API endpoints — uses TestClient with isolated DB + mocked Redis."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.news import News


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
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_news_with_data(self, client, seed_news):
        resp = await client.get("/api/v1/news/?min_score=6")
        assert resp.status_code == 200
        data = resp.json()
        # scores 6,7,8,9 pass min_score=6
        assert data["total"] == 4
        assert len(data["items"]) == 4

    async def test_list_news_pagination(self, client, seed_news):
        resp = await client.get("/api/v1/news/?min_score=5&limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

    async def test_list_news_source_filter(self, client, seed_news):
        resp = await client.get("/api/v1/news/?min_score=5&source=财联社")
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["source"] == "财联社"

    async def test_list_news_ordered_by_score_desc(self, client, seed_news):
        """With sort=score, items should be ordered by ai_score descending."""
        resp = await client.get("/api/v1/news/?min_score=5&sort=score")
        assert resp.status_code == 200
        items = resp.json()["items"]
        scores = [i["ai_score"] for i in items]
        assert scores == sorted(scores, reverse=True)

    async def test_list_news_hot_sort_returns_ranking_score(self, client, seed_news):
        """Default sort=hot should include ranking_score in response."""
        resp = await client.get("/api/v1/news/?min_score=5&sort=hot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sort"] == "hot"
        assert "gravity" in data
        for item in data["items"]:
            assert "ranking_score" in item
            assert isinstance(item["ranking_score"], (int, float))

    async def test_list_news_latest_sort(self, client, seed_news):
        """sort=latest should return items ordered by created_at desc."""
        resp = await client.get("/api/v1/news/?min_score=5&sort=latest")
        assert resp.status_code == 200
        assert resp.json()["sort"] == "latest"


class TestPipelineEndpoints:
    async def test_pipeline_status(self, client):
        resp = await client.get("/api/v1/news/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data

    async def test_clear_cache(self, client):
        resp = await client.delete("/api/v1/news/pipeline/cache")
        assert resp.status_code == 200
        data = resp.json()
        assert "keys_deleted" in data
