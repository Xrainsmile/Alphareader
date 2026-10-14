#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基线清洗（2026-10-14）：把「市场快照」从 ground truth 中剔除。

为什么要洗
----------
人工基线 441 条里有 57 条（12.9%）是市场快照型标题，例如
「港股开盘恒指科指齐涨，生物医药黄金股领涨」。人工当初把它们也归进了
「黄金避险行情」等线，导致部分线稀释率高达 57.1%。

拿被污染的基线当标准答案，会**惩罚正确的规则**：
规则把这些隔离掉 → 记为 FN（漏归）→ Recall 被压低；
规则学人工的样子收进去 → 反而算 TP。
这是典型的循环评估偏差（evaluating against a contaminated ground truth）。

但不能一刀切删 57 条
--------------------
其中混杂着真事件，盘面只是结果，必须保留：
    朱雀三号火箭陆地回收成功，商业航天概念股大涨   ← 火箭回收是真事件
    沙特机场与油轮遇袭 油价盘初走高                ← 遇袭是真事件
    英伟达推开源AI模型，美股半导体设备股集体走强   ← 发布模型是真事件
    阿里巴巴配股募资约100亿美元，港股开盘跌超8%    ← 配股是真事件

所以清洗必须**逐条判定**，而不是正则一筐端。

判定方式（双保险）
----------------
1. 规则层：is_market_snapshot() 三层（强/弱/豁免）
2. LLM 层：独立判断"这条是有独立追踪价值的事件，还是纯盘面描述"

两者一致 → 直接采用；不一致 → 输出供人工仲裁。

产出
----
/tmp/baseline_exclusions.json —— 待剔除的 event_id 清单（含标题与理由），
供 eval_thread_routing.py --clean-baseline 使用。可复现、可追溯。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.config import settings                      # noqa: E402
from app.database import async_session               # noqa: E402
from app.services import thread_router as tr         # noqa: E402


# 宽泛候选：先捞一大批，再由规则/LLM 精判（宁可多捞不可漏）
CANDIDATE_RE = (
    r"集体|全线|普涨|普跌|领涨|领跌|概念股|板块|开盘|收盘|盘初|盘中|"
    r"盘前|盘后|早盘|午盘|尾盘|三大指数|恒指|科指|创业板指|科创50|"
    r"走强|走弱|走高|走低|下挫|拉升|翻红|异动|涨跌停|涨超|跌超|涨幅|跌幅"
)

_SYSTEM = """你是新闻事件分类器的仲裁者。判断一条财经新闻是「纯盘面快照」还是「有独立追踪价值的事件」。

【纯盘面快照 snapshot】满足以下特征：
- 描述的是当天/当时段的盘面整体表现（指数涨跌、板块集体走强、个股跟随大盘）
- 没有明确的主体动作或独立发生的事件，只是"价格/指数在动"
- 读者不会把它当作某件事的进展，只是行情播报
例：「港股开盘恒指科指齐涨，生物医药黄金股领涨」「美股存储板块8月18日普跌」

【有独立追踪价值的事件 event】满足以下任一：
- 有明确的主体做成了某件具体的事（发射成功、遇袭、获批、收购、发布产品、财报、配股、制裁）
- 是某条叙事主线的一个进展节点，即使标题带了盘面描述
例：「朱雀三号火箭陆地回收成功，商业航天概念股大涨」→ event（火箭回收是主体事件）
例：「沙特机场与油轮遇袭 油价盘初走高」→ event（遇袭是主体事件）
例：「英伟达推开源AI模型，美股半导体设备股集体走强」→ event（发布模型是主体事件）

【判定原则】
盘面描述只是"结果"时，看有没有"原因事件"。有原因事件 → event；只有结果 → snapshot。
个股跟随大盘涨跌（如"XX股涨超6%"）若无主体动作 → snapshot。

只输出 JSON：{"verdict":"snapshot|event","reason":"不超过20字"}
不要输出任何其他内容。"""

_USER = """新闻标题：{title}
事件摘要：{summary}

这条属于 snapshot 还是 event？"""


async def load_candidates():
    async with async_session() as s:
        gt = {}
        rows = (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events WHERE assigned_by='manual'"
        ))).all()
        for eid, tid in rows:
            gt[str(eid)] = str(tid)

        events = {}
        rows = (await s.execute(text(
            "SELECT id, COALESCE(title,'') AS t, COALESCE(summary,'') AS s FROM events"
        ))).mappings().all()
        for r in rows:
            events[str(r["id"])] = {"title": r["t"], "summary": r["s"]}

        tmap = {}
        rows = (await s.execute(text("SELECT id, title FROM threads"))).all()
        for tid, t in rows:
            tmap[str(tid)] = t
    out = []
    for eid, tid in gt.items():
        ev = events.get(eid)
        if not ev:
            continue
        if re.search(CANDIDATE_RE, ev["title"]):
            out.append((eid, tid, ev["title"], ev["summary"], tmap.get(tid, "")))
    return out, len(gt)


