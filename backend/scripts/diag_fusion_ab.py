#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方向一·第四步：实体 vs 语义 融合方案对比（纯只读，不改阈值）。

前置结论：
  - 真实实体链路（含全部门控）  TP 55.4%
  - 语义原型 Top-1             76.6%
  - 主题型漏归 84% 卡在实体门控

本步回答：怎么把语义接进去，收益最大、误伤最小？

对比 4 个方案（同一批事件、同一人工基线）：
  R    纯规则（现状）
  S    纯语义（Top-1，无门控）
  R+S  并集：规则命中 ∪ 语义Top1
  R>S  规则优先，规则无命中时用语义Top1  ← 最保守，不推翻现有判定

口径：gt 是集合（事件可属多线）
  recall    = |hit ∩ manual| / |manual|
  precision = |hit ∩ manual| / |hit|
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid as _uuid
from collections import defaultdict, Counter
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import text

sys.path.insert(0, "/app")
from app.config import settings               # noqa: E402
from app.database import async_session        # noqa: E402
from app.services import thread_router as tr  # noqa: E402

MIN_SUP = 3


async def rule_route(session, eid, title, now):
    """复刻 route_event 打分段（与 verify_live_route.py 一致）。"""
    ev_ents = await tr._load_event_entities(_uuid.UUID(eid))
    ev_mechs = await tr._load_event_mechanisms(_uuid.UUID(eid))
    excluded = await tr._load_manual_exclusions(_uuid.UUID(eid))
    threads = await tr._load_candidate_threads()
    ev_kind = tr.infer_event_kind(title, list(ev_ents.keys()))
    if tr.is_market_snapshot(title):
        return set(), "market_snapshot"
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hits, gates = set(), Counter()
    for t in threads:
        tid = str(t["id"])
        if t["id"] in excluded:
            continue
        th_kind = tr._infer_thread_kind(t)
        if settings.THREAD_KIND_GATE_ENABLED and tr.kind_conflict(ev_kind, th_kind):
            gates["kind"] += 1
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
            gates["gate"] += 1
            continue
        if s >= settings.THREAD_T_JOIN:
            hits.add(tid)
    return hits, gates.most_common(1)[0][0] if gates else ""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=8)
    args = ap.parse_args()

    async with async_session() as s:
        gt = defaultdict(set)
        for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all():
            gt[str(a)].add(str(b))
        titles = {str(r[0]): r[1] for r in (await s.execute(text(
            "SELECT id, title FROM threads"))).all()}
        ev = {str(r[0]): (str(r[1] or ""), np.asarray(r[2], dtype=np.float32), r[3])
              for r in (await s.execute(text(
                  "SELECT id, title, event_embedding, event_last_updated_at "
                  "FROM news WHERE event_id IS NOT NULL "
                  "AND event_embedding IS NOT NULL"))).all()}

    members = defaultdict(list)
    for e, ts in gt.items():
        for t in ts:
            members[t].append(e)
    cands = {t: [x for x in es if x in ev]
             for t, es in members.items() if len([x for x in es if x in ev]) >= MIN_SUP}

    now = datetime.now(timezone.utc)
    stats = defaultdict(lambda: {"tp": 0, "hitn": 0, "mann": 0, "ev": 0})

    for eid, manual in gt.items():
        if eid not in ev:
            continue
        title, vec, ts = ev[eid]
        ref = ts if ts is not None else now
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)

        async with async_session() as s2:
            rhits, _ = await rule_route(s2, eid, title, ref)

        v = vec / (np.linalg.norm(vec) + 1e-9)
        sims = {}
        for t2, es2 in cands.items():
            vs = [ev[x][1] for x in es2 if x != eid]
            if len(vs) < MIN_SUP:
                continue
            M = np.stack(vs)
            M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
            p = M.mean(axis=0)
            p = p / (np.linalg.norm(p) + 1e-9)
            sims[t2] = float(v @ p)
        stop1 = {max(sims, key=sims.get)} if sims else set()

        plans = {
            "R   ": rhits,
            "S   ": stop1,
            "R+S ": rhits | stop1,
            "R>S ": rhits if rhits else stop1,
        }
        for k, hits in plans.items():
            st = stats[k]
            st["ev"] += 1
            st["mann"] += len(manual)
            st["hitn"] += len(hits)
            st["tp"] += len(hits & manual)

    print("=" * 96)
    print("实体 vs 语义 融合方案对比（同一批事件 / 同一人工基线）")
    print("=" * 96)
    print(f"  评估事件数        {stats['R   ']['ev']}")
    print()
    print("  {'方案':<8} {'召回':>8} {'精确':>8} {'F1':>8}   说明")
    print("  " + "-" * 80)
    desc = {
        "R   ": "纯规则（现状基线）",
        "S   ": "纯语义 Top-1（无门控）",
        "R+S ": "并集：规则 ∪ 语义",
        "R>S ": "规则优先，无命中时补语义",
    }
    best = None
    for k in ["R   ", "S   ", "R+S ", "R>S "]:
        st = stats[k]
        rec = st["tp"] / max(st["mann"], 1)
        pre = st["tp"] / max(st["hitn"], 1)
        f1 = 2 * pre * rec / max(pre + rec, 1e-9)
        print("  {:8} {:>7.1f}% {:>7.1f}% {:>8.3f}   {}".format(
            k, 100 * rec, 100 * pre, f1, desc[k]))
        if best is None or f1 > best[1]:
            best = (k, f1)
    print()
    print(f"  ★ 最优方案：{best[0].strip()}  (F1={best[1]:.3f})")
    print()

    # 增量分析
    r, s_ = stats["R   "], stats["S   "]
    print("─ 收益拆解（相对现状 R）─")
    print(f"  R   召回 {100*r['tp']/max(r['mann'],1):.1f}%   精确 {100*r['tp']/max(r['hitn'],1):.1f}%")
    for k in ["S   ", "R+S ", "R>S "]:
        st = stats[k]
        d_rec = st["tp"] / max(st["mann"], 1) - r["tp"] / max(r["mann"], 1)
        d_pre = st["tp"] / max(st["hitn"], 1) - r["tp"] / max(r["hitn"], 1)
        print("  {:5} 召回 {:+.1f}pp   精确 {:+.1f}pp".format(
            k.strip(), 100 * d_rec, 100 * d_pre))
    print()
    print("=" * 96)
    print("判据：")
    print("  R>S 若同时提升召回与精确 → 语义可直接作为「门控救兵」上线")
    print("  R>S 若召回升但精确大幅降 → 需要给语义加阈值，不能直接放行")
    print("=" * 96)


if __name__ == "__main__":
    asyncio.run(main())
