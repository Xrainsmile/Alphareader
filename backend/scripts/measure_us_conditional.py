#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证"美国条件放行"：仅当双方已有 >=1 个非国家共同实体时，才允许
「美国」计入 Jaccard。既拿到收益，又不引入误串。

对照：
  S0 现状（美国被 is_generic 过滤）          280  63.5%  误串 1.73%
  S1 美国无条件放行                          ~288        误串 2.84%
  S2 美国条件放行（需先有共同实体）           ?          误串 ?
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

US = "美国"
JP = "日本"


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

    def build(d, allow: set[str]):
        out = {}
        for k, v in d.items():
            if k in blocked:
                continue
            c = canonicalize(k)[0]
            if c in blocked:
                continue
            out[c] = max(out.get(c, 0), v)
        return out

    def keep_us(a: dict, b: dict) -> bool:
        """条件放行：先有 >=1 个非国家共同实体，才允许美国计入。"""
        shared = (set(a) & set(b)) - {US, JP}
        return len(shared) >= 1

    def prep(eid, tid, allow, conditional):
        gen = ev_gen.get(eid, set())
        ev0 = {k: v for k, v in ev_all.get(eid, {}).items()
               if k not in gen or k in allow}
        ev = build(ev0, allow)
        tc = build(threads[tid][1], allow)
        if conditional:
            if not keep_us(ev, tc):
                ev.pop(US, None)
                tc.pop(US, None)
        return ev, tc

    def run(allow, conditional):
        ok = total = 0
        for eid, tid in gt:
            if tid not in threads:
                continue
            ev, tc = prep(eid, tid, allow, conditional)
            if not ev or not tc:
                continue
            total += 1
            e = tr.weighted_jaccard_normalized(ev, tc)
            g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
            ok += g
        return ok, total

    def risk(allow, conditional):
        gt_map = defaultdict(set)
        for e, t in gt:
            gt_map[e].add(t)
        cross = tot = 0
        for eid in list(gt_map):
            for tid, (_t, ce) in threads.items():
                if tid in gt_map.get(eid, set()):
                    continue
                ev, tc = prep(eid, tid, allow, conditional)
                if not ev or not tc:
                    continue
                tot += 1
                e = tr.weighted_jaccard_normalized(ev, tc)
                g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
                if g:
                    cross += 1
        return cross, tot

    print("=" * 78)
    print("美国「条件放行」验证")
    print("=" * 78)
    print()
    cfgs = [
        ("S0 现状（全部过滤）",            set(),          False),
        ("S1 放日本（无条件）",            {JP},           False),
        ("S2 放日本+美国（无条件）",        {US, JP},       False),
        ("S3 放日本+美国（条件放行）",      {US, JP},       True),
    ]
    print("─" * 78)
    print("【1】收益 vs 风险")
    print("─" * 78)
    print(f"  {'配置':<28}{'过门控':>12}{'误串率':>10}")
    base_c = None
    for label, allow, cond in cfgs:
        ok, tot = run(allow, cond)
        c, ct = risk(allow, cond)
        r = 100 * c / max(ct, 1)
        if base_c is None:
            base_c = r
        print(f"  {label:<28}{ok:>4}/{tot}  {100*ok/max(tot,1):>5.1f}%"
              f"{r:>8.2f}%  ({r-base_c:+.2f}pp)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
