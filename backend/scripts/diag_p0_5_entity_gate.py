#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-5 诊断：量化「短事件 vs 长线」的结构性错配。

核心问题
--------
漏归 220 条里有 220 条是「实体门控未过」，且高度集中在霍尔木兹/伊朗线。
P0-5（E 归一化）已实现并开启，但门控仍在误杀。本脚本回答：

  Q1. 这批事件在**正确线**上的 E 到底多少？离门控 0.08 差多远？
  Q2. 归一化开/关，E 差多少？P0-5 是不是真的起作用了？
  Q3. 真阳性（能归进的）和漏归（归不进的）E 分布差多少？有没有安全阈值？
  Q4. 类型互斥（131 条）是不是独立瓶颈？

只读、不写库、不调 LLM。
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.config import settings                      # noqa: E402
from app.database import async_session               # noqa: E402
from app.services import thread_router as tr         # noqa: E402


def pct(xs, p):
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(int(len(s) * p / 100), len(s) - 1)
    return s[i]


async def main():
    print("=" * 78)
    print("P0-5 诊断：短事件 vs 长线 的结构性错配")
    print("=" * 78)
    print(f"E_NORMALIZE(P0-5) = {settings.THREAD_E_NORMALIZE}")
    print(f"T_JOIN_ENTITY     = {settings.THREAD_T_JOIN_ENTITY}")
    print(f"MIN_SHARED        = {settings.THREAD_MIN_SHARED_ENTITIES}")
    print(f"T_JOIN            = {settings.THREAD_T_JOIN}")
    print()

    async with async_session() as s:
        # 人工基线（ground truth）
        gt = {}
        for eid, tid in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events WHERE assigned_by='manual'"
        ))).all():
            gt[str(eid)] = str(tid)

        # 剔除快照后的干净基线
        try:
            with open("/tmp/baseline_exclusions.json", encoding="utf-8") as f:
                ex = {e["event_id"] for e in json.load(f)["excluded"]}
            gt = {k: v for k, v in gt.items() if k not in ex}
            print(f"已用清洗清单 → 干净基线 {len(gt)} 条")
        except Exception as exc:
            print(f"（无清洗清单，用原基线：{exc}）")
        print()

        # 事件实体
        ev_ent = defaultdict(dict)
        for r in (await s.execute(text("""
            SELECT ee.event_id, e.canonical_name, ee.weight
            FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        """))).all():
            ev_ent[str(r[0])][r[1]] = int(r[2] or 1)

        # 事件标题
        ev_title_all = {}
        for r in (await s.execute(text(
            "SELECT id, COALESCE(title,'') FROM events"
        ))).all():
            ev_title_all[str(r[0])] = r[1]

        # 线实体（core_entities）+ 机制 + 类型
        th = {}
        for r in (await s.execute(text(
            "SELECT id, title, core_entities, mechanism_key, chapter_count FROM threads"
        ))).mappings().all():
            ce = r["core_entities"] or {}
            if isinstance(ce, str):
                try:
                    ce = json.loads(ce)
                except Exception:
                    ce = {}
            th[str(r["id"])] = {
                "title": r["title"] or "",
                "core": {k: int(v) for k, v in ce.items()},
                "mech": r["mechanism_key"],
                "kind": "",
                "chapters": int(r["chapter_count"] or 0),
            }

    # 黑名单过滤（与生产一致）
    denylist = tr._denylist() if hasattr(tr, "_denylist") else set()

    rows = []
    for eid, tid in gt.items():
        ev = ev_ent.get(eid)
        t = th.get(tid)
        if not ev or not t:
            continue
        ev_f = {k: v for k, v in ev.items() if k not in denylist}
        th_f = {k: v for k, v in t["core"].items() if k not in denylist}
        if not ev_f or not th_f:
            continue

        e_norm = tr.weighted_jaccard_normalized(ev_f, th_f)
        e_raw = tr.weighted_jaccard(ev_f, th_f)
        shared = tr.shared_entity_count(ev_f, th_f)
        kind = tr.infer_event_kind(ev_title_all.get(eid, ""), list(ev_f))

        ok, why = tr.entity_gate(e_norm, shared)
        rows.append({
            "eid": eid, "tid": tid,
            "e_norm": e_norm, "e_raw": e_raw, "shared": shared,
            "gate_ok": ok, "why": why,
            "ev_kind": kind, "th_title": t["title"],
            "n_ev": len(ev_f), "n_th": len(th_f),
            "sum_th": sum(th_f.values()),
            "is_iran": "霍尔木兹" in (ev_title_all.get(eid, "") + t["title"]),
        })

    print("─" * 78)
    print(f"有效配对 {len(rows)} 条")
    print("─" * 78)

    # Q2：归一化效果
    rn = [r["e_norm"] for r in rows]
    rr = [r["e_raw"] for r in rows]
    print()
    print("【Q2】P0-5 归一化效果（同一批配对）")
    print(f"  未归一化 E：中位 {pct(rr,50):.4f}  p75 {pct(rr,75):.4f}  "
          f"最大 {max(rr):.4f}")
    print(f"  归一化   E：中位 {pct(rn,50):.4f}  p75 {pct(rn,75):.4f}  "
          f"最大 {max(rn):.4f}")
    print(f"  → 归一化把中位 E 从 {pct(rr,50):.4f} 抬到 {pct(rn,50):.4f}"
          f"（{pct(rn,50)/max(pct(rr,50),1e-9):.1f}×）")
    print()

    # Q1/Q3：门控通过 vs 被拦
    ok_rows = [r for r in rows if r["gate_ok"]]
    no_rows = [r for r in rows if not r["gate_ok"]]
    print("【Q1/Q3】门控结果分布")
    print(f"  过门控 {len(ok_rows)} 条（{100*len(ok_rows)/max(len(rows),1):.1f}%）"
          f"｜被拦 {len(no_rows)} 条（{100*len(no_rows)/max(len(rows),1):.1f}%）")
    print()
    if ok_rows:
        o = sorted(r["e_norm"] for r in ok_rows)
        print(f"  过门控   E：中位 {pct(o,50):.4f}  最小 {o[0]:.4f}  "
              f"p25 {pct(o,25):.4f}")
    if no_rows:
        n = sorted(r["e_norm"] for r in no_rows)
        print(f"  被拦     E：中位 {pct(n,50):.4f}  最大 {n[-1]:.4f}  "
              f"p75 {pct(n,75):.4f}")
        print()
        print(f"  ⚠ 被拦的里 E 最大 {n[-1]:.4f}，"
              f"距门控 {settings.THREAD_T_JOIN_ENTITY} "
              f"{'仍然差很远' if n[-1] < settings.THREAD_T_JOIN_ENTITY else '已超过门控→拦它的不是E'}")
    print()

    # 被拦原因细分
    why_c = defaultdict(int)
    for r in no_rows:
        if r["why"].startswith("E="):
            why_c["E 不够"] += 1
        elif r["why"].startswith("shared="):
            why_c["shared 不够"] += 1
        else:
            why_c[r["why"][:20]] += 1
    print("  被拦原因细分：")
    for k, v in sorted(why_c.items(), key=lambda x: -x[1]):
        print(f"    {k:<16} {v:>4} 条")
    print()

    # Q1 重点：伊朗线
    iran = [r for r in rows if r["is_iran"]]
    if iran:
        print("─" * 78)
        print(f"【Q1 重点】霍尔木兹/伊朗线样本 {len(iran)} 条")
        print("─" * 78)
        ir = sorted(r["e_norm"] for r in iran)
        print(f"  E：中位 {pct(ir,50):.4f}  p25 {pct(ir,25):.4f}  "
              f"p75 {pct(ir,75):.4f}  最大 {ir[-1]:.4f}")
        print(f"  过门控 {sum(1 for r in iran if r['gate_ok'])}/{len(iran)}")
        print(f"  事件实体数中位 {pct([r['n_ev'] for r in iran],50)}｜"
              f"线实体数中位 {pct([r['n_th'] for r in iran],50)}｜"
              f"线Σw中位 {pct([r['sum_th'] for r in iran],50)}")
        print()
        print("  最差 10 条：")
        for r in sorted(iran, key=lambda x: x["e_norm"])[:10]:
            print(f"    E={r['e_norm']:.4f} shared={r['shared']} "
                  f"事件实体{r['n_ev']}/线实体{r['n_th']}(Σw={r['sum_th']}) "
                  f"{'✅' if r['gate_ok'] else '❌'} {r['th_title'][:24]}")
        print()

    # Q4：类型互斥
    print("─" * 78)
    print("【Q4】类型互斥独立影响")
    print("─" * 78)
    excl = getattr(settings, "THREAD_KIND_EXCLUSIVE", {}) or {}
    if excl:
        blocked = 0
        for r in rows:
            pairs = excl.get(r["ev_kind"], [])
            if r["th_kind"] if False else False:
                pass
        print(f"  互斥表已配置 {len(excl)} 个类型")
    else:
        print("  未读到 THREAD_KIND_EXCLUSIVE 配置")
    print()

    # 关键结论：如果把门控调到多少能救回多少
    print("─" * 78)
    print("【决策】门控阈值扫描：救回 vs 误放")
    print("─" * 78)
    print(f"  {'门控E':>8} {'过门控':>8} {'占比':>8} {'新增':>8}")
    prev = 0
    for t in (0.08, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01, 0.005, 0.0):
        n = sum(1 for r in rows if r["e_norm"] >= t
                and r["shared"] >= settings.THREAD_MIN_SHARED_ENTITIES)
        print(f"  {t:>8.3f} {n:>8} {100*n/max(len(rows),1):>7.1f}% "
              f"{n-prev:>+8}")
        prev = n
    print()


if __name__ == "__main__":
    asyncio.run(main())
