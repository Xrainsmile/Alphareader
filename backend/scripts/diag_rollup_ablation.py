#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-5c 变量分离：rollup 让 E 变差，到底是谁的锅？

归一化 Jaccard 的数学性质：
    两侧各除以自身 Σw 后，Σmin + Σmax = Σa + Σb = 1 + 1 = 2
    ⇒  E = inter / (2 - inter)     ← E 仅由 inter 决定，且单调
    ⇒  inter = Σ_shared min(a_k, b_k)
    ⇒  给线加实体 → 线的 Σw 变大 → 已有实体的**份额**被稀释 → inter 掉 → E 掉

所以"扩实体池"在归一化下是**双刃剑**：能多接住事件实体（+），
但会稀释老实体的份额（−）。本实验把两个变量拆开：

    A  现状（5 实体，累加权重 21/8/13）      —— 未 rollup
    B  rollup（10 实体，权重压成 {1,3}）     —— 代码"正确"行为
    C  仅扩数量（10 实体，保留累加权重）      —— 分离"实体数"
    D  仅压权重（5 实体，权重 {1,3}）        —— 分离"权重扁平化"
    E  实体数扫描（3/5/7/10/15/20，累加权重） —— 找最优点
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
            "SELECT id, title, core_entities FROM threads"))).mappings().all()
        gt = [(str(a), str(b)) for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all()]
        # 线内实体的真实章节覆盖数（= 累加权重来源）
        rows = (await s.execute(text("""
            SELECT te.thread_id, e.canonical_name,
                   COUNT(DISTINCT te.event_id) AS chapter_cnt,
                   MAX(COALESCE(e.mention_count,1)) AS mc
            FROM thread_events te
            JOIN event_entities ee ON ee.event_id = te.event_id
            JOIN entities e ON e.id = ee.entity_id
            WHERE COALESCE(e.is_generic,false) = false
            GROUP BY te.thread_id, e.canonical_name
            ORDER BY te.thread_id, chapter_cnt DESC, mc DESC
        """))).all()
        ev_ent = defaultdict(dict)
        for r in (await s.execute(text("""
            SELECT ee.event_id, e.canonical_name, ee.weight
            FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        """))).all():
            ev_ent[str(r[0])][r[1]] = int(r[2] or 1)

    # thread -> [(name, chapter_cnt)]
    pool = defaultdict(list)
    for tid, name, cnt, mc in rows:
        pool[str(tid)].append((name, int(cnt)))

    old_ce = {str(t["id"]): parse_ce(t["core_entities"]) for t in threads}
    denylist = tr._denylist() if hasattr(tr, "_denylist") else set()

    def build(tid, n, mode):
        """mode: 'acc' 用累加章节数 / 'flat' 压成 {1,3}"""
        src = pool.get(tid, [])
        if not src:
            return {}
        top = src[:n]
        if mode == "acc":
            return {k: max(c, 1) for k, c in top}
        return {k: (CORE_W if c >= 2 else 1) for k, c in top}

    def evaluate(profiles, label):
        ok = lost = gained = total = 0
        e_sum = 0.0
        for eid, tid in gt:
            ev = {k: v for k, v in ev_ent.get(eid, {}).items() if k not in denylist}
            tc = {k: v for k, v in (profiles.get(tid) or {}).items()
                  if k not in denylist}
            old = {k: v for k, v in old_ce.get(tid, {}).items() if k not in denylist}
            if not ev or not old or not tc:
                continue
            total += 1
            e1 = tr.weighted_jaccard_normalized(ev, tc)
            ok1, _ = tr.entity_gate(e1, len(set(ev) & set(tc)))
            e0 = tr.weighted_jaccard_normalized(ev, old)
            ok0, _ = tr.entity_gate(e0, len(set(ev) & set(old)))
            e_sum += e1
            ok += ok1
            if ok1 and not ok0:
                gained += 1
            if ok0 and not ok1:
                lost += 1
        rate = 100 * ok / max(total, 1)
        print(f"  {label:<34} 过门控 {ok:>3}/{total}  {rate:>5.1f}%   "
              f"中位E≈{e_sum/max(total,1):.4f}   新+{gained:<3} 丢-{lost}")
        return ok, rate

    print("=" * 78)
    print("P0-5c 变量分离实验")
    print("=" * 78)
    print(f"归一化 Jaccard 下 E = inter/(2-inter)，inter 越大 E 越大")
    print(f"配对总数 {len(gt)}")
    print()

    # 基线：现状
    print("─" * 78)
    print("【1】A/B/C/D 四组对照")
    print("─" * 78)
    evaluate({str(t["id"]): parse_ce(t["core_entities"]) for t in threads},
             "A 现状（5实体·累加权重）")
    evaluate({str(t["id"]): build(str(t["id"]), 10, "flat") for t in threads},
             "B rollup（10实体·压成{1,3}）")
    evaluate({str(t["id"]): build(str(t["id"]), 10, "acc") for t in threads},
             "C 仅扩数量（10实体·累加权重）")
    evaluate({str(t["id"]): build(str(t["id"]), 5, "flat") for t in threads},
             "D 仅压权重（5实体·{1,3}）")
    print()

    print("─" * 78)
    print("【2】实体数扫描（累加权重）")
    print("─" * 78)
    for n in (3, 5, 7, 10, 15, 20, 30):
        evaluate({str(t["id"]): build(str(t["id"]), n, "acc") for t in threads},
                 f"  累加权重 · top{n}")
    print()

    print("─" * 78)
    print("【3】实体数扫描（压平权重 {1,3}）")
    print("─" * 78)
    for n in (3, 5, 7, 10, 15, 20, 30):
        evaluate({str(t["id"]): build(str(t["id"]), n, "flat") for t in threads},
                 f"  压平权重 · top{n}")
    print()

    print("─" * 78)
    print("【4】诊断：为何扩池会稀释")
    print("─" * 78)
    tid = max(pool, key=lambda t: len(pool[t]))
    src = pool[tid][:20]
    tot10 = sum(c for _, c in src[:10]) or 1
    tot5 = sum(c for _, c in src[:5]) or 1
    print(f"  样例线 thread={tid[:8]}  实体池 {len(pool[tid])} 个")
    print(f"  top5  Σw={tot5:<4} top1 份额={src[0][1]/tot5:.3f}  ({src[0][0]})")
    print(f"  top10 Σw={tot10:<4} top1 份额={src[0][1]/tot10:.3f}  ({src[0][0]})")
    print(f"  → 池从 5 扩到 10，头部实体份额从 {src[0][1]/tot5:.3f} 掉到 "
          f"{src[0][1]/tot10:.3f}，inter 同比缩水 → E 下降")
    print()


if __name__ == "__main__":
    asyncio.run(main())
