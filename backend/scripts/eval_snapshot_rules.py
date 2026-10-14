#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场快照规则验证（P2-11 升级）：对齐人工基线，量出误杀与漏放。

判定口径
--------
以 `thread_events.assigned_by='manual'` 的 441 条为「人工认为该进线」。

    blocked  被判为快照 → 不进线
    passed   未被判快照 → 进线

    blocked_hit_gt   被判快照 且 人工认为该进线 → **误杀**（关键风险）
    blocked_not_gt   被判快照 且 人工也没归线 → 正确隔离
    passed_gt        放行 且 人工认为该进线 → 一致

⚠️ 口径提醒（2026-10-14）
------------------------
ground truth 本身含约 57/441（12.9%）快照型标题——人工当初把
「AI服务器与光通信硬件链」等线上的盘面综述也归进了线（稀释率最高
57.1%）。所以 blocked_hit_gt 中有一部分是「人工自己也没分干净」，
不等于规则错。本脚本会同时输出**分层明细**，供人工仲裁：
一部分是规则该改，一部分是基线该洗。
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.config import settings                     # noqa: E402
from app.database import async_session              # noqa: E402
from app.services import thread_router as tr        # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=25, help="每层展示多少条样本")
    a = ap.parse_args()

    async with async_session() as s:
        gt = set()
        rows = (await s.execute(text(
            "SELECT event_id FROM thread_events WHERE assigned_by='manual'"
        ))).all()
        for (eid,) in rows:
            gt.add(str(eid))
        evs = (await s.execute(text(
            "SELECT id, COALESCE(title,'') FROM events"
        ))).mappings().all()

    blocked_hit, blocked_miss, passed = [], [], 0
    th_gt = Counter()
    for r in evs:
        title, eid = r["title"], str(r["id"])
        if tr.is_market_snapshot(title):
            (blocked_hit if eid in gt else blocked_miss).append(title)
        else:
            passed += 1

    total = len(evs)
    print("=" * 74)
    print("市场快照规则验证（P2-11 三层规则）")
    print("=" * 74)
    print(f"事件总数 {total}｜人工基线 {len(gt)} 条")
    print()
    print(f"判为快照（不进线）  {len(blocked_hit) + len(blocked_miss):>5} 条"
          f"  ({100*(len(blocked_hit)+len(blocked_miss))/total:.1f}%)")
    print(f"  其中人工也认为该进线 → 潜在误杀 {len(blocked_hit):>5} 条  ⚠")
    print(f"  其中人工未归线       → 正确隔离 {len(blocked_miss):>5} 条")
    print(f"放行（进线）          {passed:>5} 条")
    print()

    # 分层：强信号 vs 弱信号
    strong = settings.THREAD_MARKET_SNAPSHOT_STRONG
    weak = settings.THREAD_MARKET_SNAPSHOT_WEAK
    rescue = settings.THREAD_MARKET_SNAPSHOT_RESCUE
    sh, sw = [], []
    for t in blocked_hit:
        if any(re.search(p, t) for p in strong):
            sh.append(t)
        else:
            sw.append(t)
    print("─" * 74)
    print("潜在误杀分层")
    print("─" * 74)
    print(f"  强信号命中 {len(sh)} 条（指数/交易时段，基本确属快照 → 基线待洗）")
    print(f"  弱信号命中 {len(sw)} 条（板块/概念股，需人工仲裁）")
    print()

    print(f"─ 强信号样本（前 {a.show} 条，建议：接受隔离，回头洗基线）")
    for t in sh[:a.show]:
        print(f"    {t[:56]}")
    print()
    print(f"─ 弱信号样本（前 {a.show} 条，建议：逐条人工仲裁）")
    for t in sw[:a.show]:
        hit_rescue = any(re.search(p, t) for p in rescue)
        print(f"    [{'有豁免词' if hit_rescue else '无豁免词'}] {t[:48]}")
    print()

    # 豁免机制生效情况
    rescued = 0
    for r in evs:
        t = r["title"]
        if any(re.search(p, t) for p in strong):
            continue
        if not any(re.search(p, t) for p in weak):
            continue
        if any(re.search(p, t) for p in rescue):
            rescued += 1
    print(f"豁免机制从弱信号中捞回 {rescued} 条（有具体事件、盘面只是结果）")
    print()
    print("结论口径：blocked_hit 不等于规则错误——ground truth 本身含")
    print("约 12.9% 快照型标题。需要人工仲裁：哪些是规则漏放，哪些是基线该洗。")


if __name__ == "__main__":
    asyncio.run(main())
