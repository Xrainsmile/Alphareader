#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出基线清洗候选清单（纯规则，不调任何 LLM）。

判定由 AI 助手（对话内）逐条完成，本脚本只负责把候选捞出来，
附带规则的初判结果供参考。
"""
from __future__ import annotations

import json
import re
import sys

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session               # noqa: E402
from app.services import thread_router as tr         # noqa: E402

CANDIDATE_RE = (
    r"集体|全线|普涨|普跌|领涨|领跌|概念股|板块|开盘|收盘|盘初|盘中|"
    r"盘前|盘后|早盘|午盘|尾盘|三大指数|恒指|科指|创业板指|科创50|"
    r"走强|走弱|走高|走低|下挫|拉升|翻红|异动|涨跌停|涨超|跌超|涨幅|跌幅"
)


async def main():
    async with async_session() as s:
        rows = (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events WHERE assigned_by='manual'"
        ))).all()
        gt = [(str(a), str(b)) for a, b in rows]

        ev = {}
        for r in (await s.execute(text(
            "SELECT id, COALESCE(title,'') AS t, COALESCE(summary,'') AS s FROM events"
        ))).mappings().all():
            ev[str(r["id"])] = {"title": r["t"], "summary": r["s"]}

        tmap = {str(a): b for a, b in
                (await s.execute(text("SELECT id, title FROM threads"))).all()}

    out = []
    for eid, tid in gt:
        e = ev.get(eid)
        if not e or not re.search(CANDIDATE_RE, e["title"]):
            continue
        out.append({
            "event_id": eid,
            "thread_title": tmap.get(tid, ""),
            "title": e["title"],
            "summary": (e["summary"] or "")[:200],
            "rule_says": "snapshot" if tr.is_market_snapshot(e["title"]) else "event",
        })

    out.sort(key=lambda x: (x["rule_says"], x["title"]))
    with open("/tmp/baseline_candidates.json", "w", encoding="utf-8") as f:
        json.dump({"ground_truth_total": len(gt), "candidates": out},
                  f, ensure_ascii=False, indent=2)
    print(f"人工基线 {len(gt)} 条｜宽泛候选 {len(out)} 条")
    print(f"规则判快照 {sum(1 for x in out if x['rule_says']=='snapshot')} 条｜"
          f"规则判事件 {sum(1 for x in out if x['rule_says']=='event')} 条")
    print("已写入 /tmp/baseline_candidates.json")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
