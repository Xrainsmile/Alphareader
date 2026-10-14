#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方向一·第三步：语义特征可行性验证（纯只读）。

已知（来自 diag_thread_typology.py）：
    实体型线召回 83.3%，主题型线召回 57.0%，差 26.3pp。
    主题型漏归 84% 卡在实体门控 E。

本步要回答一个**决定性**问题：
    给每条线建一个「语义原型向量」= 线内人工事件 embedding 的质心，
    用 cos(事件向量, 原型) 排序，能不能把正确线排到第一？

如果能 → 语义层有救，方向二值得做。
如果不能 → 问题不在特征，在 embedding 质量/门控，得换思路。

注意：本步**不改任何阈值**，只测特征的判别力（rank 能力）。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict, Counter

import numpy as np
from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-sup", type=int, default=3)
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    async with async_session() as s:
        # 人工基线
        gt = defaultdict(set)
        for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all():
            gt[str(a)].add(str(b))

        titles = {str(r[0]): r[1] for r in (await s.execute(text(
            "SELECT id, title FROM threads"))).all()}

        ev = {str(r[0]): (str(r[1] or ""), np.asarray(r[2], dtype=np.float32))
              for r in (await s.execute(text(
                  "SELECT id, title, event_embedding FROM news "
                  "WHERE event_id IS NOT NULL AND event_embedding IS NOT NULL"))).all()
              if r[2] is not None}

    print("=" * 88)
    print("语义原型可行性验证（线原型 = 线内人工事件 embedding 质心）")
    print("=" * 88)
    print(f"  有 embedding 的事件      {len(ev)}")
    print(f"  有人工基线的事件         {len(gt)}")
    print()

    # 建线级成员：thread -> [event_id]
    members = defaultdict(list)
    for e, ts in gt.items():
        for t in ts:
            members[t].append(e)

    # 线原型：留一法（LOO）——评估时排除被测事件自身，避免自泄露
    proto_full, cands = {}, {}
    for t, es in members.items():
        vs = [ev[e][1] for e in es if e in ev]
        if len(vs) < args.min_sup:
            continue
        M = np.stack(vs)
        M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
        proto_full[t] = M.mean(axis=0)
        cands[t] = es

    print(f"  可用线（成员>= {args.min_sup} 且有向量）  {len(cands)}")
    print()

    hit1 = hit3 = 0
    total = 0
    per_line = defaultdict(lambda: [0, 0, 0])  # tid: [hit1, hit3, n]
    sim_gap = []

    for tid, es in cands.items():
        for e in es:
            if e not in ev:
                continue
        # LOO：重建原型（排除 e）
        for e in es:
            if e not in ev:
                continue
            v = ev[e][1]
            v = v / (np.linalg.norm(v) + 1e-9)
            sims = {}
            for t2, es2 in cands.items():
                vs = [ev[x][1] for x in es2 if x in ev and x != e]
                if len(vs) < args.min_sup:
                    continue
                M = np.stack(vs)
                M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
                p = M.mean(axis=0)
                p = p / (np.linalg.norm(p) + 1e-9)
                sims[t2] = float(v @ p)
            if len(sims) < 2:
                continue
            order = sorted(sims.items(), key=lambda x: -x[1])
            total += 1
            per_line[tid][2] += 1
            if order[0][0] == tid:
                hit1 += 1
                per_line[tid][0] += 1
            if tid in [x[0] for x in order[:3]]:
                hit3 += 1
                per_line[tid][1] += 1
            # 正确线相似度 - 最优错误线相似度
            best_wrong = max((v2 for k2, v2 in sims.items() if k2 != tid), default=0)
            sim_gap.append(sims.get(tid, 0) - best_wrong)

    print("─ 语义原型的排序判别力（越高越好）─")
    print(f"  Top-1 命中率   {hit1}/{total}  = {100*hit1/max(total,1):.1f}%")
    print(f"  Top-3 命中率   {hit3}/{total}  = {100*hit3/max(total,1):.1f}%")
    if sim_gap:
        g = np.array(sim_gap)
        print(f"  正确线 vs 最优错误线 相似度差：均值 {g.mean():+.4f}  "
              f"中位 {np.median(g):+.4f}  正值占比 {(g>0).mean()*100:.1f}%")
    print()

    print("─ 各线 Top-1 ─")
    rows = sorted(per_line.items(), key=lambda x: -x[1][2])
    for tid, (h1, h3, n) in rows[:args.show * 2]:
        print("  {:28} n={:>3}  Top1={:>5.0%}  Top3={:>5.0%}".format(
            titles.get(tid, "?")[:26], n, h1 / max(n, 1), h3 / max(n, 1)))
    print()

    # 与实体型基线对比
    print("=" * 88)
    print("结论判据：")
    print("  若 Top-1 显著高于 57.0%（主题型实体召回）→ 语义层有救")
    print("  若 Top-1 接近或低于 57.0%               → 语义层不是答案")
    print("=" * 88)


if __name__ == "__main__":
    asyncio.run(main())
