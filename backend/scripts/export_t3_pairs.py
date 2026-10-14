#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 T3 全量近邻对 —— 生成可直接粘贴进 ALIAS_MAP 的字典。

T3 = 事件与线零共享实体，但存在"差一点就接上"的近邻。
只导出高置信近邻，排除噪声：
  - 子串型：要求较短一方长度 >= 3（"AI" 这类 2 字子串是噪声）
  - 且较短一方不是纯数字
  - 别名表可接型：canonicalize 后相等，直接采信
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict, Counter

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session            # noqa: E402
from app.config import settings                   # noqa: E402
from app.services import thread_router as tr      # noqa: E402
from app.services.entity_writer import canonicalize  # noqa: E402


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
        gt = [(str(a), str(b)) for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events "
            "WHERE assigned_by='manual'"))).all()]
        ev_ent = defaultdict(dict)
        for r in (await s.execute(text("""
            SELECT ee.event_id, e.canonical_name, ee.weight
            FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        """))).all():
            ev_ent[str(r[0])][r[1]] = int(r[2] or 1)
        threads = {str(r["id"]): (r["title"], parse_ce(r["core_entities"]))
                   for r in (await s.execute(text(
                       "SELECT id, title, core_entities FROM threads"
                   ))).mappings().all()}

    denylist = tr._denylist() if hasattr(tr, "_denylist") else set()

    # (src -> dst, kind, 命中次数, 样例线)
    pairs: dict[tuple[str, str, str], list] = defaultdict(
        lambda: [0, None])

    for eid, tid in gt:
        ev = {k: v for k, v in ev_ent.get(eid, {}).items() if k not in denylist}
        tc = {k: v for k, v in (threads.get(tid, ("", {}))[1]).items()
              if k not in denylist}
        if not ev or not tc:
            continue
        e = tr.weighted_jaccard_normalized(ev, tc)
        g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
        if g:
            continue

        ttitle = threads.get(tid, ("",))[0]
        for a in ev:
            for b in tc:
                if a == b:
                    continue
                # 事件侧写法 -> 线侧规范名
                if canonicalize(a)[0] == canonicalize(b)[0] and a != b:
                    key = (a, b, "alias")
                    pairs[key][0] += 1
                    pairs[key][1] = pairs[key][1] or ttitle
                    continue
                if a in b or b in a:
                    short = a if len(a) <= len(b) else b
                    if len(short) < 3 or short.isdigit():
                        continue
                    key = (a, b, "substr")
                    pairs[key][0] += 1
                    pairs[key][1] = pairs[key][1] or ttitle

    print("=" * 78)
    print("T3 全量近邻对导出")
    print("=" * 78)
    print(f"近邻对总数 {len(pairs)}")
    print()

    alias_p = {k: v for k, v in pairs.items() if k[2] == "alias"}
    sub_p = {k: v for k, v in pairs.items() if k[2] == "substr"}

    print("─" * 78)
    print(f"【1】别名表可接（canonicalize 后相等）—— {len(alias_p)} 对")
    print("─" * 78)
    for (a, b, _k), (n, tt) in sorted(alias_p.items(), key=lambda x: -x[1][0]):
        print(f"  {n:>2}x  {a:<28} -> {b:<20}  ({tt})")
    print()

    print("─" * 78)
    print(f"【2】子串型（需人工确认方向）—— {len(sub_p)} 对")
    print("─" * 78)
    for (a, b, _k), (n, tt) in sorted(sub_p.items(), key=lambda x: -x[1][0]):
        direction = "事件⊃线" if b in a else "线⊃事件"
        print(f"  {n:>2}x  {a:<28} ~ {b:<20} [{direction}]  ({tt})")
    print()

    print("─" * 78)
    print("【3】可直接粘贴进 ALIAS_MAP 的候选（子串型，短→长 或 长→短 需判断）")
    print("─" * 78)
    print("  生成规则：把「事件侧写法」映射到「线侧规范名」，")
    print("  即 ALIAS_MAP[事件侧] = 线侧。方向：事件侧通常更啰嗦。")
    print()
    print("CANDIDATE_ALIAS_MAP: dict[str, str] = {")
    for (a, b, _k), (n, tt) in sorted(sub_p.items(), key=lambda x: -x[1][0]):
        # 谁更长谁更像"啰嗦写法"，映射到短的；若长度相等跳过
        if len(a) > len(b):
            src, dst = a, b
        elif len(b) > len(a):
            src, dst = b, a
        else:
            continue
        print(f"    {src!r}: {dst!r},   # {n}x  {tt}")
    print("}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
