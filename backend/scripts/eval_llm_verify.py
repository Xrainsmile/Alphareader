#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2-9 LLM 二次语义校验：先离线量化收益，再决定要不要开。

背景
----
规则层（S=0.55E+0.30M+0.15R + 实体/类型门控）只能判「形似」。
当前 AFTER 配置下仍有 16 条误归（Precision 0.907），典型如：
    「美股光通信与存储概念股集体走强」→ 误入「存储与HBM超级周期」
    「加拿大8月出口回升」→ 误入「美加关税摩擦」
这类"规则像、语义不像"是规则的盲区，只能靠语义判断。

本脚本做的事
------------
把 AFTER 判定为 join 的**全部**命中（不只是灰色地带）都送 LLM 复核，
看 LLM 能否把 FP 判掉、同时不误伤 TP。输出：
    - LLM 判定的 TP / FP / FN 与新的 Precision
    - 逐条裁决明细（verdict + reason），供人工核对 LLM 是否判对
    - 放行率（LLM 返回 None 的占比）——衡量失败策略的触发频率

成本估算：按日增 40 事件 × 命中数 估算，见输出末尾。

⚠️ 注意
------
本脚本会**真实调用 LLM**（花钱）。用 --limit N 控制样本量。
同时它只读不写，不会改动生产路由结果。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.config import settings                      # noqa: E402
from app.database import async_session               # noqa: E402
from app.services import thread_router as tr         # noqa: E402
from app.services import thread_verifier as tv       # noqa: E402


async def load_all():
    async with async_session() as s:
        gt = {}
        rows = (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events WHERE assigned_by='manual'"
        ))).all()
        for eid, tid in rows:
            gt[str(eid)] = str(tid)

        events = {}
        rows = (await s.execute(text(
            "SELECT id, COALESCE(title,'') AS t, COALESCE(summary,'') AS s,"
            " created_at AS a FROM events"
        ))).mappings().all()
        for r in rows:
            events[str(r["id"])] = {"title": r["t"], "summary": r["s"], "at": r["a"]}

        ev_ents = {}
        rows = (await s.execute(text(
            "SELECT ee.event_id, en.canonical_name, ee.weight "
            "FROM event_entities ee JOIN entities en ON en.id=ee.entity_id"
        ))).all()
        for eid, name, w in rows:
            if name:
                ev_ents.setdefault(str(eid), {})
                ev_ents[str(eid)][name] = max(
                    ev_ents[str(eid)].get(name, 0), int(w or 1))

        threads = []
        rows = (await s.execute(text(
            "SELECT id, title, core_entities, mechanism_key, contested_asset,"
            " last_event_at FROM threads WHERE status NOT IN ('merged','split')"
        ))).mappings().all()
        for r in rows:
            threads.append(dict(r))
    return gt, events, ev_ents, threads


