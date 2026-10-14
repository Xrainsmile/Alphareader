#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""世界线路由离线回放评估（用人工基线做 ground truth）。

为什么不等 7 天影子
------------------
在线影子要等新事件慢慢攒，且新事件没有人工标注、无法算准确率。
基线已有 441 条 `assigned_by='manual'` 的章节 = 现成的人工标注集。
直接拿它当标准答案，让算法**离线回放**一遍历史事件，当天就能出
precision / recall / F1，还能和"旧配置"同条件 A/B 对比，量化改进幅度。
影子模式该跑还得跑（验真实流量），但本脚本负责给出**量化结论**。

关键设计：时间回溯
------------------
评估时用**事件自身的 occurred_at 作为 now**，而不是当前时间。
否则历史事件距"现在"都很远，time_gap_penalty 会把所有线衰减到 0，
结果变成"全部漏归"，评估失真。回放必须站在当时那个时点看。

指标定义（对每个事件，gt = 人工基线给的线）
------------------------------------------
    TP  算法判定 join 且 top1 == gt
    FP  算法判定 join 但 top1 != gt（误归：把事件塞进错的线）
    FN  算法判定不 join（漏归：本该进 gt 线却没进去）
    Precision = TP / (TP + FP)     归进去的有多少是对的
    Recall    = TP / (TP + FN)     该归的归进去了多少
    F1        = 2PR / (P + R)

用法（在 alpha-web 容器内执行，需连生产库）
------------------------------------------
    docker cp eval_thread_routing.py alpha-web:/tmp/
    docker exec alpha-web python /tmp/eval_thread_routing.py
    docker exec alpha-web python /tmp/eval_thread_routing.py --errors 30
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.config import settings                                    # noqa: E402
from app.database import async_session                             # noqa: E402
from app.services import thread_router as tr                       # noqa: E402


# ---------------------------------------------------------------------------
# 数据加载（批量，避免 N 次查询）
# ---------------------------------------------------------------------------
async def load_all():
    async with async_session() as s:
        # ground truth：人工基线标注
        gt = {}
        rows = (await s.execute(text("""
            SELECT event_id, thread_id FROM thread_events WHERE assigned_by = 'manual'
        """))).all()
        for eid, tid in rows:
            gt[str(eid)] = str(tid)

        # 事件标题 + 时间
        events = {}
        rows = (await s.execute(text("""
            SELECT id,
                   COALESCE(title,'')    AS ev_title,
                   COALESCE(summary,'')  AS ev_summary,
                   created_at            AS ev_at
            FROM events
        """))).mappings().all()
        for r in rows:
            events[str(r["id"])] = {
                "title": r["ev_title"], "summary": r["ev_summary"], "at": r["ev_at"]
            }

        # 事件实体
        ev_ents = defaultdict(dict)
        rows = (await s.execute(text("""
            SELECT ee.event_id, en.canonical_name, ee.weight
            FROM event_entities ee JOIN entities en ON en.id = ee.entity_id
        """))).all()
        for eid, name, w in rows:
            if name:
                ev_ents[str(eid)][name] = max(ev_ents[str(eid)].get(name, 0), int(w or 1))

        # 机制存在 events.mechanism_hints（jsonb 数组），不是独立表
        ev_mechs = defaultdict(list)
        try:
            rows = (await s.execute(text("""
                SELECT id, mechanism_hints FROM events
                WHERE mechanism_hints IS NOT NULL
            """))).all()
            for eid, mh in rows:
                if isinstance(mh, list):
                    ev_mechs[str(eid)] = [str(x) for x in mh if x]
                elif isinstance(mh, str):
                    ev_mechs[str(eid)] = [mh]
        except Exception as exc:  # noqa: BLE001
            print("（跳过机制加载：%s）" % exc)

        # 候选线
        threads = []
        rows = (await s.execute(text("""
            SELECT id, title, core_entities, mechanism_key, last_event_at
            FROM threads WHERE status NOT IN ('merged','split')
        """))).mappings().all()
        for r in rows:
            threads.append(dict(r))
    return gt, events, ev_ents, ev_mechs, threads


# ---------------------------------------------------------------------------
# 配置快照 / 切换：BEFORE（现网旧行为） vs AFTER（本次改造）
# ---------------------------------------------------------------------------
def snapshot():
    return {
        "M_REDISTRIBUTE": settings.THREAD_M_REDISTRIBUTE_WEIGHT,
        "T_JOIN_ENTITY": settings.THREAD_T_JOIN_ENTITY,
        "MIN_SHARED": settings.THREAD_MIN_SHARED_ENTITIES,
        "DENYLIST": list(settings.THREAD_ENTITY_DENYLIST or []),
        "KIND_GATE": settings.THREAD_KIND_GATE_ENABLED,
        "TIME_GAP": settings.THREAD_TIME_GAP_ENABLED,
        "SNAPSHOT": settings.THREAD_MARKET_SNAPSHOT_ENABLED,
    }


