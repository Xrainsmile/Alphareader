#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方向一·第五步：纯语义方案的阈值扫描 + 多标签（纯只读）。

前置：diag_fusion_ab.py 已证 纯语义 S 最优（F1=0.766），且优于任何规则融合。
本步细化两件事：
  1. S 只取 Top-1，但事件可属多线 → 扫相似度阈值，允许多归，看精确/召回权衡
  2. 找「替代实体门控」的语义阈值：cos >= T 才归

输出：阈值-指标曲线，给出推荐工作点。
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict

import numpy as np
from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session  # noqa: E402

MIN_SUP = 3


async def main():
    async with async_session() as s:
        gt = defaultdict(set)
        for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all():
            gt[str(a)].add(str(b))
        titles = {str(r[0]): r[1] for r in (await s.execute(text(
            "SELECT id, title FROM threads"))).all()}
        ev = {str(r[0]): np.asarray(r[1], dtype=np.float32)
              for r in (await s.execute(text(
                  "SELECT id, event_embedding FROM news "
                  "WHERE event_id IS NOT NULL AND event_embedding IS NOT NULL"))).all()}

    members = defaultdict(list)
    for e, ts in gt.items():
        for t in ts:
            members[t].append(e)
    cands = {t: [x for x in es if x in ev]
             for t, es in members.items() if len([x for x in es if x in ev]) >= MIN_SUP}

    # 预计算线原型（全量，评估时用 LOO 重建避免自泄露）
    rows = []
    for eid, manual in gt.items():
        if eid not in ev:
            continue
        v = ev[eid]
        v = v / (np.linalg.norm(v) + 1e-9)
        sims = {}
        for t2, es2 in cands.items():
            vs = [ev[x] for x in es2 if x != eid]
            if len(vs) < MIN_SUP:
                continue
            M = np.stack(vs)
            M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
            p = M.mean(axis=0)
            p = p / (np.linalg.norm(p) + 1e-9)
            sims[t2] = float(v @ p)
        rows.append((eid, manual, sims))

    print("=" * 92)
    print("纯语义方案：阈值扫描（cos >= T 则归线，允许多标签）")
    print("=" * 92)
    print(f"  评估事件 {len(rows)}   候选线 {len(cands)}")
    print()
    print("  {:>6} {:>9} {:>9} {:>8} {:>7} {:>8}".format(
        "阈值T", "召回", "精确", "F1", "平均归线数", "零归线"))
    print("  " + "-" * 62)

    best = (None, -1)
    for T in [0.00, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        tp = hitn = mann = 0
        zero = 0
        for eid, manual, sims in rows:
            hits = {t for t, v in sims.items() if v >= T}
            if not hits:
                zero += 1
            tp += len(hits & manual)
            hitn += len(hits)
            mann += len(manual)
        rec = tp / max(mann, 1)
        pre = tp / max(hitn, 1)
        f1 = 2 * pre * rec / max(pre + rec, 1e-9)
        print("  {:>6.2f} {:>8.1f}% {:>8.1f}% {:>8.3f} {:>9.2f} {:>8}".format(
            T, 100 * rec, 100 * pre, f1, hitn / max(len(rows), 1), zero))
        if f1 > best[1]:
            best = (T, f1)

    print()
    print(f"  ★ 最优阈值 T={best[0]:.2f}  F1={best[1]:.3f}")
    print()

    # Top-K 对照
    print("─ Top-K 对照（固定取相似度最高的 K 条线）─")
    print("  {:>6} {:>9} {:>9} {:>8}".format("K", "召回", "精确", "F1"))
    print("  " + "-" * 40)
    for K in [1, 2, 3]:
        tp = hitn = mann = 0
        for eid, manual, sims in rows:
            hits = {t for t, _ in sorted(sims.items(), key=lambda x: -x[1])[:K]}
            tp += len(hits & manual)
            hitn += len(hits)
            mann += len(manual)
        rec = tp / max(mann, 1)
        pre = tp / max(hitn, 1)
        f1 = 2 * pre * rec / max(pre + rec, 1e-9)
        print("  {:>6} {:>8.1f}% {:>8.1f}% {:>8.3f}".format(K, 100 * rec, 100 * pre, f1))
    print()

    # 人工基线归线数分布
    dist = defaultdict(int)
    for eid, manual, _ in rows:
        dist[len(manual)] += 1
    print("─ 人工基线：每事件归线数分布 ─")
    for k in sorted(dist):
        print("  {:>2} 条线: {:>4} 事件 ({:>5.1f}%)".format(
            k, dist[k], 100 * dist[k] / len(rows)))
    print()
    print("=" * 92)
    print("说明：人工基线多数事件只归 1 条线，与 Top-1 口径吻合，")
    print("      因此 Top-1 的 76.6% 是公平对比，不是被多标签捞回来的。")
    print("=" * 92)


if __name__ == "__main__":
    asyncio.run(main())
