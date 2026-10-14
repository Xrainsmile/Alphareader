#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方向一·第二步：世界线「实体型 vs 主题型」分类诊断（纯只读）。

假设（待验证）：
    实体 Jaccard 只对「主体型线」（英伟达算力、特斯拉…）有效；
    对「主题型线」（美联储、宏观数据、长端利率…）结构性失效，
    因为这类线的事件之间没有稳定共现主体。

方法：
    1. 聚合到 thread 级：support / TP / FN / FP / recall / precision
    2. 数据驱动分类（不靠标题猜）：
       取该线人工事件的全量实体，算每个实体的「线内覆盖率」
       = 出现该实体的事件数 / 线内事件数
       anchor = 覆盖率 >= ANCHOR_COV 的实体
       - 主体型：anchor 数 >= 2 且 top2 平均覆盖率 >= ANCHOR_TOP2
       - 主题型：其余
    3. 对比两类的 recall，看差异是否显著

注意：eval 用的 simulate 与 verify_live_route.py 完全一致（复用 router 纯函数）。
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

ANCHOR_COV = 0.50
ANCHOR_TOP2 = 0.60


async def simulate(session, eid: str, title: str, now) -> list[dict]:
    """复刻 route_event 打分段（无写库、无 LLM）。"""
    ev_ents = await tr._load_event_entities(_uuid.UUID(eid))
    ev_mechs = await tr._load_event_mechanisms(_uuid.UUID(eid))
    excluded = await tr._load_manual_exclusions(_uuid.UUID(eid))
    threads = await tr._load_candidate_threads()

    ev_kind = tr.infer_event_kind(title, list(ev_ents.keys()))
    if tr.is_market_snapshot(title):
        return [{"gate": "market_snapshot", "S": 0.0}]

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
                           "gate": "kind:" + ev_kind + "/" + th_kind})
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
                       "join": s >= settings.THREAD_T_JOIN, "gate": ""})

    scored.sort(key=lambda x: x["S"], reverse=True)
    return scored[: settings.THREAD_MAX_LINES_PER_EVENT]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0=全部有基线的事件")
    args = ap.parse_args()

    async with async_session() as s:
        gt = defaultdict(set)
        for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all():
            gt[str(a)].add(str(b))

        titles = {str(r[0]): r[1] for r in (await s.execute(text(
            "SELECT id, title FROM threads"))).all()}

        eids = list(gt.keys())
        if args.limit:
            eids = eids[: args.limit]

        # 事件元信息
        meta = {}
        for r in (await s.execute(text(
            "SELECT id, title, last_updated_at FROM events"))).all():
            meta[str(r[0])] = (str(r[1] or ""), r[2])

    # 逐事件跑真实链路
    tp_by, fn_by, fp_by = Counter(), Counter(), Counter()
    fn_gate_by = defaultdict(Counter)

    for i, eid in enumerate(eids):
        title, ts = meta.get(eid, ("", None))
        now = ts or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        async with async_session() as s2:
            scored = await simulate(s2, eid, title, now)

        hits = {x["thread_id"] for x in scored if x.get("join") and x.get("thread_id")}
        manual = gt[eid]

        for t in hits & manual:
            tp_by[t] += 1
        for t in manual - hits:
            fn_by[t] += 1
            g = Counter(x.get("gate", "") for x in scored)
            top_gate = g.most_common(1)[0][0] if g else ""
            if top_gate.startswith("kind:"):
                fn_gate_by[t]["类型互斥"] += 1
            elif "E=" in top_gate:
                fn_gate_by[t]["实体门控E"] += 1
            elif "shared" in top_gate:
                fn_gate_by[t]["共现数不足"] += 1
            elif top_gate == "market_snapshot":
                fn_gate_by[t]["日频快照"] += 1
            else:
                fn_gate_by[t]["S未达阈值"] += 1
        for t in hits - manual:
            fp_by[t] += 1

    # 线内实体锚定度：该线人工事件的实体覆盖率
    async with async_session() as s:
        rows = (await s.execute(text("""
            SELECT ee.event_id, e.canonical_name
            FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        """))).all()
    ev_ents_raw = defaultdict(set)
    for a, b in rows:
        ev_ents_raw[str(a)].add(b)

    results = []
    for tid in set(list(tp_by) + list(fn_by) + list(fp_by) + 
                   [t for s in gt.values() for t in s]):
        members = [e for e, ts_ in gt.items() if tid in ts_]
        support = len(members)
        if support == 0:
            continue
        # 实体覆盖率
        cov = Counter()
        for e in members:
            for nm in ev_ents_raw.get(e, set()):
                cov[nm] += 1
        top = [(n, c / support) for n, c in cov.most_common()]
        anchors = [(n, r) for n, r in top if r >= ANCHOR_COV]
        top2 = sum(r for _, r in top[:2]) / 2 if len(top) >= 2 else 0.0
        is_entity_type = len(anchors) >= 2 and top2 >= ANCHOR_TOP2

        tp, fn, fp = tp_by[tid], fn_by[tid], fp_by[tid]
        recall = tp / support
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        results.append({
            "tid": tid, "title": titles.get(tid, "?"),
            "support": support, "tp": tp, "fn": fn, "fp": fp,
            "recall": recall, "prec": prec,
            "type": "实体型" if is_entity_type else "主题型",
            "anchors": anchors[:4], "top": top[:4],
            "gates": fn_gate_by[tid].most_common(3),
        })

    results.sort(key=lambda x: (x["type"], -x["support"]))

    print("=" * 92)
    print("世界线分类诊断（数据驱动，非标题猜测）")
    print("=" * 92)
    ent = [r for r in results if r["type"] == "实体型"]
    them = [r for r in results if r["type"] == "主题型"]

    def agg(g, name):
        if not g:
            print(f"  {name}: 无")
            return
        sup = sum(r["support"] for r in g)
        tp = sum(r["tp"] for r in g)
        fp = sum(r["fp"] for r in g)
        print(f"  {name:<6} 线数={len(g):<3} support={sup:<4} TP={tp:<4} "
              f"召回={100*tp/sup:5.1f}%  "
              f"精确率={100*tp/max(tp+fp,1):5.1f}%")
        return tp / sup

    r1 = agg(ent, "实体型")
    r2 = agg(them, "主题型")
    print()
    if r1 and r2:
        print(f"  ★ 召回差距：{100*(r1-r2):.1f} 个百分点 "
              f"（实体型 {100*r1:.1f}% vs 主题型 {100*r2:.1f}%）")
        print(f"  ★ 假设{'成立' if r1 - r2 > 0.15 else '不成立/差距过小'}")
    print()

    for name, grp in (("实体型", ent), ("主题型", them)):
        print("─" * 92)
        print(f"[{name}]  {'线名':<26} sup  TP  FN  FP   召回  精确  top实体(覆盖率)")
        print("─" * 92)
        for r in grp:
            tops = " ".join("{}:{:.0%}".format(n, v) for n, v in r["top"][:3])
            print("  {:26} {:>3} {:>3} {:>3} {:>3}  {:>5.0%} {:>5.0%}  {}".format(
                r["title"][:24], r["support"], r["tp"], r["fn"], r["fp"],
                r["recall"], r["prec"], tops[:44]))
        print()

    print("─ 主题型线漏归拦截原因 ─")
    for r in sorted(them, key=lambda x: -x["fn"])[:8]:
        if r["fn"]:
            print("  {:24} FN={}  {}".format(
                r["title"][:22], r["fn"], dict(r["gates"])))


if __name__ == "__main__":
    asyncio.run(main())
