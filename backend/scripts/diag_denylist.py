#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：THREAD_ENTITY_DENYLIST 是否误杀了线的「争夺标的」。

P0-3 的立意正确 —— 8-K 这类**披露形式**不能当锚点。
但把「原油/石油/油价/天然气/AI/芯片/美元」一并划为"通用名词"时，
对**主题线**（原油供给冲击、AI算力版图）而言，这些恰恰是争夺标的本身。

典型事故：
    线「原油供给冲击与价格传导」core_entities = {原油, 柴油, 石油, 欧盟, 美国}
    过 denylist 后 → {柴油, 欧盟, 美国}      ← 「原油」被删
    事件「EIA上调油价预期」实体 = {EIA, WTI原油, 布伦特原油}
    → 零交集，E=0，永远归不进这条线

本脚本量化：denylist 整体 / 逐词 对门控通过率的贡献与伤害。
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session            # noqa: E402
from app.config import settings                   # noqa: E402
from app.services import thread_router as tr      # noqa: E402

DENY = list(settings.THREAD_ENTITY_DENYLIST or [])


def parse_ce(v) -> dict:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return {}
    if isinstance(v, dict):
        return {k: int(x) for k, x in v.items() if isinstance(x, (int, float))}
    if isinstance(v, list):
        return {str(x): 1 for x in v}
    return {}


async def main():
    async with async_session() as s:
        gt = [(str(a), str(b)) for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all()]
        ev_ent = defaultdict(dict)
        for r in (await s.execute(text("""
            SELECT ee.event_id, e.canonical_name, ee.weight
            FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        """))).all():
            ev_ent[str(r[0])][r[1]] = int(r[2] or 1)
        threads = {str(r["id"]): (r["title"], parse_ce(r["core_entities"]))
                   for r in (await s.execute(text(
                       "SELECT id, title, core_entities FROM threads"
                   ))).mappings().all()}

    def run(deny: set[str]):
        ok = total = 0
        for eid, tid in gt:
            ev = {k: v for k, v in ev_ent.get(eid, {}).items() if k not in deny}
            tc = {k: v for k, v in (threads.get(tid, ("", {}))[1]).items()
                  if k not in deny}
            if not ev or not tc:
                continue
            total += 1
            e = tr.weighted_jaccard_normalized(ev, tc)
            g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
            ok += g
        return ok, total

    full = set(DENY)
    print("=" * 78)
    print("denylist 影响诊断")
    print("=" * 78)
    print(f"denylist 共 {len(full)} 个词")
    print()

    ok0, tot = run(set())
    ok1, _ = run(full)
    print("─" * 78)
    print("【1】整体开关")
    print("─" * 78)
    print(f"  关闭 denylist   过门控 {ok0}/{tot}  {100*ok0/max(tot,1):>5.1f}%")
    print(f"  开启 denylist   过门控 {ok1}/{tot}  {100*ok1/max(tot,1):>5.1f}%")
    print(f"  → denylist 净   {ok1-ok0:+d} 条 ({100*(ok1-ok0)/max(tot,1):+.1f}pp)")
    print()

    print("─" * 78)
    print("【2】逐词贡献（单独移除该词，看通过率变化）")
    print("─" * 78)
    print("  负 = 该词在伤害（移除后通过率上升，说明误杀）")
    print("  正 = 该词在帮忙（移除后通过率下降，说明拦对了）")
    print()
    rows = []
    for w in DENY:
        ok2, _ = run(full - {w})
        rows.append((ok2 - ok1, w, ok2))
    rows.sort()
    print("  【伤害最大的 12 个词】")
    for d, w, ok2 in rows[:12]:
        print(f"    {d:>+4}  {w:<22} (移除后 {ok2}/{tot} = {100*ok2/max(tot,1):.1f}%)")
    print()
    print("  【帮助最大的 8 个词】")
    for d, w, ok2 in rows[-8:][::-1]:
        print(f"    {d:>+4}  {w:<22} (移除后 {ok2}/{tot} = {100*ok2/max(tot,1):.1f}%)")
    print()

    print("─" * 78)
    print("【3】主题线实体被删情况")
    print("─" * 78)
    for tid, (title, ce) in sorted(threads.items(),
                                   key=lambda x: -sum(x[1][1].values())):
        removed = {k: v for k, v in ce.items() if k in full}
        if removed:
            left = {k: v for k, v in ce.items() if k not in full}
            print(f"  {str(title)[:30]:<30}")
            print(f"    全量 {list(ce)}")
            print(f"    剩   {list(left)}   被删 {list(removed)}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
