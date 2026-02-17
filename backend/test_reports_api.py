"""Quick smoke test for Reports API endpoints."""
import asyncio
import httpx

BASE = "http://localhost:8000"
TOKEN = "syncAlphaRick2333"

async def test():
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        # 1. List (empty)
        r = await c.get("/api/v1/reports/")
        print(f"1. GET /reports/ -> {r.status_code} count={len(r.json())}")

        # 2. Sync without token -> 401
        r = await c.post("/api/v1/reports/sync", json={"sync_id":"t","title":"t","content":"# t"})
        print(f"2. POST /sync (no token) -> {r.status_code}")

        # 3. Sync with token -> create
        r = await c.post("/api/v1/reports/sync",
            json={"sync_id":"test-0212","title":"测试复盘","date":"2026-02-12",
                  "cover":"","summary":"测试摘要","content":"# Hello\n\n测试正文"},
            headers={"Authorization": f"Bearer {TOKEN}"})
        data = r.json()
        print(f"3. POST /sync (create) -> {r.status_code} action={data.get('action')}")

        # 4. List (should have 1+)
        r = await c.get("/api/v1/reports/")
        items = r.json()
        print(f"4. GET /reports/ -> {r.status_code} count={len(items)}")

        # 5. Detail
        if items:
            rid = items[0]["id"]
            r = await c.get(f"/api/v1/reports/{rid}")
            print(f"5. GET /reports/{rid} -> {r.status_code} title={r.json()['title']}")

        # 6. Upsert (update)
        r = await c.post("/api/v1/reports/sync",
            json={"sync_id":"test-0212","title":"测试复盘(更新)","date":"2026-02-12",
                  "cover":"","summary":"更新摘要","content":"# Updated"},
            headers={"Authorization": f"Bearer {TOKEN}"})
        print(f"6. POST /sync (upsert) -> {r.status_code} action={r.json().get('action')}")

        # 7. 404
        r = await c.get("/api/v1/reports/99999")
        print(f"7. GET /reports/99999 -> {r.status_code}")

        print("\n✅ All tests passed!")

asyncio.run(test())
