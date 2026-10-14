#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回刷：清掉「日本」的 is_generic 标记（P0-6）。

GENERIC_ENTITIES 移除了「日本」，但库里 entities.is_generic 是写入时的
快照，存量行仍是 true，_load_event_entities 的 SQL 会把它们过滤掉。
必须回刷才能生效。

    python migrate_unset_generic_jp.py          # dry-run
    python migrate_unset_generic_jp.py --apply  # 写库
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.database import async_session  # noqa: E402

TARGET = "日本"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    async with async_session() as s:
        rows = (await s.execute(text("""
            SELECT id, canonical_name, is_generic, mention_count
            FROM entities
            WHERE canonical_name = :n OR canonical_name LIKE :p
        """), {"n": TARGET, "p": f"%{TARGET}%"})).mappings().all()

    hit = [r for r in rows if r["is_generic"]]
    print("=" * 78)
    print(f"回刷 is_generic：{TARGET}  "
          f"{'[APPLY]' if args.apply else '[DRY-RUN]'}")
    print("=" * 78)
    print(f"  匹配实体 {len(rows)} 个，其中 is_generic=true {len(hit)} 个")
    for r in rows[:10]:
        print(f"    {r['canonical_name']:<24} generic={r['is_generic']}  "
              f"mention={r['mention_count']}")
    print()

    if not hit:
        print("  无需回刷。")
        return

    if not args.apply:
        print("  [DRY-RUN] 未写库。确认后加 --apply。")
        return

    async with async_session() as s:
        res = await s.execute(text("""
            UPDATE entities SET is_generic = false
            WHERE is_generic = true
              AND (canonical_name = :n OR canonical_name LIKE :p)
        """), {"n": TARGET, "p": f"%{TARGET}%"})
        await s.commit()
        print(f"  [APPLY] 已更新 {res.rowcount} 行。")


if __name__ == "__main__":
    asyncio.run(main())
