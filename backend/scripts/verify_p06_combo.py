#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""联合验证：denylist 拆分 × 动态 canonicalize 的收益。

背景疑点（关键）：
    export_t3_pairs 显示 canonicalize('霍尔木兹') == canonicalize('霍尔木兹海峡')，
    即 ALIAS_MAP **已经**有这条别名，但生产上 E 仍是 0。
    推论：ALIAS_MAP 只在**实体写入时**调用一次，历史事件/线的
    canonical_name 是旧快照，ALIAS_MAP 后续新增的别名对存量数据不生效。

解法候选：
    R0 生产现状（旧 denylist 52 词，不做动态 canonicalize）
    R1 新 denylist（仅形式词 24 词）
    R2 R1 + 比较时两侧动态 canonicalize（不改库，覆盖全部存量）
    R3 R2 + T3 候选别名补丁

本脚本只读评估，不写库。
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session            # noqa: E402
from app.config import settings                   # noqa: E402
from app.services import thread_router as tr      # noqa: E402
from app.services.entity_writer import canonicalize  # noqa: E402

OLD_DENY = set(settings.THREAD_ENTITY_DENYLIST or [])  # 容器内仍是旧值

# P0-6 新表：只保留披露形式
NEW_DENY = {
    "8-K", "8-K/A", "10-K", "10-Q", "6-K", "20-F", "S-1", "424B5",
    "财报", "季报", "年报", "半年报", "中报", "业绩公告", "重大协议",
    "重大事项", "经营业绩", "其他事项", "退市通知", "监管披露",
    "SEC", "美国证券交易委员会", "披露文件", "定期报告",
}

# T3 候选补丁（事件侧写法 -> 线侧规范名）
PATCH = {
    "服务器": "AI服务器",
    "标普500指数期货": "标普500指数",
    "美国7月CPI": "CPI",
    "美国CPI": "CPI",
    "核心CPI": "CPI",
    "霍尔木兹": "霍尔木兹海峡",
}


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


def merge(d: dict, use_patch: bool = True) -> dict:
    """canonicalize 后同名合并，权重取最大。"""
    out: dict[str, int] = {}
    for k, v in d.items():
        c = (PATCH.get(k) if use_patch else None) or canonicalize(k)[0]
        out[c] = max(out.get(c, 0), v)
    return out


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
        threads = {str(r["id"]): parse_ce(r["core_entities"])
                   for r in (await s.execute(text(
                       "SELECT id, core_entities FROM threads"))).mappings().all()}

    def run(deny, do_canon, use_patch=True):
        ok = total = 0
        for eid, tid in gt:
            ev = {k: v for k, v in ev_ent.get(eid, {}).items() if k not in deny}
            tc = {k: v for k, v in threads.get(tid, {}).items() if k not in deny}
            if do_canon:
                ev, tc = merge(ev, use_patch), merge(tc, use_patch)
            if not ev or not tc:
                continue
            total += 1
            e = tr.weighted_jaccard_normalized(ev, tc)
            g, _ = tr.entity_gate(e, len(set(ev) & set(tc)))
            ok += g
        return ok, total

    print("=" * 78)
    print("联合验证：denylist 拆分 × 动态 canonicalize")
    print("=" * 78)
    print(f"容器内 denylist 现状 {len(OLD_DENY)} 词（旧）  新表 {len(NEW_DENY)} 词")
    print(f"候选补丁 {len(PATCH)} 条")
    print()

    print("─" * 78)
    print("【1】五种配置对比")
    print("─" * 78)
    cfgs = [
        ("R0 生产现状（旧deny·无canon）", OLD_DENY, False, True),
        ("R1 新denylist（仅形式词）",     NEW_DENY, False, True),
        ("R2 R1 + 动态 canonicalize",     NEW_DENY, True,  False),
        ("R3 R2 + T3候选补丁",            NEW_DENY, True,  True),
    ]
    base = None
    for label, deny, canon, patch in cfgs:
        ok, tot = run(deny, canon, patch)
        if base is None:
            base = ok
        print(f"  {label:<32} {ok:>3}/{tot}  {100*ok/max(tot,1):>5.1f}%   "
              f"({ok-base:+d})")
    print()

    # 验证 ALIAS_MAP 存量失效假设
    print("─" * 78)
    print("【2】验证：ALIAS_MAP 对存量数据是否失效")
    print("─" * 78)
    ev_names = set()
    th_names = set()
    for eid, tid in gt:
        ev_names |= set(ev_ent.get(eid, {}))
        th_names |= set(threads.get(tid, {}))
    unresolved = []
    for n in sorted(ev_names | th_names):
        c = canonicalize(n)[0]
        if c != n:
            unresolved.append((n, c, n in ev_names, n in th_names))
    print(f"  可被 ALIAS_MAP 改写但库里仍是原名的实体：{len(unresolved)} 个")
    for n, c, ine, inth in unresolved[:15]:
        side = []
        if ine:
            side.append("事件侧")
        if inth:
            side.append("线侧")
        print(f"    {n:<28} -> {c:<24} [{'/'.join(side)}]")
    print()
    print("  → 这些名字在**比较时**才归一化就能接上，无需改库。")
    print()


if __name__ == "__main__":
    asyncio.run(main())
