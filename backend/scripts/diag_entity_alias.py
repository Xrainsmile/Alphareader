#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-5b 量化：实体别名分裂规模。

回答：全库有多少实体存在「同一实体、多个 canonical_name」的分裂？
影响多少条事件-线配对？修好能救回多少？
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session               # noqa: E402
from app.services import thread_router as tr         # noqa: E402


def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s\-_·、，,]+", "", s)
    s = re.sub(r"[()（）\[\]【】'\"]", "", s)
    return s


async def main():
    async with async_session() as s:
        ents = []
        for r in (await s.execute(text(
            "SELECT id, canonical_name, COALESCE(mention_count,0) FROM entities"
        ))).all():
            ents.append((str(r[0]), r[1], int(r[2])))

    print("=" * 78)
    print("P0-5b 量化：实体别名分裂")
    print("=" * 78)
    print(f"全库实体 {len(ents)} 个")
    print()

    # 1. 中英文分裂（人工映射表覆盖的高频对）
    pairs = [
        ("伊朗", "Iran"), ("美国", "US"), ("美国", "USA"), ("美国", "United States"),
        ("原油", "Oil"), ("原油", "Crude"), ("油价", "Oilprices"),
        ("中国", "China"), ("俄罗斯", "Russia"), ("以色列", "Israel"),
        ("沙特", "Saudi"), ("特朗普", "Trump"), ("拜登", "Biden"),
        ("英伟达", "Nvidia"), ("特斯拉", "Tesla"), ("苹果", "Apple"),
        ("欧盟", "EU"), ("日本", "Japan"), ("韩国", "Korea"),
        ("路透", "Reuters"), ("彭博", "Bloomberg"),
        ("美联储", "Fed"), ("美联储", "Federal Reserve"),
    ]
    by_cn = {n: (i, mc) for i, n, mc in ents}
    found = []
    for cn, en in pairs:
        a = by_cn.get(cn)
        b = by_cn.get(en)
        if a and b:
            found.append((cn, a[1], en, b[1]))
    print("─" * 78)
    print(f"【1】已知中英文对同时在库：{len(found)} 组")
    print("─" * 78)
    for cn, ca, en, cb in found:
        print(f"    {cn:<10}(mc={ca:>4})  ←→  {en:<16}(mc={cb:>4})")
    if not found:
        print("    （无）")
    print()

    # 2. 前缀包含分裂（霍尔木兹 vs 霍尔木兹海峡）
    print("─" * 78)
    print("【2】前缀包含分裂（A 是 B 的子串，且都 mc>=1）")
    print("─" * 78)
    names = [(n, mc) for _, n, mc in ents if mc >= 1]
    names.sort(key=lambda x: -len(x[0]))
    seen = set()
    sub = []
    for i, (a, mca) in enumerate(names):
        if len(a) < 2:
            continue
        for b, mcb in names:
            if a == b or len(b) < 2:
                continue
            if a != b and b in a and len(b) >= 2:
                key = tuple(sorted([a, b]))
                if key in seen:
                    continue
                seen.add(key)
                sub.append((a, mca, b, mcb))
    for a, mca, b, mcb in sub[:25]:
        print(f"    {a:<24}(mc={mca:>4})  含  {b:<24}(mc={mcb:>4})")
    print(f"    共 {len(sub)} 组")
    print()

    # 3. 模糊相似（可能是同一实体不同写法）
    print("─" * 78)
    print("【3】高相似度实体对（ratio>=0.85 且不同名）")
    print("─" * 78)
    small = [(n, mc) for _, n, mc in ents if mc >= 2][:400]
    fuzzy = []
    for i in range(len(small)):
        for j in range(i + 1, len(small)):
            a, b = small[i][0], small[j][0]
            if a == b or not a or not b:
                continue
            if a in b or b in a:
                continue
            r = SequenceMatcher(None, norm(a), norm(b)).ratio()
            if r >= 0.85:
                fuzzy.append((r, a, small[i][1], b, small[j][1]))
    fuzzy.sort(reverse=True)
    for r, a, ca, b, cb in fuzzy[:20]:
        print(f"    {r:.2f}  {a:<20}(mc={ca:>4})  ~  {b:<20}(mc={cb:>4})")
    print(f"    共 {len(fuzzy)} 组")
    print()

    # 4. 影响面：多少配对因分裂而 shared=0
    async with async_session() as s:
        gt = {str(a): str(b) for a, b in (await s.execute(text(
            "SELECT event_id, thread_id FROM thread_events WHERE assigned_by='manual'"
        ))).all()}
        ev_ent = defaultdict(dict)
        for r in (await s.execute(text("""
            SELECT ee.event_id, e.canonical_name, ee.weight
            FROM event_entities ee JOIN entities e ON e.id = ee.entity_id
        """))).all():
            ev_ent[str(r[0])][r[1]] = int(r[2] or 1)
        th = {}
        for r in (await s.execute(text(
            "SELECT id, core_entities FROM threads"))).mappings().all():
            ce = r["core_entities"] or {}
            if isinstance(ce, str):
                try:
                    ce = json.loads(ce)
                except Exception:
                    ce = {}
            th[str(r["id"])] = {k: int(v) for k, v in ce.items()}

    denylist = tr._denylist() if hasattr(tr, "_denylist") else set()

    # 建别名映射
    alias = {}
    for cn, _ca, en, _cb in found:
        alias[en] = cn
        alias[cn] = cn
    for a, _mca, b, _mcb in sub:
        alias[b] = a   # 短名 → 长名
        alias[a] = a
    for _r, a, _ca, b, _cb in fuzzy:
        alias.setdefault(b, a)
        alias.setdefault(a, a)

    def canon(n):
        return alias.get(n, n)

    before_ok = after_ok = 0
    zero_before = []
    rescued = []
    for eid, tid in gt.items():
        ev = {k: v for k, v in ev_ent.get(eid, {}).items() if k not in denylist}
        tc = {k: v for k, v in th.get(tid, {}).items() if k not in denylist}
        if not ev or not tc:
            continue
        # 现状
        shared_now = set(ev) & set(tc)
        e_now = tr.weighted_jaccard_normalized(ev, tc)
        ok_now, _ = tr.entity_gate(e_now, len(shared_now))
        # 别名归一后
        ev2, tc2 = defaultdict(int), defaultdict(int)
        for k, v in ev.items():
            ev2[canon(k)] += v
        for k, v in tc.items():
            tc2[canon(k)] += v
        ev2, tc2 = dict(ev2), dict(tc2)
        shared_new = set(ev2) & set(tc2)
        e_new = tr.weighted_jaccard_normalized(ev2, tc2)
        ok_new, _ = tr.entity_gate(e_new, len(shared_new))

        before_ok += ok_now
        after_ok += ok_new
        if ok_new and not ok_now:
            rescued.append((eid, e_now, e_new, sorted(shared_now), sorted(shared_new)))

    print("─" * 78)
    print("【4】影响面：别名归一后能救回多少配对")
    print("─" * 78)
    total = sum(1 for eid, tid in gt.items()
                if ev_ent.get(eid) and th.get(tid))
    print(f"  有效配对        {total}")
    print(f"  现状过门控      {before_ok}  ({100*before_ok/max(total,1):.1f}%)")
    print(f"  别名归一后过    {after_ok}  ({100*after_ok/max(total,1):.1f}%)")
    print(f"  → 净救回        {after_ok - before_ok} 条 "
          f"(+{100*(after_ok-before_ok)/max(total,1):.1f}pp)")
    print()
    if rescued:
        print(f"  救回样本（前 12 条）：")
        for eid, eo, en, so, sn in rescued[:12]:
            print(f"    E {eo:.4f}→{en:.4f}  shared {so}→{sn}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