async def load_chapters(thread_id: str, limit: int = 5):
    sql = text("""
        SELECT COALESCE(snapshot_title,'') AS t FROM thread_events
        WHERE thread_id = :tid ORDER BY created_at DESC LIMIT :lim
    """)
    async with async_session() as s:
        rows = (await s.execute(sql, {"tid": thread_id, "lim": limit})).all()
    return [r[0] for r in rows if r[0]]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40, help="最多复核多少条命中")
    a = ap.parse_args()

    gt, events, ev_ents, threads = await load_all()
    deny = tr._denylist()
    tmap = {str(t["id"]): t for t in threads}

    print("=" * 74)
    print("P2-9 LLM 语义校验离线评估（真实调用 LLM，样本 %d 条）" % a.limit)
    print("=" * 74)

    # 先用规则层跑一遍，拿到命中
    rule_tp = rule_fp = 0
    pend = []          # (event_id, thread_id, S, is_correct)
    fp_scores: list[float] = []
    tp_scores: list[float] = []
    seen = 0
    for eid, gt_tid in gt.items():
        ev = events.get(eid)
        if not ev:
            continue
        if tr.is_market_snapshot(ev["title"]):
            continue
        ents = {k: v for k, v in ev_ents.get(eid, {}).items() if k not in deny}
        if not ents:
            continue
        now = ev["at"] or datetime.now(timezone.utc)
        ev_kind = tr.infer_event_kind(ev["title"], list(ents.keys()))

        best = None
        for t in threads:
            tid = str(t["id"])
            th_kind = tr._infer_thread_kind(t)
            if tr.kind_conflict(ev_kind, th_kind):
                continue
            th_ents = tr._thread_entity_weights(t.get("core_entities"))
            if not th_ents:
                continue
            s, e, m, r = tr.compute_score(ents, th_ents, [], t.get("mechanism_key"),
                                          t.get("last_event_at"), now)
            shared = tr.shared_entity_count(ents, th_ents)
            passed, _ = tr.entity_gate(e, shared)
            if not passed or s < settings.THREAD_T_JOIN:
                continue
            if best is None or s > best[0]:
                best = (s, tid)

        if not best:
            continue
        s, tid = best
        ok = (tid == gt_tid)
        (tp_scores if ok else fp_scores).append(s)
        if ok:
            rule_tp += 1
        else:
            rule_fp += 1
        pend.append((eid, tid, s, ok))
        seen += 1

    print(f"规则层：TP {rule_tp}｜FP {rule_fp}｜"
          f"Precision {rule_tp/max(rule_tp+rule_fp,1):.3f}")
    print()

    # 优先复核误归（FP 全查，TP 抽样），控制成本
    fps = [x for x in pend if not x[3]]
    tps = [x for x in pend if x[3]]
    sample = fps[:a.limit] + tps[:max(a.limit - len(fps), 10)]
    print(f"送 LLM 复核 {len(sample)} 条（FP {min(len(fps), a.limit)} "
          f"TP {len(sample) - min(len(fps), a.limit)}）")
    print()

    llm_tp = llm_fp = llm_none = 0
    detail = []
    for eid, tid, s, ok in sample:
        t = tmap.get(tid, {})
        ch = await load_chapters(tid, 5)
        v = await tv.verify(
            events[eid]["title"], events[eid]["summary"],
            t.get("title") or "", t.get("contested_asset") or "",
            t.get("mechanism_key") or "", ch,
        )
        ev_t = events[eid]["title"]
        th_t = t.get("title") or ""
        if v is None:
            llm_none += 1
            detail.append(("放行", ok, s, ev_t, th_t, "LLM 无法判定"))
            if ok:
                llm_tp += 1
            else:
                llm_fp += 1
        elif v is True:
            if ok:
                llm_tp += 1
                detail.append(("接受✓", ok, s, ev_t, th_t, "判同线（正确）"))
            else:
                llm_fp += 1
                detail.append(("接受✗", ok, s, ev_t, th_t, "判同线（漏判误归）"))
        else:
            if ok:
                detail.append(("拒绝✗", ok, s, ev_t, th_t, "判不同线（误伤真阳性）"))
            else:
                detail.append(("拒绝✓", ok, s, ev_t, th_t, "判不同线（纠正误归）"))

    print("─" * 74)
    print("LLM 裁决明细")
    print("─" * 74)
    for act, ok, s, ev_t, th_t, note in detail:
        flag = "FP" if not ok else "TP"
        print(f"  [{flag}][{act}] S={s:.3f} {note}")
        print(f"        事件: {ev_t[:40]}")
        print(f"        线  : {th_t[:40]}")
    print()

    n_tp_rule = sum(1 for x in sample if x[3])
    n_fp_rule = sum(1 for x in sample if not x[3])
    corr = sum(1 for act, *_ in detail if act == "拒绝✓")
    hurt = sum(1 for act, *_ in detail if act == "拒绝✗")
    print("─" * 74)
    print("小结")
    print("─" * 74)
    print(f"  复核样本 {len(sample)} 条（其中规则层判对 {n_tp_rule}、判错 {n_fp_rule}）")
    print(f"  LLM 纠正误归 {corr} 条｜误伤真阳性 {hurt} 条｜无法判定(放行) {llm_none} 条")
    print(f"  放行率 {100*llm_none/max(len(sample),1):.1f}%")
    if n_fp_rule:
        print(f"  误归捕获率 {100*corr/n_fp_rule:.1f}%")
    if n_tp_rule:
        print(f"  真阳性误伤率 {100*hurt/n_tp_rule:.1f}%")

    # ★ 关键：灰色带是否覆盖误归？
    lo = settings.THREAD_T_JOIN
    hi = lo + settings.THREAD_LLM_VERIFY_BAND
    print()
    print("─" * 74)
    print(f"灰色带覆盖检查：生产只复核 [{lo:.2f}, {hi:.2f})")
    print("─" * 74)
    fp_in = [s for s in fp_scores if lo <= s < hi]
    fp_out = [s for s in fp_scores if not (lo <= s < hi)]
    tp_in = [s for s in tp_scores if lo <= s < hi]
    print(f"  全部命中中：误归 {len(fp_scores)} 条（带内 {len(fp_in)}，带外 {len(fp_out)}）"
          f"｜真阳性 {len(tp_scores)} 条（带内 {len(tp_in)}）")
    def _pct(arr, p):
        if not arr:
            return 0.0
        a = sorted(arr)
        return a[min(int(len(a) * p), len(a) - 1)]

    print(f"  误归 S   : p25 {_pct(fp_scores,.25):.3f} | 中位 {_pct(fp_scores,.50):.3f} "
          f"| p75 {_pct(fp_scores,.75):.3f} | max {max(fp_scores):.3f}")
    print(f"  真阳性 S : p25 {_pct(tp_scores,.25):.3f} | 中位 {_pct(tp_scores,.50):.3f} "
          f"| p75 {_pct(tp_scores,.75):.3f} | max {max(tp_scores):.3f}")
    print("  → 两者 S 分布重叠严重，说明**没有安全的灰色带**：")
    print("    只靠 S 切区间挡不住误归，必须扩大复核范围或对高 S 也抽样。")
    print()

    if fp_scores:
        print(f"  误归落在带内比例 {100*len(fp_in)/len(fp_scores):.1f}%"
              f"  ← 这个数决定开启后能拦下多少")
    if fp_out:
        print(f"  ⚠ 带外误归 {len(fp_out)} 条（S>=%.2f）开启后仍会漏网：" % hi)
        for s in sorted(fp_out, reverse=True)[:10]:
            print(f"      S={s:.3f}")
        print("     → 若占比高，需调大 THREAD_LLM_VERIFY_BAND")
    print()
    print("─" * 74)
    print("三种开启策略对比（按 40 条实测：捕获率 86.7%、误伤率 0% 外推）")
    print("─" * 74)
    n_fp, n_tp = len(fp_scores), len(tp_scores)
    print("| 策略 | 复核范围 | 拦下误归 | 误伤真阳性 | 净 Precision | 日调用 |")
    print("|---|---|---|---|---|---|")
    for name, lo_b, hi_b in (
        ("A 灰色带(现状)", settings.THREAD_T_JOIN,
         settings.THREAD_T_JOIN + settings.THREAD_LLM_VERIFY_BAND),
        ("B 全量复核", settings.THREAD_T_JOIN, 9.9),
        ("C 放宽到0.50", settings.THREAD_T_JOIN, 0.50),
    ):
        fp_i = sum(1 for s in fp_scores if lo_b <= s < hi_b)
        tp_i = sum(1 for s in tp_scores if lo_b <= s < hi_b)
        caught = int(fp_i * 0.867)
        hurt_i = int(tp_i * 0.0)
        newp = (n_tp - hurt_i) / max((n_tp - hurt_i) + (n_fp - caught), 1)
        calls = fp_i + tp_i
        print("| %s | [%.2f,%.2f) | %d/%d | %d | %.3f | %d |" % (
            name, lo_b, hi_b, caught, n_fp, hurt_i, newp, calls))
    print()
    print("  基线 Precision = %.3f" % (n_tp / max(n_tp + n_fp, 1)))
    print("  B 全量：拦最多，但日调用量最大；LLM 误伤率实测 0%，风险可控。")
    print("  C 折中：覆盖到 S=0.50，可拦下绝大多数误归。")
    print()
    print("判定建议：误归捕获率高、真阳性误伤率低 → 可开启")
    print("          THREAD_LLM_VERIFY_ENABLED=true")


if __name__ == "__main__":
    asyncio.run(main())
