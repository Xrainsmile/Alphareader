#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-7a 精确测算：给两条 AI 线扩 core_entities 的收益/风险。

关键设计：**必须同时测误串风险**。
上一轮（P0-5c）证明「盲目扩实体数」会稀释头部份额、反而降通过率。
上一轮（P0-6）证明「放美国」收益+8 但误串+1.11pp，性价比不划算。

所以本轮对每个候选扩容量 K 同时报：
    gain   本线过门控增量
    risk   全局误串率变化（该事件 × 所有非本线）

只有 gain>0 且 risk 不涨（或涨得极小）的方案才采纳。
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid as _uuid
from collections import defaultdict, Counter

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session            # noqa: E402
from app.services import thread_router as tr      # noqa: E402
from app.services.entity_writer import canonicalize  # noqa: E402

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
    async with async_session() as s:
        threads = {str(r["id"]): r for r in (await s.execute(text(
            "SELECT id, title, core_entities FROM threads"))).mappings().all()}
        gt = defaultdict(set)
        gt_pairs = []
        for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all():
            gt[str(b)].add(str(a))
            gt_pairs.append((str(a), str(b)))
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

    def ev_clean(eid):
        out = {}
        for k, v in ev_ent.get(eid, {}).items():
            if k in ev_gen.get(eid, set()):
                continue
            c = canonicalize(k)[0]
            out[c] = max(out.get(c, 0), v)
        return out

    def score(ev, tc):
        if not ev or not tc:
            return False
        e = tr.weighted_jaccard_normalized(ev, tc)
        g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
        return g

    def sweep(tid, t):
        ce = parse_ce(t["core_entities"])
        evs = gt.get(tid, set())
        base_ce = {canonicalize(k)[0]: v for k, v in ce.items()}
        base_ce = {k: max(v, base_ce.get(k, 0)) for k, v in base_ce.items()}

        # 线内事件实体频次（作为扩画像候选，按章数）
        cnt = Counter()
        for eid in evs:
            for name in ev_clean(eid):
                cnt[name] += 1
        cands = [n for n, c in cnt.most_common(30)
                 if n not in base_ce or base_ce.get(n, 0) < 3]

        rows = []
        cur = dict(base_ce)
        # K=0 基线
        prev_gain = None
        for K in [0, 2, 3, 5, 8, 12]:
            trial = dict(base_ce)
            for n in cands[:K]:
                trial[n] = max(trial.get(n, 0), 3)
            trial = {k: v for k, v in trial.items()}
            tc = tr._thread_entity_weights(trial)
            gain = sum(1 for eid in evs if score(ev_clean(eid), tc))
            # 误串：本线事件 × 其他线？不，应测"其他事件 × 本线"
            other_evs = [e for e, _ in gt_pairs if e not in evs]
            cross = sum(1 for eid in other_evs if score(ev_clean(eid), tc))
            rows.append((K, gain, cross, len(other_evs), tc))
        return rows, base_ce, cands, evs

    print("=" * 86)
    print("P0-7a 扩画像测算（gain=本线过门控，cross=其他事件误串本线）")
    print("=" * 86)

    for tid, t in threads.items():
        title = str(t["title"] or "")
        if not any(k in title for k in TARGETS):
            continue
        rows, base_ce, cands, evs = sweep(tid, t)
        print()
        print("─" * 86)
        print(f"▎{title}   （本线事件 {len(evs)}，现有画像 {len(base_ce)}）")
        print("─" * 86)
        print(f"  现有画像：{list(base_ce)}")
        print(f"  候选池前12：{cands[:12]}")
        print()
        print(f"  {'K(新增实体数)':<16}{'gain':>10}{'cross':>12}{'cross率':>10}")
        b_g = rows[0][1]
        b_c = rows[0][2]
        for K, gain, cross, tot, tc in rows:
            print(f"  K={K:<14}{gain:>4}/{len(evs)}  {gain-b_g:>+3}   "
                  f"{cross:>4}/{tot}  {100*cross/max(tot,1):>6.2f}%  "
                  f"({100*(cross/max(tot,1)-b_c/max(tot,1)):+.2f}pp)")
        print()


if __name__ == "__main__":
    asyncio.run(main())
