#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""世界线碎片合并扫描（P1-8）。

背景
----
现网「伊朗 / 霍尔木兹 / 油价」主题被拆成 17 条线（33+10+9+7+7+6+5+4+3+2…），
根因是早期随便建线后，后续事件被第一条匹配的线吸走而非最合适的线——
**该合的没合**。人工基线聚合显示这些应归并为 3 条：地理博弈 / 价格传导 / 袭击事件。

本脚本只做「扫描 + 建议」，默认不写库（--apply 才执行合并）。
合并语义：把 src 线的章节迁到 dst 线，src 置 merged 并写 merged_into_id
（threads 表已有该字段与 'merged' 状态，前端/API 可据此做重定向）。

用法
----
    python lint_thread_fragments.py                 # 只出建议
    python lint_thread_fragments.py --apply         # 执行合并
    python lint_thread_fragments.py --threshold 0.5 # 自定义相似度阈值
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from itertools import combinations

from sqlalchemy import text

sys.path.insert(0, ".")
from app.config import settings                       # noqa: E402
from app.database import async_session                # noqa: E402


async def load_threads() -> list[dict]:
    sql = text("""
        SELECT t.id, t.title, t.chapter_count, t.core_entities, t.mechanism_key,
               t.last_event_at, t.status
        FROM threads t
        WHERE t.status NOT IN ('merged', 'split')
        ORDER BY t.chapter_count DESC
    """)
    async with async_session() as s:
        rows = (await s.execute(sql)).mappings().all()
    return [dict(r) for r in rows]


def ent_weights(core) -> dict[str, int]:
    if isinstance(core, dict):
        return {str(k): int(v or 1) for k, v in core.items()}
    if isinstance(core, list):
        return {str(x): 1 for x in core}
    return {}


def jaccard(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    inter = sum(min(a.get(k, 0), b.get(k, 0)) for k in keys)
    union = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
    return inter / union if union else 0.0


def build_pairs(threads: list[dict], threshold: float) -> list[dict]:
    out = []
    for a, b in combinations(threads, 2):
        sim = jaccard(ent_weights(a.get("core_entities")), ent_weights(b.get("core_entities")))
        if sim < threshold:
            continue
        # dst = 章数多的那条（保留更完整的叙事）；同章数取更早更新的
        dst, src = (a, b) if (a["chapter_count"], str(a["last_event_at"])) >= \
                             (b["chapter_count"], str(b["last_event_at"])) else (b, a)
        out.append({
            "dst_id": dst["id"], "dst_title": dst["title"], "dst_n": dst["chapter_count"],
            "src_id": src["id"], "src_title": src["title"], "src_n": src["chapter_count"],
            "sim": round(sim, 3),
            "shared": sorted(set(ent_weights(a.get("core_entities"))) &
                             set(ent_weights(b.get("core_entities")))),
        })
    out.sort(key=lambda x: -x["sim"])
    return out


async def apply_merge(pair: dict) -> bool:
    """把 src 线章节迁到 dst，src 置 merged。返回是否成功。"""
    async with async_session() as s:
        try:
            # 1) 迁移章节（去重：已存在于 dst 的跳过）
            await s.execute(text("""
                INSERT INTO thread_events
                    (thread_id, event_id, role, chapter_id, assigned_by,
                     match_score, snapshot_title)
                SELECT :dst, te.event_id, te.role, gen_random_uuid(),
                       'auto', te.match_score, te.snapshot_title
                FROM thread_events te
                WHERE te.thread_id = :src
                  AND NOT EXISTS (
                      SELECT 1 FROM thread_events x
                      WHERE x.thread_id = :dst AND x.event_id = te.event_id
                  )
            """), {"dst": pair["dst_id"], "src": pair["src_id"]})
            # 2) src 置 merged 并写重定向指针；章节由触发器/外键 CASCADE 前先删
            await s.execute(
                text("DELETE FROM thread_events WHERE thread_id = :src"),
                {"src": pair["src_id"]})
            await s.execute(text("""
                UPDATE threads SET status='merged', merged_into_id=:dst,
                       chapter_count=0, updated_at=now() WHERE id=:src
            """), {"dst": pair["dst_id"], "src": pair["src_id"]})
            # 3) 回写 dst 统计
            await s.execute(text("""
                UPDATE threads t SET chapter_count = c.n,
                       last_event_at = c.mx, updated_at = now()
                FROM (SELECT thread_id, COUNT(*) n, MAX(occurred_at) mx
                      FROM thread_events WHERE thread_id=:dst GROUP BY 1) c
                WHERE t.id = :dst AND c.thread_id = t.id
            """), {"dst": pair["dst_id"]})
            await s.commit()
            return True
        except Exception as exc:  # noqa: BLE001
            await s.rollback()
            print("  合并失败 %s -> %s: %s" % (pair["src_title"], pair["dst_title"], exc))
            return False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行合并（默认只出建议）")
    ap.add_argument("--threshold", type=float,
                    default=settings.THREAD_MERGE_SIMILARITY)
    a = ap.parse_args()

    threads = await load_threads()
    print("扫描 %d 条线，相似度阈值 %.2f\n" % (len(threads), a.threshold))

    pairs = build_pairs(threads, a.threshold)
    if not pairs:
        print("未发现碎片线。")
        return

    print("发现 %d 组疑似碎片：\n" % len(pairs))
    print("| 保留（dst） | 章 | 合并（src） | 章 | 相似度 | 共享实体 |")
    print("|---|---|---|---|---|---|")
    for p in pairs:
        print("| %s | %d | %s | %d | %.3f | %s |" % (
            (p["dst_title"] or "")[:26], p["dst_n"],
            (p["src_title"] or "")[:26], p["src_n"], p["sim"],
            "、".join(p["shared"][:4])))

    if not a.apply:
        print("\n（只读模式。加 --apply 执行合并）")
        return

    # 按 dst 去重：一条 dst 一次只合一个 src，避免链式误合
    print("\n执行合并：")
    used_dst: set[uuid.UUID] = set()
    used_src: set[uuid.UUID] = set()
    ok = 0
    for p in pairs:
        if p["dst_id"] in used_dst or p["src_id"] in used_src:
            continue
        r = await apply_merge(p)
        if r:
            used_dst.add(p["dst_id"])
            used_src.add(p["src_id"])
            ok += 1
            print("  ✓ %s → %s" % (p["src_title"], p["dst_title"]))
    print("\n完成 %d 组合并。" % ok)


if __name__ == "__main__":
    asyncio.run(main())