def apply(mode: str):
    if mode == "BEFORE":
        settings.THREAD_M_REDISTRIBUTE_WEIGHT = False
        settings.THREAD_E_NORMALIZE = False
        settings.THREAD_T_JOIN_ENTITY = 0.15
        settings.THREAD_MIN_SHARED_ENTITIES = 2
        settings.THREAD_T_JOIN = 0.40
        settings.THREAD_ENTITY_DENYLIST = []
        settings.THREAD_KIND_GATE_ENABLED = False
        settings.THREAD_TIME_GAP_ENABLED = False
        settings.THREAD_MARKET_SNAPSHOT_ENABLED = False
    else:  # AFTER
        settings.THREAD_M_REDISTRIBUTE_WEIGHT = True
        settings.THREAD_E_NORMALIZE = True
        settings.THREAD_T_JOIN_ENTITY = 0.08
        settings.THREAD_MIN_SHARED_ENTITIES = 1
        settings.THREAD_T_JOIN = 0.15
        settings.THREAD_KIND_GATE_ENABLED = True
        settings.THREAD_TIME_GAP_ENABLED = True
        settings.THREAD_MARKET_SNAPSHOT_ENABLED = True
        # 黑名单恢复默认（重新导入太重，这里内联一份精简版用于回放）
        settings.THREAD_ENTITY_DENYLIST = getattr(settings, "_DEFAULT_DENY", [])
    tr._DENY_CACHE = None   # 清黑名单缓存，否则切换不生效


# ---------------------------------------------------------------------------
# 回放
# ---------------------------------------------------------------------------
async def replay(mode: str, gt, events, ev_ents, ev_mechs, threads):
    # 只在这两种模式切换配置；"CFG" 表示由 sweep 在外部设定，原样保留
    if mode in ("BEFORE", "AFTER"):
        apply(mode)
    deny = tr._denylist()

    tp = fp = fn = 0
    errs, nojoin = [], []
    reason = Counter()
    per_thread = Counter()
    per_thread_gt = Counter()

    for eid, gt_tid in gt.items():
        ev = events.get(eid)
        if not ev:
            continue
        title = ev["title"]
        per_thread_gt[gt_tid] += 1

        if tr.is_market_snapshot(title):
            fn += 1          # 快照被隔离 = 不归线，对 gt 而言是漏归
            continue

        ents = {k: v for k, v in ev_ents.get(eid, {}).items() if k not in deny}
        if not ents:
            fn += 1
            reason["实体全被黑名单过滤"] += 1
            continue
        mechs = ev_mechs.get(eid, [])
        ev_kind = tr.infer_event_kind(title, list(ents.keys()))
        now = ev["at"] or datetime.now(timezone.utc)

        scored = []
        n_kind = n_gate = n_thresh = n_noent = 0
        for t in threads:
            tid = str(t["id"])
            th_kind = tr._infer_thread_kind(t)
            if settings.THREAD_KIND_GATE_ENABLED and tr.kind_conflict(ev_kind, th_kind):
                n_kind += 1
                continue
            th_ents = tr._thread_entity_weights(t.get("core_entities"))
            if not th_ents:
                n_noent += 1
                continue
            s, e, m, r = tr.compute_score(ents, th_ents, mechs, t.get("mechanism_key"), now)
            gap = tr.time_gap_penalty(t.get("last_event_at"), now) if settings.THREAD_TIME_GAP_ENABLED else 1.0
            if gap < 1.0:
                s *= gap
            shared = tr.shared_entity_count(ents, th_ents)
            passed, why = tr.entity_gate(e, shared)
            if not passed:
                n_gate += 1
                continue
            if s < settings.THREAD_T_JOIN:
                n_thresh += 1
                continue
            scored.append((s, tid, t))

        if not scored:
            fn += 1
            if n_kind:
                reason["类型互斥被拦"] += 1
            if n_gate:
                reason["实体门控未过"] += 1
            if n_thresh:
                reason["S低于阈值"] += 1
            if n_kind == n_gate == n_thresh == 0:
                reason["无候选线实体"] += 1
            nojoin.append((title, gt_tid, ev_kind, n_kind, n_gate, n_thresh, len(ents)))
            continue

        scored.sort(key=lambda x: -x[0])
        best_s, best_tid, best_t = scored[0]
        if best_tid == gt_tid:
            tp += 1
            per_thread[gt_tid] += 1
        else:
            fp += 1
            errs.append((best_s, title, best_t.get("title"), gt_tid, best_tid))

    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "mode": mode, "tp": tp, "fp": fp, "fn": fn,
        "precision": prec, "recall": rec, "f1": f1,
        "errors": errs, "nojoin": nojoin, "reason": reason,
        "per_thread": per_thread, "per_thread_gt": per_thread_gt,
    }


