#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深挖 shared=0 的伊朗样本：事件实体 vs 线实体 逐条对照。"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session               # noqa: E402
from app.services import thread_router as tr         # noqa: E402


async def main():
    async with async_session() as s:
        gt = {}
        for eid, tid in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events WHERE assigned_by='manual'"
        ))).all():
            gt[str(eid)] = str(tid)

        ev_ent = defaultdict(dict)
        for r in (await s.execute(text("""
            SELECT ee.event_id, e.canonical_name, ee.weight
            FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        """))).all():
            ev_ent[str(r[0])][r[1]] = int(r[2] or 1)

        titles = {str(r[0]): r[1] for r in (await s.execute(text(
            "SELECT id, COALESCE(title,'') FROM events"))).all()}

        th = {}
        for r in (await s.execute(text(
            "SELECT id, title, core_entities FROM threads"))).mappings().all():
            ce = r["core_entities"] or {}
            if isinstance(ce, str):
                try:
                    ce = json.loads(ce)
                except Exception:
                    ce = {}
            th[str(r["id"])] = (r["title"] or "",
                                {k: int(v) for k, v in ce.items()})

    denylist = tr._denylist() if hasattr(tr, "_denylist") else set()

    print("=" * 78)
    print("shared=0 的伊朗样本：事件实体 vs 线实体 逐条对照")
    print("=" * 78)

    zeros = []
    for eid, tid in gt.items():
        if tid not in th:
            continue
        ttl, tcore = th[tid]
        if "霍尔木兹" not in ttl and "伊朗" not in ttl:
            continue
        ev = {k: v for k, v in ev_ent.get(eid, {}).items() if k not in denylist}
        tc = {k: v for k, v in tcore.items() if k not in denylist}
        shared = set(ev) & set(tc)
        if not shared:
            zeros.append((eid, ttl, titles.get(eid, ""), ev, tc))

    print(f"共 {len(zeros)} 条 shared=0\n")
    for i, (eid, ttl, etitle, ev, tc) in enumerate(zeros[:12], 1):
        print(f"── 样本 {i} ──")
        print(f"  事件：{etitle[:52]}")
        print(f"  线  ：{ttl[:52]}")
        print(f"  事件实体({len(ev)})：{sorted(ev.items(), key=lambda x:-x[1])}")
        print(f"  线实体  ({len(tc)})：{sorted(tc.items(), key=lambda x:-x[1])}")
        print()

    # 线的实体全貌
    if zeros:
        ttl, tc = zeros[0][1], zeros[0][4]
        print("─" * 78)
        print(f"【该线的 core_entities 全貌】{ttl}")
        print("─" * 78)
        for k, v in sorted(tc.items(), key=lambda x: -x[1]):
            print(f"    {v:>4}  {k}")
        print()

        # 这批事件共同提到、但线里没有的实体
        print("─" * 78)
        print("被拦事件高频实体 TOP20（线里没有的 → 该进 core_entities）")
        print("─" * 78)
        freq = defaultdict(int)
        for _, _, _, ev, _ in zeros:
            for k in ev:
                freq[k] += 1
        for k, v in sorted(freq.items(), key=lambda x: -x[1])[:20]:
            mark = "★线里已有" if k in tc else ""
            print(f"    {v:>3} 条  {k}  {mark}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
