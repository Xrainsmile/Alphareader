#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排查：生产链路 63.5% vs 模拟 67.6% 的差异来源。

逐项对比两套口径，定位是哪个过滤环节吃掉了收益。
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session            # noqa: E402
from app.services import thread_router as tr      # noqa: E402
from app.services.entity_writer import canonicalize  # noqa: E402


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
        # 含 is_generic 的全量
        ev_all = defaultdict(dict)
        ev_gen = defaultdict(set)
        for r in (await s.execute(text("""
            SELECT ee.event_id, e.canonical_name, ee.weight,
                   COALESCE(e.is_generic,false)
            FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        """))).all():
            ev_all[str(r[0])][r[1]] = int(r[2] or 1)
            if r[3]:
                ev_gen[str(r[0])].add(r[1])
        threads = {str(r["id"]): (r["title"], parse_ce(r["core_entities"]))
                   for r in (await s.execute(text(
                       "SELECT id, title, core_entities FROM threads"
                   ))).mappings().all()}

    blocked = tr._denylist()

    def canonical_merge(d):
        out = {}
        for k, v in d.items():
            c = canonicalize(k)[0]
            if c in blocked:
                continue
            out[c] = max(out.get(c, 0), v)
        return out

    print("=" * 78)
    print("差异排查：生产链路 vs 模拟口径")
    print("=" * 78)
    print(f"denylist 生效词数 {len(blocked)}")
    print()

    # A 生产链路
    okA = totA = 0
    for eid, tid in gt:
        if tid not in threads:
            continue
        ev = await tr._load_event_entities(__import__("uuid").UUID(eid))
        tc = tr._thread_entity_weights(threads[tid][1])
        if not ev or not tc:
            continue
        totA += 1
        e = tr.weighted_jaccard_normalized(ev, tc)
        g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
        okA += g

    # B 模拟：不去 is_generic，直接 canonicalize
    okB = totB = 0
    for eid, tid in gt:
        if tid not in threads:
            continue
        ev = canonical_merge(ev_all.get(eid, {}))
        tc = canonical_merge(threads[tid][1])
        if not ev or not tc:
            continue
        totB += 1
        e = tr.weighted_jaccard_normalized(ev, tc)
        g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
        okB += g

    # C 模拟 + 去 is_generic
    okC = totC = 0
    for eid, tid in gt:
        if tid not in threads:
            continue
        ev = canonical_merge({k: v for k, v in ev_all.get(eid, {}).items()
                              if k not in ev_gen.get(eid, set())})
        tc = canonical_merge(threads[tid][1])
        if not ev or not tc:
            continue
        totC += 1
        e = tr.weighted_jaccard_normalized(ev, tc)
        g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
        okC += g

    print("─" * 78)
    print("【1】三口径对比")
    print("─" * 78)
    print(f"  A 生产链路（去is_generic·去deny·canon）   {okA:>3}/{totA}  "
          f"{100*okA/max(totA,1):>5.1f}%")
    print(f"  B 模拟（不去is_generic·canon）            {okB:>3}/{totB}  "
          f"{100*okB/max(totB,1):>5.1f}%")
    print(f"  C 模拟+去is_generic                      {okC:>3}/{totC}  "
          f"{100*okC/max(totC,1):>5.1f}%")
    print()

    # is_generic 影响面
    gen_hits = sum(1 for eid, _ in gt if ev_gen.get(eid))
    print("─" * 78)
    print("【2】is_generic 影响面")
    print("─" * 78)
    print(f"  含 is_generic 实体的事件：{gen_hits} / {len(gt)}")
    from collections import Counter
    c = Counter()
    for eid, _ in gt:
        for n in ev_gen.get(eid, set()):
            c[n] += 1
    print(f"  被标 generic 的实体名（前 10）：{c.most_common(10)}")
    print()

    # 线的 core_entities 是否含 generic
    print("─" * 78)
    print("【3】canonicalize 对线侧的影响")
    print("─" * 78)
    changed = []
    for tid, (title, ce) in threads.items():
        merged = canonical_merge(ce)
        if set(merged) != set(ce):
            changed.append((title, list(ce), list(merged)))
    print(f"  canonicalize 后实体集合发生变化的线：{len(changed)}")
    for t, a, b in changed[:8]:
        print(f"    {str(t)[:28]}")
        print(f"      旧 {a}")
        print(f"      新 {b}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
