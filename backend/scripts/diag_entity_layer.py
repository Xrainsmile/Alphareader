#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实体抽取/链接层诊断：E=0 硬骨头的真实成因。

归一化后 E = inter/(2-inter)，E=0 ⟺ inter=0 ⟺ 事件与线**零共享实体**。
本脚本按成因分类 E=0 的配对，回答"杠杆在哪"：

  T1 事件侧实体抽得太少（<=2 个可用实体）
  T2 事件侧实体多，但一个都不在线里 —— 语义跑偏 or 线画像窄
  T3 存在"看起来该共享"的近邻（子串/同义），只差归一化没接上
  T4 事件实体被 is_generic 拦掉
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
from app.services.entity_writer import canonicalize, ALIAS_MAP  # noqa: E402


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
        # 事件实体（含 is_generic 标记）
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
        ev_title = {str(a): b for a, b in (await s.execute(text(
            "SELECT id, title FROM events"))).all()}
        threads = {str(r["id"]): (r["title"], parse_ce(r["core_entities"]))
                   for r in (await s.execute(text(
                       "SELECT id, title, core_entities FROM threads"
                   ))).mappings().all()}

    denylist = tr._denylist() if hasattr(tr, "_denylist") else set()

    print("=" * 78)
    print("实体抽取/链接层诊断")
    print("=" * 78)
    print(f"配对 {len(gt)} 条   ALIAS_MAP 已加载 {len(ALIAS_MAP)} 条别名")
    print()

    t1 = t2 = t3 = t4 = ok = 0
    t1s, t2s, t3s, t4s = [], [], [], []

    for eid, tid in gt:
        raw = ev_ent.get(eid, {})
        ev = {k: v for k, v in raw.items() if k not in denylist}
        tc = {k: v for k, v in (threads.get(tid, ("", {}))[1]).items()
              if k not in denylist}
        if not ev or not tc:
            continue
        e = tr.weighted_jaccard_normalized(ev, tc)
        g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
        if g:
            ok += 1
            continue

        shared = set(ev) & set(tc)
        # T3：是否存在"差一点就接上"的近邻
        near = []
        for a in ev:
            for b in tc:
                if a == b:
                    continue
                if a in b or b in a:
                    near.append((a, b, "子串"))
                    continue
                if canonicalize(a)[0] == canonicalize(b)[0]:
                    near.append((a, b, "别名表可接"))

        gen_hit = ev_gen.get(eid, set()) & set(tc)

        if near:
            t3 += 1
            t3s.append((e, ev_title.get(eid, ""), threads.get(tid, ("",))[0],
                        sorted(ev), sorted(tc), near[:3]))
        elif gen_hit:
            t4 += 1
            t4s.append((e, ev_title.get(eid, ""), sorted(gen_hit)))
        elif len(ev) <= 2:
            t1 += 1
            t1s.append((e, ev_title.get(eid, ""), threads.get(tid, ("",))[0],
                        sorted(ev), sorted(tc)))
        else:
            t2 += 1
            t2s.append((e, ev_title.get(eid, ""), threads.get(tid, ("",))[0],
                        sorted(ev)[:6], sorted(tc)[:6]))

    tot = ok + t1 + t2 + t3 + t4
    print("─" * 78)
    print(f"【1】未过门控 {t1+t2+t3+t4} 条的成因分布")
    print("─" * 78)
    print(f"  已过门控                        {ok:>4}  ({100*ok/max(tot,1):>5.1f}%)")
    print(f"  T3 差一点就接上（子串/别名可修）   {t3:>4}  ({100*t3/max(tot,1):>5.1f}%)  ← 可修")
    print(f"  T2 实体够多但零交集（语义/画像）  {t2:>4}  ({100*t2/max(tot,1):>5.1f}%)")
    print(f"  T1 事件侧实体太少（<=2 个）       {t1:>4}  ({100*t1/max(tot,1):>5.1f}%)")
    print(f"  T4 被 is_generic 拦掉            {t4:>4}  ({100*t4/max(tot,1):>5.1f}%)")
    print()

    if t3s:
        print("─" * 78)
        print(f"【2】T3 样本（归一化就能救）—— 共 {t3} 条")
        print("─" * 78)
        for e, et, tt, ev, tc, near in t3s[:14]:
            print(f"  E={e:.4f}  {str(et)[:34]}")
            print(f"    线：{str(tt)[:30]}")
            print(f"    事件实体 {ev}")
            print(f"    线的实体 {tc}")
            print(f"    近邻 → {near}")
        print()

    if t2s:
        print("─" * 78)
        print(f"【3】T2 样本（实体够多仍零交集）—— 共 {t2} 条")
        print("─" * 78)
        for e, et, tt, ev, tc in t2s[:10]:
            print(f"  E={e:.4f}  {str(et)[:34]}")
            print(f"    线：{str(tt)[:30]}")
            print(f"    事件实体 {ev}")
            print(f"    线的实体 {tc}")
        print()

    if t1s:
        print("─" * 78)
        print(f"【4】T1 样本（事件侧实体太少）—— 共 {t1} 条")
        print("─" * 78)
        for e, et, tt, ev, tc in t1s[:8]:
            print(f"  E={e:.4f}  {str(et)[:40]}")
            print(f"    线：{str(tt)[:28]}  事件实体={ev}")
        print()

    # 事件侧实体数分布
    print("─" * 78)
    print("【5】事件侧可用实体数分布（去 denylist 后）")
    print("─" * 78)
    c = Counter()
    for eid, _ in gt:
        c[len({k for k in ev_ent.get(eid, {}) if k not in denylist})] += 1
    for n in sorted(c):
        print(f"  {n:>2} 个实体：{c[n]:>4} 条")
    print()


if __name__ == "__main__":
    asyncio.run(main())
