#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-5c 修正版：core_entities 权重压平（只改权重，不动实体集合）。

依据 diag_rollup_ablation 结论：
    A 现状（5实体·累加权重）  61.7%  ← 基准
    B rollup（10实体·压平）   50.1%  ← 扩池有害
    D 仅压权重（5实体·压平）  64.2%  ← 本脚本方案 (+2.5pp)

原理：thread_profile._load_chapter_entities 的 SQL 已经用
    MAX(CASE WHEN weight >= :core THEN :core ELSE weight END)
把权重钉死在 {1, 3}。现存 23 条线权重为 21/8/13/7/5 等累加值，
是旧逻辑遗留，从未被 _refresh 覆盖。本脚本把它们对齐到
_refresh 会产出的形态，等价于"补跑一次 rollup，但不扩实体数"。

★ 为什么不直接调 refresh_thread_profile()：
    它会把实体数扩到 THREAD_MAX_CORE_ENTITIES=10，
    实测反而 −11.6pp（扩池稀释 inter）。故只压权重。

用法：
    python flatten_core_weights.py          # dry-run，只打印对比
    python flatten_core_weights.py --apply  # 写库
"""
from __future__ import annotations

import argparse
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


def flatten(ce: dict) -> dict:
    """累加权重 → {1, 3}。

    映射口径与 _load_chapter_entities 一致：
        原权重 >= 2（覆盖 ≥2 章）→ CORE_W(3)
        原权重 == 1             → 1
    """
    return {k: (CORE_W if int(v) >= 2 else 1) for k, v in ce.items()}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写库")
    args = ap.parse_args()

    async with async_session() as s:
        threads = (await s.execute(text(
            "SELECT id, title, chapter_count, core_entities "
            "FROM threads ORDER BY chapter_count DESC NULLS LAST"
        ))).mappings().all()

    targets = []
    for t in threads:
        ce = parse_ce(t["core_entities"])
        if not ce:
            continue
        new = flatten(ce)
        if new != ce:
            targets.append((t, ce, new))

    print("=" * 78)
    print(f"P0-5c 权重压平  {'[APPLY 写库]' if args.apply else '[DRY-RUN 不写库]'}")
    print("=" * 78)
    print(f"全库线 {len(threads)} 条，需压平 {len(targets)} 条")
    print(f"映射口径：w >= 2 → {CORE_W} ；w == 1 → 1")
    print()

    print("─" * 78)
    print("【1】前后对比")
    print("─" * 78)
    for t, old, new in targets[:25]:
        cc = t["chapter_count"] or 0
        o = " ".join(f"{k}:{v}" for k, v in list(old.items())[:5])
        n = " ".join(f"{k}:{v}" for k, v in list(new.items())[:5])
        print(f"  章{cc:>3} {str(t['title'])[:26]:<26}")
        print(f"        旧 {o}")
        print(f"        新 {n}")
    if len(targets) > 25:
        print(f"  ... 另有 {len(targets)-25} 条")
    print()

    # 影响面评估
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
    new_map = {str(t["id"]): new for t, _o, new in targets}
    old_map = {str(t["id"]): parse_ce(t["core_entities"]) for t in threads}

    def score(profiles):
        ok = gained = lost = total = 0
        for eid, tid in gt:
            ev = {k: v for k, v in ev_ent.get(eid, {}).items() if k not in denylist}
            tc = {k: v for k, v in (profiles.get(tid) or {}).items()
                  if k not in denylist}
            if not ev or not tc:
                continue
            total += 1
            e = tr.weighted_jaccard_normalized(ev, tc)
            okk, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
            ok += okk
            if tid in new_map:
                old = {k: v for k, v in old_map.get(tid, {}).items()
                       if k not in denylist}
                if old:
                    e0 = tr.weighted_jaccard_normalized(ev, old)
                    ok0, _ = tr.entity_gate(e0, len(set(ev) & set(old)))
                    if okk and not ok0:
                        gained += 1
                    elif ok0 and not okk:
                        lost += 1
        return ok, total, gained, lost

    o0, t0, _g, _l = score(old_map)
    merged = dict(old_map)
    merged.update(new_map)
    o1, t1, g1, l1 = score(merged)

    print("─" * 78)
    print("【2】影响面（441 条人工基线配对）")
    print("─" * 78)
    print(f"  压平前  过门控 {o0}/{t0}  {100*o0/max(t0,1):.1f}%")
    print(f"  压平后  过门控 {o1}/{t1}  {100*o1/max(t1,1):.1f}%")
    print(f"  → 净     {o1-o0:+d} 条 ({100*(o1-o0)/max(t1,1):+.1f}pp)   "
          f"新过 +{g1}  新丢 -{l1}")
    print()

    if not args.apply:
        print("  [DRY-RUN] 未写库。确认后加 --apply 执行。")
        print("=" * 78)
        return

    # 写库：用 jsonb 整体覆盖，保留实体集合只换权重
    async with async_session() as s:
        n = 0
        for t, _old, new in targets:
            await s.execute(
                text("UPDATE threads SET core_entities = CAST(:c AS jsonb), "
                     "updated_at = now() WHERE id = :t"),
                {"c": json.dumps(new, ensure_ascii=False), "t": t["id"]},
            )
            n += 1
        await s.commit()

    print(f"  [APPLY] 已写库 {n} 条。")

    # 回读校验
    async with async_session() as s:
        back = (await s.execute(text(
            "SELECT id, core_entities FROM threads"))).mappings().all()
    bad = []
    for r in back:
        ce = parse_ce(r["core_entities"])
        for k, v in ce.items():
            if v not in (1, CORE_W):
                bad.append((str(r["id"]), k, v))
    print(f"  回读校验：越界权重 {len(bad)} 个"
          + ("  → 全部清零 ✓" if not bad else f"  样例={bad[:5]}"))
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
