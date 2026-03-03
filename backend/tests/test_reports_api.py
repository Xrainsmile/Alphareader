"""Reports API tests (migrated from legacy smoke script)."""

from __future__ import annotations

import pytest

import app.api.v1.reports as reports_api


@pytest.fixture(autouse=True)
def _patch_sync_token(monkeypatch):
    """Patch module-level SYNC_TOKEN used by verify_sync_token()."""
    monkeypatch.setattr(reports_api, "SYNC_TOKEN", "test-report-token")


class TestReportsAPI:
    async def test_reports_crud_flow(self, client):
        # 1) list empty
        resp = await client.get("/api/v1/reports/")
        assert resp.status_code == 200
        assert resp.json() == []

        # 2) sync without token -> 401
        resp = await client.post(
            "/api/v1/reports/sync",
            json={"sync_id": "t", "title": "t", "content": "# t"},
        )
        assert resp.status_code == 401

        # 3) sync with token -> create
        payload_create = {
            "sync_id": "test-0212",
            "title": "测试复盘",
            "date": "2026-02-12",
            "cover": "",
            "summary": "测试摘要",
            "content": "# Hello\n\n测试正文",
        }
        resp = await client.post(
            "/api/v1/reports/sync",
            json=payload_create,
            headers={"Authorization": "Bearer test-report-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "created"

        # 4) list has 1+
        resp = await client.get("/api/v1/reports/")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1

        # 5) detail
        rid = items[0]["id"]
        resp = await client.get(f"/api/v1/reports/{rid}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "测试复盘"

        # 6) upsert (update)
        payload_update = {
            "sync_id": "test-0212",
            "title": "测试复盘(更新)",
            "date": "2026-02-12",
            "cover": "",
            "summary": "更新摘要",
            "content": "# Updated",
        }
        resp = await client.post(
            "/api/v1/reports/sync",
            json=payload_update,
            headers={"Authorization": "Bearer test-report-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "updated"

        # 7) 404 detail
        resp = await client.get("/api/v1/reports/99999")
        assert resp.status_code == 404
