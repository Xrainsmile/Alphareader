#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产实测：P0-6 上线后的真实门控通过率。

走真实链路 _load_event_entities + _thread_entity_weights，
不再自己拼实体字典，确保测的就是生产逻辑。
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session            # noqa: E402
from app.services import thread_router as tr      # noqa: E402


async def main():
    async with async_session() as s:
        gt = [(a, b) for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all()]
        threads = {r["id"]: r for r in (await s.execute(text(
            "SELECT id, title, core_entities FROM threads"
        ))).mappings().all()}

    ok = total = 0
    fails = []
    for eid, tid in gt:
        t = threads.get(tid)
        if not t:
            continue
        ev = await tr._load_event_entities(eid)
        tc = tr._thread_entity_weights(t["core_entities"])
        if not ev or not tc:
            continue
        total += 1
        e = tr.weighted_jaccard_normalized(ev, tc)
        g, why = tr.entity_gate(e, len(set(ev) & set(tc)))
        if g:
            ok += 1
        else:
            fails.append((e, t["title"], len(ev), len(tc)))

    print("=" * 78)
    print("P0-6 生产实测（真实链路）")
    print("=" * 78)
    print(f"  有效配对        {total}")
    print(f"  过门控          {ok}  ({100*ok/max(total,1):.1f}%)")
    print(f"  未过            {len(fails)}")
    print()
    print("  历史基线：")
    print("    污染基线起点   61.7%  (272/441)")
    print("    + 权重压平     62.8%  (277/441)")
    print(f"    + P0-6         {100*ok/max(total,1):.1f}%  ({ok}/{total})")
    print()

    fails.sort()
    print("  仍未过门控的样本（前 8，按 E 降序）：")
    for e, tt, ne, nt in fails[:8]:
        print(f"    E={e:.4f}  事件实体{ne:>2} 线实体{nt:>2}  {str(tt)[:30]}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
