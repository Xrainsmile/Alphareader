#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-7a 收尾：只清理确凿噪音实体，不做扩画像。

结论（measure_p07a_expand 实测）：扩 core_entities 是**负收益**——
  线1「AI服务器与光通信硬件链」K=2 时 gain 从 13 掉到 5（−8）。
  复现 P0-5c 的结论：core_entities 这条路已见顶，
  扩实体数会稀释头部实体份额，反而压低 E。

唯一确凿可做的：清掉「ParkDentalPartners」（牙科诊所，与 AI 变现线无关，
建线时的误抽），并顺手验证清理后的收益。

    python fix_p07a_noise.py           # dry-run
    python fix_p07a_noise.py --apply   # 写库
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
from app.services import thread_router as tr      # noqa: E402
from app.services.entity_writer import canonicalize  # noqa: E402

NOISE = {"ParkDentalPartners", "Park Dental Partners",
         "ParkDental", "ParkDentalPartnersInc"}
TARGETS = ("AI应用软件与云厂商变现", "AI服务器与光通信硬件链")


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    async with async_session() as s:
        threads = {str(r["id"]): r for r in (await s.execute(text(
            "SELECT id, title, core_entities FROM threads"))).mappings().all()}
        gt = defaultdict(set)
        for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all():
            gt[str(b)].add(str(a))
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

    print("=" * 80)
    print(f"P0-7a 噪音清理  {'[APPLY]' if args.apply else '[DRY-RUN]'}")
    print("=" * 80)

    for tid, t in threads.items():
        title = str(t["title"] or "")
        if not any(k in title for k in TARGETS):
            continue
        ce = parse_ce(t["core_entities"])
        hit = [k for k in ce if k in NOISE]
        if not hit:
            print(f"\n  {title}: 无噪音实体，跳过。")
            continue

        new_ce = {k: v for k, v in ce.items() if k not in NOISE}
        print(f"\n  ▎{title}")
        print(f"    清理 {hit}  →  {list(new_ce)}")

        # 收益对比
        def gain(ce_dict):
            tc = tr._thread_entity_weights(ce_dict)
            n = 0
            for eid in gt.get(tid, set()):
                ev = {canonicalize(k)[0]: v for k, v in ev_ent.get(eid, {}).items()
                      if k not in ev_gen.get(eid, set())}
                if not ev or not tc:
                    continue
                e = tr.weighted_jaccard_normalized(ev, tc)
                g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
                n += g
            return n

        g0 = gain(ce)
        g1 = gain(new_ce)
        tot = len(gt.get(tid, set()))
        print(f"    本线过门控  {g0}/{tot}  →  {g1}/{tot}   ({g1-g0:+d})")

        if args.apply and g1 >= g0:
            async with async_session() as s2:
                await s2.execute(text(
                    "UPDATE threads SET core_entities = CAST(:ce AS jsonb) "
                    "WHERE id = CAST(:tid AS uuid)"),
                    {"ce": json.dumps(new_ce, ensure_ascii=False), "tid": tid})
                await s2.commit()
            print("    [APPLY] 已写库。")
        elif args.apply:
            print("    [跳过] 清理后收益未提升，保留原值。")

    print()


if __name__ == "__main__":
    asyncio.run(main())
