#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-7a 诊断：重刷两条 AI 线的 core_entities。

现象：这两条线集中了大量 E=0.0000 的未过门控样本。
怀疑：建线时 core_entities 抽进了噪音实体，且被旧 denylist 删过，
      真实信号实体反而没进画像。

本脚本列出：
  1. 线的当前 core_entities（含权重）
  2. 该线**人工基线事件**的实体分布（真实信号来源）
  3. 候选替换：线内高频 ∩ 未进画像 的实体
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
            "SELECT id, title, core_entities, chapter_count FROM threads"
        ))).mappings().all()}

        # 人工基线：event -> thread
        gt = defaultdict(list)
        for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all():
            gt[str(b)].append(str(a))

        # 事件实体（含 generic 标记）
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

        ev_title = dict((await s.execute(text(
            "SELECT id, title FROM events"))).all())

    blocked = tr._denylist()

    print("=" * 82)
    print("P0-7a 诊断：AI 两条线的实体画像")
    print("=" * 82)

    for tid, t in threads.items():
        title = str(t["title"] or "")
        if not any(k in title for k in TARGETS):
            continue
        ce = parse_ce(t["core_entities"])
        evs = gt.get(tid, [])

        print()
        print("─" * 82)
        print(f"▎{title}   (章节 {t['chapter_count']}，人工基线事件 {len(evs)})")
        print("─" * 82)
        print(f"  当前 core_entities（{len(ce)}）：")
        for k, v in sorted(ce.items(), key=lambda x: -x[1]):
            flag = " [被deny]" if k in blocked else ""
            print(f"      {k:<26} w={v}{flag}")
        print()

        # 线内事件的实体分布
        cnt = Counter()
        wsum = Counter()
        for eid in evs:
            for name, w in ev_ent.get(eid, {}).items():
                if name in ev_gen.get(eid, set()):
                    continue
                cnt[name] += 1
                wsum[name] += w
        print(f"  线内人工事件实体分布（前 18，按章数）：")
        for name, c in cnt.most_common(18):
            ince = "  ✅已在画像" if name in ce else ""
            g = "  [generic]"
            print(f"      {name:<26} {c:>2}章  Σw={wsum[name]:<4}{ince}{g if name in ev_gen.get(eid,set()) else ''}")
        print()

        # 候选：高频但不在画像
        cand = [(n, c, wsum[n]) for n, c in cnt.most_common(30)
                if n not in ce and n not in blocked]
        print(f"  候选新增（高频但不在画像，前 12）：")
        for n, c, w in cand[:12]:
            print(f"      {n:<26} {c:>2}章  Σw={w}")
        print()

        # 该线未过门控的事件
        print(f"  未过门控的事件：")
        for eid in evs:
            ev = {k: v for k, v in ev_ent.get(eid, {}).items()
                  if k not in ev_gen.get(eid, set()) and k not in blocked}
            evc = {}
            for k, v in ev.items():
                c = canonicalize(k)[0]
                evc[c] = max(evc.get(c, 0), v)
            tc = tr._thread_entity_weights(t["core_entities"])
            if not evc or not tc:
                continue
            e = tr.weighted_jaccard_normalized(evc, tc)
            g, _ = tr.entity_gate(e, len(set(evc) & set(tc)))
            if not g:
                ttl = str(ev_title.get(__import__("uuid").UUID(eid), ""))[:34]
                print(f"      E={e:.4f}  事件实体={sorted(evc)}")
                print(f"              {ttl}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