async def llm_judge(title: str, summary: str) -> tuple[str | None, str]:
    try:
        from app.services.llm_client import stream_chat
    except Exception:  # noqa: BLE001
        return None, "llm导入失败"
    try:
        raw = await stream_chat(
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": _USER.format(
                          title=title, summary=(summary or "")[:250])}],
            temperature=0.0, max_tokens=80, log_tag="BASELINE_CLEAN",
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"llm调用失败:{exc}"[:20]
    if not raw:
        return None, "空返回"
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None, f"无JSON:{raw[:30]}"
    try:
        obj = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None, "JSON解析失败"
    v = str(obj.get("verdict", "")).strip().lower()
    reason = str(obj.get("reason", ""))[:20]
    if v in ("snapshot", "event"):
        return v, reason
    return None, f"非法verdict:{v}"[:20]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="只用规则，不调 LLM")
    ap.add_argument("--out", default="/tmp/baseline_exclusions.json")
    a = ap.parse_args()

    cands, n_gt = await load_candidates()
    print("=" * 74)
    print("基线清洗：识别 ground truth 中的市场快照")
    print("=" * 74)
    print(f"人工基线 {n_gt} 条｜宽泛候选 {len(cands)} 条"
          f"（{100*len(cands)/n_gt:.1f}%）")
    print()

    rows = []
    for eid, tid, title, summary, th_title in cands:
        rule_snap = tr.is_market_snapshot(title)
        if a.no_llm:
            llm_v, llm_r = None, "（跳过）"
        else:
            llm_v, llm_r = await llm_judge(title, summary)
        rows.append({
            "event_id": eid, "thread_id": tid, "title": title,
            "thread_title": th_title,
            "rule": "snapshot" if rule_snap else "event",
            "llm": llm_v, "llm_reason": llm_r,
        })

    # 分类
    both = [r for r in rows if r["rule"] == "snapshot" and r["llm"] == "snapshot"]
    rule_only = [r for r in rows if r["rule"] == "snapshot" and r["llm"] == "event"]
    llm_only = [r for r in rows if r["rule"] == "event" and r["llm"] == "snapshot"]
    keep = [r for r in rows if r["rule"] == "event" and r["llm"] == "event"]
    unknown = [r for r in rows if r["llm"] is None]

    print("─" * 74)
    print("判定结果")
    print("─" * 74)
    print(f"  规则=快照 且 LLM=快照  → 剔除       {len(both):>3} 条  ✅ 无争议")
    print(f"  规则=快照 但 LLM=事件  → 分歧(保留) {len(rule_only):>3} 条  ⚠ 规则过严")
    print(f"  规则=事件 但 LLM=快照  → 分歧(剔除) {len(llm_only):>3} 条  ⚠ 规则过松")
    print(f"  规则=事件 且 LLM=事件  → 保留       {len(keep):>3} 条  ✅ 无争议")
    if unknown:
        print(f"  LLM 无法判定（按规则执行）         {len(unknown):>3} 条")
    print()

    # 剔除集：双方一致 或 LLM 独判快照；规则独判快照但 LLM 说事件 → 保留（防误删）
    exclude = both + llm_only
    for r in unknown:
        if r["rule"] == "snapshot":
            exclude.append(r)

    print("─" * 74)
    print(f"规则过严样本（规则要删、LLM 说该留）前 15 条")
    print("─" * 74)
    for r in rule_only[:15]:
        print(f"  {r['title'][:44]}")
        print(f"      → {r['llm_reason']}")
    if not rule_only:
        print("  （无）")
    print()
    print("─" * 74)
    print(f"规则过松样本（规则要留、LLM 说该删）前 15 条")
    print("─" * 74)
    for r in llm_only[:15]:
        print(f"  {r['title'][:44]}")
        print(f"      → {r['llm_reason']}")
    if not llm_only:
        print("  （无）")
    print()

    payload = {
        "generated_at": "2026-10-14",
        "ground_truth_total": n_gt,
        "candidates": len(rows),
        "excluded_count": len(exclude),
        "excluded": [{"event_id": r["event_id"], "title": r["title"],
                      "thread_title": r["thread_title"],
                      "rule": r["rule"], "llm": r["llm"],
                      "llm_reason": r["llm_reason"]} for r in exclude],
        "kept_disagreement": [{"event_id": r["event_id"], "title": r["title"],
                               "rule": r["rule"], "llm": r["llm"],
                               "llm_reason": r["llm_reason"]} for r in rule_only],
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("=" * 74)
    print(f"剔除 {len(exclude)} 条 → 干净基线 {n_gt - len(exclude)} 条"
          f"（原 {n_gt}）")
    print(f"清单已写入 {a.out}")
    print("=" * 74)


if __name__ == "__main__":
    asyncio.run(main())
