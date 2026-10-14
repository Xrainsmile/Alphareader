#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-5c 只读验证：线的 core_entities 是否被 rollup 覆盖过。

判定依据（thread_profile._load_chapter_entities）：
    weight = MAX(CASE WHEN weight >= 3 THEN 3 ELSE weight END)  →  只会是 1 或 3
若某条线 core_entities 里有权重 ∉ {1,3}，说明它没被 _refresh 写过，
是旧累加式逻辑的遗留物。

同时模拟：若对这批线强制 rollup，core_entities 会变成什么，
门控通过率能到多少。
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

CORE_W = settings.THREAD_CORE_ENTITY_WEIGHT       # 3
MAX_N = settings.THREAD_MAX_CORE_ENTITIES         # 10
MIN_CH = settings.THREAD_MIN_CHAPTERS_FOR_ROLLUP  # 2


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
        threads = (await s.execute(text(
            "SELECT id, title, chapter_count, core_entities, status "
            "FROM threads ORDER BY chapter_count DESC NULLS LAST"
        ))).mappings().all()

    print("=" * 78)
    print("P0-5c 只读验证：core_entities 是否被 rollup 覆盖过")
    print("=" * 78)
    print(f"合法权重取值：{{1, {CORE_W}}}   MAX_CORE_ENTITIES={MAX_N}   "
          f"MIN_CHAPTERS_FOR_ROLLUP={MIN_CH}")
    print(f"全库线 {len(threads)} 条")
    print()

    clean, stale = [], []
    for t in threads:
        ce = parse_ce(t["core_entities"])
        if not ce:
            continue
        bad = {k: v for k, v in ce.items() if v not in (1, CORE_W)}
        (stale if bad else clean).append((t, ce, bad))

    print("─" * 78)
    print(f"【1】权重越界（未被 rollup 覆盖）的线：{len(stale)} / {len(threads)}")
    print("─" * 78)
    for t, ce, bad in stale[:20]:
        cc = t["chapter_count"] or 0
        print(f"  章{cc:>3}  ent={len(ce):>2}  {str(t['title'])[:40]:<40} "
              f"越界权重样例={list(bad.items())[:3]}")
    if len(stale) > 20:
        print(f"  ... 另有 {len(stale)-20} 条")
    print()

    print("─" * 78)
    print("【2】越界线的实体数分布（vs 上限 10）")
    print("─" * 78)
    dist = defaultdict(int)
    for _t, ce, _b in stale:
        dist[len(ce)] += 1
    for n in sorted(dist):
        flag = "  ← 已满，截断" if n >= MAX_N else ""
        print(f"  {n:>2} 个实体：{dist[n]:>3} 条{flag}")
    print()

    # 模拟 rollup：线内章节实体并集，取覆盖章节数最多的前 10
    async with async_session() as s:
        rows = (await s.execute(text("""
            SELECT te.thread_id, e.canonical_name,
                   COUNT(DISTINCT te.event_id) AS chapter_cnt,
                   MAX(CASE WHEN COALESCE(ee.weight,1) >= :cw THEN :cw
                            ELSE COALESCE(ee.weight,1) END) AS w,
                   MAX(COALESCE(e.mention_count,1)) AS mc
            FROM thread_events te
            JOIN event_entities ee ON ee.event_id = te.event_id
            JOIN entities e ON e.id = ee.entity_id
            WHERE COALESCE(e.is_generic,false) = false
            GROUP BY te.thread_id, e.canonical_name
            ORDER BY te.thread_id, chapter_cnt DESC, mc DESC
        """), {"cw": CORE_W})).all()

    by_th = defaultdict(list)
    for tid, name, cnt, w, mc in rows:
        by_th[str(tid)].append((name, int(cnt), int(w or 1), int(mc or 1)))

    stale_ids = {str(t["id"]) for t, _ce, _b in stale}

    print("─" * 78)
    print("【3】模拟 rollup：越界线的实体池会扩到多大")
    print("─" * 78)
    grew = 0
    samples = []
    for tid in list(stale_ids)[:400]:
        if tid not in by_th:
            continue
        pool = by_th[tid]
        new_names = [n for n, _c, _w, _mc in pool[:MAX_N]]
        old_t = next((t for t, _ce, _b in stale if str(t["id"]) == tid), None)
        old_ce = parse_ce(old_t["core_entities"]) if old_t else {}
        old_names = list(old_ce)
        added = [n for n in new_names if n not in old_names]
        if added:
            grew += 1
            samples.append((old_t["chapter_count"] or 0, len(old_names),
                            len(pool), len(new_names), added[:6]))
    samples.sort(key=lambda x: -x[1])
    print(f"  越界线中实体池能扩大的：{grew} 条")
    print()
    for cc, on, pn, nn, added in samples[:10]:
        print(f"  章{cc:>3}  现有 {on:>2} → 池 {pn:>3} → 取 {nn:>2}   "
              f"新增={added}")
    print()

    # 影响面：模拟 rollup 后门控通过率
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

    denylist = tr._denylist() if hasattr(tr, "_denylist") else set()

    def new_ce(tid):
        if tid in by_th:
            return {n: w for n, _c, w, _mc in by_th[tid][:MAX_N]}
        return {}

    before_ok = after_ok = 0
    rescued = []
    total = 0
    for eid, tid in gt:
        ev = {k: v for k, v in ev_ent.get(eid, {}).items() if k not in denylist}
        old = {k: v for k, v in parse_ce(
            next((t["core_entities"] for t in threads
                  if str(t["id"]) == tid), {})) .items()
            if k not in denylist}
        nw = {k: v for k, v in new_ce(tid).items() if k not in denylist}
        if not ev or not old:
            continue
        total += 1

        e0 = tr.weighted_jaccard_normalized(ev, old)
        ok0, _ = tr.entity_gate(e0, len(set(ev) & set(old)))
        e1 = tr.weighted_jaccard_normalized(ev, nw) if nw else 0.0
        ok1, _ = (tr.entity_gate(e1, len(set(ev) & set(nw))) if nw else (False, ""))

        before_ok += ok0
        after_ok += ok1
        if ok1 and not ok0:
            rescued.append((eid, e0, e1))

    print("─" * 78)
    print("【4】影响面：全库强制 rollup 后门控通过率")
    print("─" * 78)
    print(f"  有效配对          {total}")
    print(f"  现状过门控        {before_ok}  ({100*before_ok/max(total,1):.1f}%)")
    print(f"  rollup 后过门控   {after_ok}  ({100*after_ok/max(total,1):.1f}%)")
    print(f"  → 净变化          {after_ok-before_ok:+d} 条 "
          f"({100*(after_ok-before_ok)/max(total,1):+.1f}pp)")
    print()
    if rescued:
        print("  净新增过门控样本（前 10）：")
        for eid, e0, e1 in rescued[:10]:
            print(f"    E {e0:.4f} → {e1:.4f}")
    lost = before_ok - sum(1 for eid, tid in gt
                           if True)  # placeholder
    print()
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