async def sweep(gt, events, ev_ents, ev_mechs, threads):
    """阈值扫描：用数据选参数，而不是拍脑袋。

    同时统计真实配对（事件 vs 其 gt 线）的 E / shared 分布，
    这是定阈值的唯一可靠依据——门控阈值必须落在真阳性的下沿之上。
    """
    apply("AFTER")
    deny = tr._denylist()

    # 先看真实配对的 E 与 shared 分布
    es, shs = [], []
    for eid, gt_tid in gt.items():
        ev = events.get(eid)
        if not ev:
            continue
        ents = {k: v for k, v in ev_ents.get(eid, {}).items() if k not in deny}
        if not ents:
            continue
        t = next((x for x in threads if str(x["id"]) == gt_tid), None)
        if not t:
            continue
        th_ents = tr._thread_entity_weights(t.get("core_entities"))
        if not th_ents:
            continue
        e, _, _ = tr.weighted_jaccard(ents, th_ents), 0, 0
        es.append(e)
        shs.append(tr.shared_entity_count(ents, th_ents))

    def pct(arr, p):
        if not arr:
            return 0.0
        a = sorted(arr)
        return a[min(int(len(a) * p), len(a) - 1)]

    print("─" * 74)
    print("真实配对（事件 vs 其人工基线所属线）的 E / 共享实体数分布")
    print("─" * 74)
    print(f"  样本 {len(es)} 条")
    print(f"  E      : min {min(es):.3f} | p10 {pct(es,.10):.3f} | p25 {pct(es,.25):.3f} "
          f"| 中位 {pct(es,.50):.3f} | p75 {pct(es,.75):.3f} | max {max(es):.3f}")
    print(f"  shared : min {min(shs)} | p10 {pct(shs,.10)} | p25 {pct(shs,.25)} "
          f"| 中位 {pct(shs,.50)} | p75 {pct(shs,.75)} | max {max(shs)}")
    print()
    print("  → 门控阈值必须 ≤ 真阳性下沿，否则直接误杀。")
    print("  → 当前 E 上限受「线权重累积」压制：线越成熟 Σw 越大，E 越小。")
    print()

    # 归一化对照：把两侧权重按各自总和归一化后再算 Jaccard
    print("─" * 74)
    print("修复对照：权重归一化后的 E 分布（两侧各除以自身 Σw）")
    print("─" * 74)
    es_n = []
    for eid, gt_tid in gt.items():
        ev = events.get(eid)
        if not ev:
            continue
        ents = {k: v for k, v in ev_ents.get(eid, {}).items() if k not in deny}
        if not ents:
            continue
        t = next((x for x in threads if str(x["id"]) == gt_tid), None)
        if not t:
            continue
        th_ents = tr._thread_entity_weights(t.get("core_entities"))
        if not th_ents:
            continue
        se, st = sum(ents.values()) or 1, sum(th_ents.values()) or 1
        a = {k: v / se for k, v in ents.items()}
        b = {k: v / st for k, v in th_ents.items()}
        es_n.append(tr.weighted_jaccard(a, b))
    if es_n:
        print(f"  样本 {len(es_n)} 条")
        print(f"  E_norm : min {min(es_n):.3f} | p10 {pct(es_n,.10):.3f} "
              f"| p25 {pct(es_n,.25):.3f} | 中位 {pct(es_n,.50):.3f} "
              f"| p75 {pct(es_n,.75):.3f} | max {max(es_n):.3f}")
    print()

    # 组合扫描
    print("─" * 74)
    print("参数组合扫描（TP/FP/FN/P/R/F1）")
    print("─" * 74)
    print("| E门控 | 最少共享 | 类型门控 | TP | FP | FN | Prec | Rec | F1 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    results = []
    for tje in (0.08, 0.10, 0.15, 0.20, 0.30):
        for ms in (1, 2, 3):
            for kg in (True, False):
                settings.THREAD_T_JOIN_ENTITY = tje
                settings.THREAD_MIN_SHARED_ENTITIES = ms
                settings.THREAD_KIND_GATE_ENABLED = kg
                r = await replay("CFG", gt, events, ev_ents, ev_mechs, threads)
                results.append((r["f1"], tje, ms, kg, r))
                print("| %.2f | %d | %s | %d | %d | %d | %.3f | %.3f | %.3f |" % (
                    tje, ms, "on" if kg else "off",
                    r["tp"], r["fp"], r["fn"], r["precision"], r["recall"], r["f1"]))
    # 真实配对的 S 分布（用当前 AFTER 配置）
    apply("AFTER")
    deny = tr._denylist()
    ss = []
    for eid, gt_tid in gt.items():
        ev = events.get(eid)
        if not ev:
            continue
        ents = {k: v for k, v in ev_ents.get(eid, {}).items() if k not in deny}
        if not ents:
            continue
        t = next((x for x in threads if str(x["id"]) == gt_tid), None)
        if not t:
            continue
        th_ents = tr._thread_entity_weights(t.get("core_entities"))
        if not th_ents:
            continue
        now = ev["at"] or datetime.now(timezone.utc)
        s, e, m, r = tr.compute_score(ents, th_ents, ev_mechs.get(eid, []),
                                      t.get("mechanism_key"), t.get("last_event_at"), now)
        ss.append(s)
    if ss:
        print("─" * 74)
        print("真实配对的 S 分布（当前 AFTER 配置，机制缺失已做权重重分配）")
        print("─" * 74)
        print(f"  样本 {len(ss)} 条")
        print(f"  S : min {min(ss):.3f} | p25 {pct(ss,.25):.3f} | 中位 {pct(ss,.50):.3f} "
              f"| p75 {pct(ss,.75):.3f} | p90 {pct(ss,.90):.3f} | max {max(ss):.3f}")
        print(f"  当前 T_JOIN = {settings.THREAD_T_JOIN} → "
              f"有 {sum(1 for x in ss if x >= settings.THREAD_T_JOIN)}/{len(ss)} 条真阳性能过阈值")
        print()
        print("  → 若绝大多数真阳性的 S 都低于 T_JOIN，则阈值是瓶颈，")
        print("    调门控无用（这正是上一轮所有 E 阈值结果相同的原因）。")
        print()

    # T_JOIN 扫描
    print("─" * 74)
    print("T_JOIN 阈值扫描（固定 E门控=0.08、最少共享=1、类型门控=on）")
    print("─" * 74)
    print("| T_JOIN | TP | FP | FN | Prec | Rec | F1 |")
    print("|---|---|---|---|---|---|---|")
    settings.THREAD_T_JOIN_ENTITY = 0.08
    settings.THREAD_MIN_SHARED_ENTITIES = 1
    settings.THREAD_KIND_GATE_ENABLED = True
    best = None
    for tj in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40):
        settings.THREAD_T_JOIN = tj
        r = await replay("CFG", gt, events, ev_ents, ev_mechs, threads)
        print("| %.2f | %d | %d | %d | %.3f | %.3f | %.3f |" % (
            tj, r["tp"], r["fp"], r["fn"], r["precision"], r["recall"], r["f1"]))
        if best is None or r["f1"] > best[0]:
            best = (r["f1"], tj, r)
    print()
    f1, tj, r = best
    print("最优 T_JOIN=%.2f → F1=%.3f (P=%.3f R=%.3f)" % (
        tj, f1, r["precision"], r["recall"]))
    print()

    # 联合扫描：E 门控 × 最少共享 × T_JOIN
    print("─" * 74)
    print("联合扫描：E门控 × 最少共享 × T_JOIN（类型门控=on）")
    print("─" * 74)
    print("| E门控 | 最少共享 | T_JOIN | TP | FP | FN | Prec | Rec | F1 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    settings.THREAD_KIND_GATE_ENABLED = True
    joint = []
    for tje in (0.05, 0.08, 0.12, 0.20):
        for ms in (1, 2):
            for tj in (0.10, 0.15, 0.20, 0.25):
                settings.THREAD_T_JOIN_ENTITY = tje
                settings.THREAD_MIN_SHARED_ENTITIES = ms
                settings.THREAD_T_JOIN = tj
                r = await replay("CFG", gt, events, ev_ents, ev_mechs, threads)
                joint.append((r["f1"], tje, ms, tj, r))
                print("| %.2f | %d | %.2f | %d | %d | %d | %.3f | %.3f | %.3f |" % (
                    tje, ms, tj, r["tp"], r["fp"], r["fn"],
                    r["precision"], r["recall"], r["f1"]))
    joint.sort(key=lambda x: -x[0])
    print()
    f1, tje, ms, tj, r = joint[0]
    print("★ 最优组合：E门控=%.2f，最少共享=%d，T_JOIN=%.2f → F1=%.3f "
          "(P=%.3f R=%.3f, TP=%d FP=%d FN=%d)" % (
              tje, ms, tj, f1, r["precision"], r["recall"],
              r["tp"], r["fp"], r["fn"]))
    settings.THREAD_T_JOIN = 0.40
    apply("AFTER")
    return results


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--errors", type=int, default=15, help="展示多少条误归样本")
    ap.add_argument("--sweep", action="store_true", help="做阈值扫描而非单次评估")
    ap.add_argument("--clean-baseline", metavar="PATH",
                    help="用清洗清单剔除市场快照后再评估（干净 F1）")
    a = ap.parse_args()

    # 先固化默认黑名单，供 AFTER 模式恢复
    settings._DEFAULT_DENY = list(settings.THREAD_ENTITY_DENYLIST or [])

    gt, events, ev_ents, ev_mechs, threads = await load_all()

    # ★ 2026-10-14：基线清洗。ground truth 里混着 12.9% 市场快照，
    #   拿它当标准答案会惩罚正确规则（隔离快照被记 FN）。用清洗清单剔除
    #   后再评估，才能得到不被污染的 F1。明细见 clean_baseline.py。
    excluded = set()
    if a.clean_baseline:
        import json
        try:
            with open(a.clean_baseline, encoding="utf-8") as f:
                payload = json.load(f)
            excluded = {x["event_id"] for x in payload.get("excluded", [])}
        except Exception as exc:  # noqa: BLE001
            print("（清洗清单加载失败，用原始基线：%s）" % exc)
        else:
            before_n = len(gt)
            gt = {k: v for k, v in gt.items() if k not in excluded}
            print(f"基线清洗：剔除 {before_n - len(gt)} 条市场快照 "
                  f"→ 干净基线 {len(gt)} 条（原 {before_n}）")

    print("=" * 74)
    print("世界线路由离线回放评估 —— ground truth = 人工基线")
    print("=" * 74)
    print(f"人工标注章节 {len(gt)} 条｜候选线 {len(threads)} 条｜事件 {len(events)} 条")
    print(f"带机制标注的事件 {len(ev_mechs)} 条"
          f"（覆盖率 {100*len(ev_mechs)/max(len(events),1):.1f}%）")
    print()

    if a.sweep:
        await sweep(gt, events, ev_ents, ev_mechs, threads)
        return

    before = await replay("BEFORE", gt, events, ev_ents, ev_mechs, threads)
    after = await replay("AFTER", gt, events, ev_ents, ev_mechs, threads)
    apply("AFTER")   # 评估结束把配置恢复成生产值

    print("| 配置 | TP | FP | FN | Precision | Recall | F1 |")
    print("|---|---|---|---|---|---|---|")
    for r in (before, after):
        print("| %s | %d | %d | %d | %.3f | %.3f | %.3f |" % (
            r["mode"], r["tp"], r["fp"], r["fn"],
            r["precision"], r["recall"], r["f1"]))
    print()
    d_f1 = after["f1"] - before["f1"]
    d_p = after["precision"] - before["precision"]
    d_r = after["recall"] - before["recall"]
    print("改进幅度：F1 %+.3f｜Precision %+.3f｜Recall %+.3f" % (d_f1, d_p, d_r))
    print()

    # 误归样本
    print("─" * 74)
    print("AFTER 误归样本（事件被塞进了错的线）")
    print("─" * 74)
    for s, title, th_title, gtid, gotid in sorted(after["errors"], key=lambda x: -x[0])[:a.errors]:
        print(f"  S={s:.3f} {title[:38]}")
        print(f"        误入: {str(th_title)[:38]}")
    if not after["errors"]:
        print("  （无）")
    print()

    print("─" * 74)
    print("漏归原因分布（AFTER，可多选，故总和 > 漏归数）")
    print("─" * 74)
    for k, v in after["reason"].most_common():
        print(f"  {k:<22} {v:>5} 条")
    print()
    print("─" * 74)
    print("漏归样本（含诊断：类型/互斥数/门控未过数/阈值未过数/事件实体数）")
    print("─" * 74)
    for title, gtid, kind, nk, ng, nt, ne in after["nojoin"][:a.errors]:
        print(f"  [{kind}|实体{ne}] 互斥{nk} 门控{ng} 阈值{nt}  {title[:36]}")
    if not after["nojoin"]:
        print("  （无）")
    print()
    print(f"漏归合计 {len(after['nojoin'])} 条。")


if __name__ == "__main__":
    asyncio.run(main())
