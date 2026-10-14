#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方向二·上线前影子验证：用**真实 thread_router 代码**跑语义路。

与 diag_semantic_proto.py 的区别：
  前者是我自己写的评估脚本（自定义 LOO 逻辑）
  本脚本走 settings.THREAD_SEMANTIC_ENABLED=True → route_event 真实分支，
  验证**生产代码路径**能否复现 76.6%，而不是验证算法本身。

★ 关键差异（必须提前说清）：
  评估脚本用 LOO（每个被测事件都从原型里剔除自己）→ 无自泄露，76.6%
  生产代码直接用 threads.embedding（原型含该事件自身）→ 有自泄露
  因此本脚本的预期是「略高于 76.6%」，它衡量的是**代码正确性**，
  不是**生产真实水位**。生产真实水位须用新事件灰度观察（方案第六步）。

口径：THREAD_ROUTING_SHADOW 强制 True，只留痕不写库。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid as _uuid
from collections import defaultdict, Counter
from datetime import datetime, timezone

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.config import settings               # noqa: E402
from app.database import async_session        # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    # ★ 强制开语义 + 强制影子，绝不写库
    settings.THREAD_SEMANTIC_ENABLED = True
    settings.THREAD_SEMANTIC_LLM_VERIFY = False
    settings.THREAD_ROUTING_SHADOW = True
    settings.THREAD_ROUTING_ENABLED = True

    if not settings.THREAD_ROUTING_SHADOW:
        print("!!! 拒绝执行：必须是影子模式")
        return 1

    from app.services import thread_router as tr

    async with async_session() as s:
        gt = defaultdict(set)
        for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all():
            gt[str(a)].add(str(b))
        meta = {str(r[0]): (str(r[1] or ""), r[2]) for r in (await s.execute(text(
            "SELECT id, title, event_last_updated_at FROM news "
            "WHERE event_id IS NOT NULL"))).all()}
        nproto = (await s.execute(text(
            "SELECT count(*) FROM threads WHERE embedding IS NOT NULL"))).scalar()

    eids = list(gt.keys())
    if args.limit:
        eids = eids[: args.limit]

    print("=" * 88)
    print("上线前影子验证：真实 route_event 语义路")
    print("=" * 88)
    print(f"  有原型线数        {nproto}")
    print(f"  评估事件          {len(eids)}")
    print(f"  ROUTING_SHADOW    {settings.THREAD_ROUTING_SHADOW}  (True=不写库)")
    print()

    tp = hitn = mann = 0
    zero = 0
    by_line = defaultdict(lambda: [0, 0])  # tid: [hit, support]
    no_cand = 0

    for i, eid in enumerate(eids):
        title, ts = meta.get(eid, ("", None))
        now = ts or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        try:
            res = await tr.route_event(_uuid.UUID(eid), reference_at=now)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}] route failed {eid[:8]}: {exc}")
            continue

        hits = {str(x["thread_id"]) for x in res if x.get("join")}
        manual = gt[eid]
        if not res:
            no_cand += 1
        if not hits:
            zero += 1
        tp += len(hits & manual)
        hitn += len(hits)
        mann += len(manual)
        for t in manual:
            by_line[t][1] += 1
            if t in hits:
                by_line[t][0] += 1

    rec = tp / max(mann, 1)
    pre = tp / max(hitn, 1)
    f1 = 2 * pre * rec / max(pre + rec, 1e-9)

    print("─ 真实代码路径结果 ─")
    print(f"  召回   {100*rec:5.1f}%   ({tp}/{mann})")
    print(f"  精确   {100*pre:5.1f}%   ({tp}/{hitn})")
    print(f"  F1     {f1:.3f}")
    print(f"  零归线 {zero} 事件   无候选 {no_cand} 事件")
    print()
    print("─ 对照 ─")
    print("  评估脚本（LOO，无自泄露）   76.6%  ← 生产真实水位参考值")
    print("  规则路（现状）              57.1%")
    print(f"  本脚本（真实代码，有自泄露） {100*rec:.1f}%  ← 应 ≥76.6%，低了说明代码有 bug")
    print()

    print("─ 各线召回（sup>=5）─")
    rows = sorted(by_line.items(), key=lambda x: -x[1][1])
    for tid, (h, sup) in rows:
        if sup >= 5:
            print("  {:30} {:>3}/{:<3} {:>5.0%}".format(
                tid[:8] + "…", h, sup, h / sup))

    print()
    print("=" * 88)
    if rec >= 0.70:
        print("✅ 代码路径正确，可进入灰度（第 5 步）")
    else:
        print("❌ 未达预期，检查 _semantic_route 实现")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
