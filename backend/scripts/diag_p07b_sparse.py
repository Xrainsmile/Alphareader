#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-7b 量化：事件侧实体稀疏的真实规模与根因。

对比三个数字：
    A  news.entities  —— 抽取层产出（受 MAX_ITEMS=5 / MIN_SCORE=5 限制）
    B  event_entities —— 落库结果（整簇并集）
    C  人工基线线的 core_entities

若 A 远大于 B → 说明并集/落库环节丢实体
若 A 本身就 ≤2 → 说明**抽取层**就是天花板（需改 prompt/上限）
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict, Counter

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
        gt_pairs = [(str(a), str(b)) for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all()]

        # A: news.entities（整簇并集，模拟 _collect_cluster_entities）
        cluster_ent = {}
        for r in (await s.execute(text("""
            SELECT id, related_to_id, entities FROM news
            WHERE entities IS NOT NULL AND array_length(entities,1) > 0
        """))).all():
            cid = str(r[1]) if r[1] else str(r[0])
            cluster_ent.setdefault(cid, set()).update(
                [x for x in (r[2] or []) if x])

        # B: event_entities 落库
        ev_ent = defaultdict(dict)
        ev_gen = defaultdict(set)
        for r in (await s.execute(text("""
            SELECT ee.event_id, e.canonical_name, ee.weight,
                   COALESCE(e.is_generic,false)
            FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        """))).all():
            ev_ent[str(r[0])][r[1]] = int(r[2] or 1)
            if r[3]:
                ev_gen[str(r[0])].add(r[1])

        threads = {str(r["id"]): parse_ce(r["core_entities"])
                   for r in (await s.execute(text(
                       "SELECT id, core_entities FROM threads"))).mappings().all()}

    print("=" * 84)
    print("P0-7b 诊断：事件侧实体稀疏的根因定位")
    print("=" * 84)
    print()

    # A vs B
    a_sizes, b_sizes = [], []
    for eid, tid in gt_pairs:
        a = cluster_ent.get(eid, set())
        b = set(ev_ent.get(eid, {}))
        a_sizes.append(len(a))
        b_sizes.append(len(b))
    import statistics as st
    print("─" * 84)
    print("【1】news.entities(A) vs event_entities(B)")
    print("─" * 84)
    print(f"  A 簇内并集实体数   中位 {st.median(a_sizes):.0f}  "
          f"均值 {st.mean(a_sizes):.1f}  max {max(a_sizes)}")
    print(f"  B 落库实体数       中位 {st.median(b_sizes):.0f}  "
          f"均值 {st.mean(b_sizes):.1f}  max {max(b_sizes)}")
    print(f"  A≤2 的配对 {sum(1 for x in a_sizes if x<=2)}/{len(a_sizes)}  "
          f"({100*sum(1 for x in a_sizes if x<=2)/len(a_sizes):.1f}%)")
    print(f"  B≤2 的配对 {sum(1 for x in b_sizes if x<=2)}/{len(b_sizes)}  "
          f"({100*sum(1 for x in b_sizes if x<=2)/len(b_sizes):.1f}%)")
    print()

    # 未过门控的样本里 A 的分布
    print("─" * 84)
    print("【2】未过门控样本：A 是否也稀疏？")
    print("─" * 84)
    fail_a, fail_b = [], []
    for eid, tid in gt_pairs:
        if tid not in threads:
            continue
        ev = {canonicalize(k)[0]: v for k, v in ev_ent.get(eid, {}).items()
              if k not in ev_gen.get(eid, set())}
        tc = tr._thread_entity_weights(threads[tid])
        if not ev or not tc:
            continue
        e = tr.weighted_jaccard_normalized(ev, tc)
        g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
        if not g:
            fail_a.append(len(cluster_ent.get(eid, set())))
            fail_b.append(len(ev))
    print(f"  未过门控 {len(fail_a)} 条")
    print(f"    A 中位 {st.median(fail_a):.0f}  A≤2 占 "
          f"{100*sum(1 for x in fail_a if x<=2)/max(len(fail_a),1):.1f}%")
    print(f"    B 中位 {st.median(fail_b):.0f}  B≤2 占 "
          f"{100*sum(1 for x in fail_b if x<=2)/max(len(fail_b),1):.1f}%")
    print()

    # 假设：把 A 全部放开（模拟"抽取层给足"）
    print("─" * 84)
    print("【3】模拟：若抽取层给足（用 A 全量替代 B）能救回多少？")
    print("─" * 84)
    ok_base = ok_full = 0
    for eid, tid in gt_pairs:
        if tid not in threads:
            continue
        evb = {canonicalize(k)[0]: v for k, v in ev_ent.get(eid, {}).items()
               if k not in ev_gen.get(eid, set())}
        tcb = tr._thread_entity_weights(threads[tid])
        if evb and tcb:
            e = tr.weighted_jaccard_normalized(evb, tcb)
            g, _ = tr.entity_gate(e, len(set(evb) & set(tcb)))
            ok_base += g
        eva = {canonicalize(x)[0]: 1 for x in cluster_ent.get(eid, set())}
        tca = tr._thread_entity_weights(threads[tid])
        if eva and tca:
            e = tr.weighted_jaccard_normalized(eva, tca)
            g, _ = tr.entity_gate(e, len(set(eva) & set(tca)))
            ok_full += g
    n = len(gt_pairs)
    print(f"  现状（B）              {ok_base}/{n}  {100*ok_base/n:.1f}%")
    print(f"  用 A 全量              {ok_full}/{n}  {100*ok_full/n:.1f}%  "
          f"({ok_full-ok_base:+d})")
    print()
    print("  → 差值就是『抽取层给足』的理论上限收益。")
    print()


if __name__ == "__main__":
    asyncio.run(main())
