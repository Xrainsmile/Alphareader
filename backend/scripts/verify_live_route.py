#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方向一：真实链路只读验证。

⚠️ 为什么不能直接跑 route_event：
   生产 THREAD_ROUTING_SHADOW=False，route_event 会执行
   _apply_routes（写 thread_events）+ maybe_create_thread（建空壳线）。
   maybe_create_thread **不受 shadow 保护**，实测会把真实库写脏。
   本脚本复刻打分链路但跳过全部写库分支，等价于"影子模式 + 跳过 LLM"。

复用 thread_router 的纯函数，保证与生产口径一致：
   is_market_snapshot / infer_event_kind / kind_conflict /
   compute_score / shared_entity_count / entity_gate / time_gap_penalty /
   _load_event_entities / _load_event_mechanisms / _thread_entity_weights /
   _load_candidate_threads

评估口径（这是本轮重点）：
   与人工基线比，分 4 类
     TP  自动归的线 == 人工线
     FP  自动归了，但不在人工线里（误串）
     FN  人工有线，但自动没归上（漏）
     —   人工无线的事件不参与，只看有基线的
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
from app.config import settings                    # noqa: E402
from app.database import async_session             # noqa: E402
from app.services import thread_router as tr       # noqa: E402


async def simulate(session, eid: str, title: str, now_map: dict) -> list[dict]:
    """复刻 route_event 的打分段（无写库、无 LLM）。"""
    ev_ents = await tr._load_event_entities(_uuid.UUID(eid))
    ev_mechs = await tr._load_event_mechanisms(_uuid.UUID(eid))
    excluded = await tr._load_manual_exclusions(_uuid.UUID(eid))
    threads = await tr._load_candidate_threads()

    ev_kind = tr.infer_event_kind(title, list(ev_ents.keys()))
    if tr.is_market_snapshot(title):
        return [{"gate": "market_snapshot", "S": 0.0}]

    now = now_map.get(eid) or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    scored = []
    for t in threads:
        tid = t["id"]
        if tid in excluded:
            continue
        th_kind = tr._infer_thread_kind(t)
        if settings.THREAD_KIND_GATE_ENABLED and tr.kind_conflict(ev_kind, th_kind):
            scored.append({"thread_id": str(tid), "title": t.get("title"),
                           "S": 0.0, "join": False,
                           "gate": f"kind:{ev_kind}/{th_kind}"})
            continue
        th_ents = tr._thread_entity_weights(t.get("core_entities"))
        s, e, m, r = tr.compute_score(
            ev_ents, th_ents, ev_mechs, t.get("mechanism_key"),
            t.get("last_event_at"), now)

        if settings.THREAD_TIME_GAP_ENABLED:
            gap = tr.time_gap_penalty(t.get("last_event_at"), now)
            if gap < 1.0:
                s = s * gap
        shared = tr.shared_entity_count(ev_ents, th_ents)
        passed, why = tr.entity_gate(e, shared)
        if not passed:
            scored.append({"thread_id": str(tid), "title": t.get("title"),
                           "S": round(s, 4), "E": round(e, 4),
                           "join": False, "gate": why})
            continue
        scored.append({"thread_id": str(tid), "title": t.get("title"),
                       "S": round(s, 4), "E": round(e, 4),
                       "M": round(m, 4), "R": round(r, 4),
                       "join": s >= settings.THREAD_T_JOIN, "gate": ""})

    scored.sort(key=lambda x: x["S"], reverse=True)
    return scored[: settings.THREAD_MAX_LINES_PER_EVENT]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    async with async_session() as s:
        evs = (await s.execute(text("""
            SELECT id, title, last_updated_at FROM events
            ORDER BY last_updated_at DESC NULLS LAST
            LIMIT :lim OFFSET :off
        """), {"lim": args.limit, "off": args.offset})).mappings().all()

        gt = defaultdict(set)
        for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all():
            gt[str(a)].add(str(b))

        titles = {str(r[0]): r[1] for r in (await s.execute(text(
            "SELECT id, title FROM threads"))).all()}

    now_map = {}
    for r in evs:
        eid = str(r["id"])
        title = str(r["title"] or "")
        ts = r["last_updated_at"]
        if ts is not None:
            now_map[eid] = ts.replace(tzinfo=timezone.utc) \
                if ts.tzinfo is None else ts

    TP = FP = FN = 0
    fplist, fnlist, tplist = [], [], []
    block = Counter()

    for r in evs:
        eid = str(r["id"])
        title = str(r["title"] or "")
        async with async_session() as s2:
            scored = await simulate(s2, eid, title, now_map)
        hits = [x for x in scored if x.get("join")]
        hit_ids = {x["thread_id"] for x in hits if x.get("thread_id")}
        manual = gt.get(eid, set())

        if not manual:
            # 无人工基线：只看是否乱归（FP 观察，不计入分母）
            continue

        if hit_ids & manual:
            TP += 1
            tplist.append((title, sorted(manual & hit_ids),
                           sorted(hit_ids - manual)))
        else:
            FN += 1
            g = Counter(x.get("gate", "") for x in scored)
            top_gate = g.most_common(1)[0][0] if g else ""
            if top_gate.startswith("kind:"):
                block["类型互斥"] += 1
            elif "E=" in top_gate:
                block["实体门控E"] += 1
            elif "shared" in top_gate:
                block["共现数不足"] += 1
            elif top_gate == "market_snapshot":
                block["日频快照"] += 1
            else:
                block[f"S未达阈值"] += 1
            fnlist.append((title, sorted(manual),
                           round(max((x["S"] for x in scored), default=0), 4),
                           top_gate))
        if hit_ids - manual:
            FP += 1
            fplist.append((title, sorted(manual), sorted(hit_ids - manual)))

    n = TP + FN
    print("=" * 84)
    print("方向一：真实链路只读验证（与人工基线对照）")
    print("=" * 84)
    print(f"  有人工基线的事件   {n}")
    print(f"  ✅ TP 归对         {TP}  ({100*TP/max(n,1):.1f}%)")
    print(f"  ❌ FN 漏归         {FN}  ({100*FN/max(n,1):.1f}%)")
    print(f"  ⚠️  FP 误串        {FP}  (含部分对但多归的)")
    print()
    print("─ 漏归(FN)的拦截原因分布 ─")
    for k, v in block.most_common():
        print(f"      {k:<18} {v:>4}  ({100*v/max(FN,1):.1f}%)")
    print()

    print(f"─ FP 误串样本（前 {args.show}）─")
    for t, m, w in fplist[:args.show]:
        print(f"  人工: {[titles.get(x,'?')[:20] for x in m]}")
        print(f"  误串: {[titles.get(x,'?')[:20] for x in w]}")
        print(f"  事件: {t[:40]}")
        print()
    print(f"─ FN 漏归样本（前 {args.show}）─")
    for t, m, s, g in fnlist[:args.show]:
        print(f"  S={s}  {g}")
        print(f"  应在: {[titles.get(x,'?')[:22] for x in m]}")
        print(f"  事件: {t[:40]}")
        print()
    print(f"─ TP 归对样本（前 5）─")
    for t, m, w in tplist[:5]:
        print(f"  {[titles.get(x,'?')[:22] for x in m]}  ← {t[:36]}")


if __name__ == "__main__":
    asyncio.run(main())
