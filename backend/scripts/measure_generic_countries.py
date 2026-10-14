#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量化：把「美国/中国/日本/欧洲」从 is_generic 里放出来，收益与风险。

背景：GENERIC_ENTITIES 把国家名划为"泛化实体"，_load_event_entities 在
SQL 层就 WHERE is_generic = false 过滤掉。但世界线产品里，
「美国 vs 伊朗」恰恰是争夺标的——霍尔木兹线的 core_entities 就有「美国」。
实测这道过滤吃掉了 18 条（67.6% → 63.5%）。

风险：放出来后可能把无关事件串成一条线（原设计意图）。
本脚本同时测「收益」与「误串风险」：
  收益 = 人工基线配对过门控数
  风险 = 非本线事件是否能过（取每条线 top1 候选里不属于人工基线的比例）
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid as _uuid
from collections import defaultdict

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session            # noqa: E402
from app.services import thread_router as tr      # noqa: E402
from app.services.entity_writer import canonicalize  # noqa: E402

COUNTRIES = {"美国", "中国", "欧洲", "日本"}


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

    def build(d, extra_pass: set[str]):
        out = {}
        for k, v in d.items():
            if k in blocked:
                continue
            c = canonicalize(k)[0]
            if c in blocked:
                continue
            out[c] = max(out.get(c, 0), v)
        return out

    def run(extra_pass):
        ok = total = 0
        for eid, tid in gt:
            if tid not in threads:
                continue
            gen = ev_gen.get(eid, set())
            ev0 = {k: v for k, v in ev_all.get(eid, {}).items()
                   if k not in gen or k in extra_pass}
            ev = build(ev0, extra_pass)
            tc = build(threads[tid][1], extra_pass)
            if not ev or not tc:
                continue
            total += 1
            e = tr.weighted_jaccard_normalized(ev, tc)
            g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
            ok += g
        return ok, total

    # 误串风险：把每条事件与**所有**线比对，看放出国家名后
    # 非人工基线线过门控的比例是否上升
    def risk(extra_pass):
        cross = tot = 0
        gt_map = defaultdict(set)
        for e, t in gt:
            gt_map[e].add(t)
        for eid in list({e for e, _ in gt}):
            gen = ev_gen.get(eid, set())
            ev0 = {k: v for k, v in ev_all.get(eid, {}).items()
                   if k not in gen or k in extra_pass}
            ev = build(ev0, extra_pass)
            if not ev:
                continue
            for tid, (_t, ce) in threads.items():
                if tid in gt_map.get(eid, set()):
                    continue
                tc = build(ce, extra_pass)
                if not tc:
                    continue
                tot += 1
                e = tr.weighted_jaccard_normalized(ev, tc)
                g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
                if g:
                    cross += 1
        return cross, tot

    print("=" * 78)
    print("国家名放出 is_generic 的收益 / 风险")
    print("=" * 78)
    print()

    base_ok, base_tot = run(set())
    base_c, base_ct = risk(set())
    print("─" * 78)
    print("【1】收益（人工基线过门控）")
    print("─" * 78)
    print(f"  现状（国家名被过滤）        {base_ok}/{base_tot}  "
          f"{100*base_ok/max(base_tot,1):>5.1f}%")
    ok1, t1 = run(COUNTRIES)
    print(f"  放出 美/中/欧/日            {ok1}/{t1}  "
          f"{100*ok1/max(t1,1):>5.1f}%   ({ok1-base_ok:+d})")
    print()

    print("─" * 78)
    print("【2】风险（误串：非本线事件过门控的占比，越低越好）")
    print("─" * 78)
    print(f"  现状                        {base_c}/{base_ct}  "
          f"{100*base_c/max(base_ct,1):>5.2f}%")
    c1, ct1 = risk(COUNTRIES)
    print(f"  放出 美/中/欧/日            {c1}/{ct1}  "
          f"{100*c1/max(ct1,1):>5.2f}%   ({100*(c1/max(ct1,1)-base_c/max(base_ct,1)):+.2f}pp)")
    print()

    print("─" * 78)
    print("【3】逐个国家拆解")
    print("─" * 78)
    for c in sorted(COUNTRIES):
        okc, tc = run({c})
        cc, ctc = risk({c})
        print(f"  仅放出 {c:<4}  收益 {okc-base_ok:>+3} 条   "
              f"误串 {100*(cc/max(ctc,1)-base_c/max(base_ct,1)):+.2f}pp")
    print()


if __name__ == "__main__":
    asyncio.run(main())
