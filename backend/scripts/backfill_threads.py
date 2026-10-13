#!/usr/bin/env python
"""历史事件批量归线（世界线冷启动）。

为什么需要这个脚本
------------------
thread_router.route_event 只在「事件合成阶段」被调用，回填的 810 个历史
事件从未走过归线流程，因此：
  - threads 只有 1 条（maybe_create_thread 在影子模式下也会建线，但
    chapter_count=0，因为影子模式不写 thread_events）
  - thread_events = 0，实体层建好了却没有任何事件挂到线上

本脚本复用线上同一套 route_event（不重写打分逻辑），保证批量结果与
增量链路完全一致，避免出现「回填一套口径、线上另一套口径」。

影子模式说明
------------
THREAD_ROUTING_SHADOW=True 时只算分留痕、不写 thread_events。
要让历史事件真正挂线，必须先关闭影子模式（THREAD_ROUTING_SHADOW=False）。
脚本启动时会检测并明确提示，不会静默地什么都不做。

用法
----
    python scripts/backfill_threads.py            # 全量
    python scripts/backfill_threads.py --limit 20 # 试跑
    python scripts/backfill_threads.py --order desc
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session  # noqa: E402
from app.services import thread_router  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("backfill_threads")

# 并发上限。归线是 DB 密集操作（每个事件要加载全部候选线算分），
# 并发过高会打满连接池。取 8 保守起步。
MAX_CONCURRENCY = 8


async def get_pending_event_ids(order: str) -> list[uuid.UUID]:
    """取待归线事件：有实体 且 尚未挂到任何线上。

    为什么要「有实体」这个条件：没有实体的事件在 E=0.55 权重下
    S 分必为 0，归线无意义，空跑纯属浪费。

    为什么要「未挂线」：保证幂等，重复执行不会重复写入。
    """
    direction = "DESC" if order == "desc" else "ASC"
    sql = text(f"""
        SELECT DISTINCT ee.event_id
        FROM event_entities ee
        JOIN entities e ON e.id = ee.entity_id
        WHERE COALESCE(e.is_generic, false) = false
          AND NOT EXISTS (
              SELECT 1 FROM thread_events te WHERE te.event_id = ee.event_id
          )
        ORDER BY ee.event_id {direction}
    """)
    async with async_session() as session:
        rows = (await session.execute(sql)).all()
    return [r[0] for r in rows]


async def process_one(sem: asyncio.Semaphore, event_id: uuid.UUID) -> tuple[bool, str]:
    async with sem:
        try:
            await thread_router.route_event(event_id)
            return True, ""
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"


async def main() -> int:
    parser = argparse.ArgumentParser(description="历史事件批量归线")
    parser.add_argument("--limit", type=int, default=0, help="试跑条数，0=全量")
    parser.add_argument(
        "--order", choices=["asc", "desc"], default="asc", help="处理顺序"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("世界线批量归线")
    logger.info("THREAD_ROUTING_ENABLED = %s", settings.THREAD_ROUTING_ENABLED)
    logger.info("THREAD_ROUTING_SHADOW  = %s", settings.THREAD_ROUTING_SHADOW)
    logger.info("T_JOIN = %s", settings.THREAD_T_JOIN)
    logger.info("=" * 60)

    if not settings.THREAD_ROUTING_ENABLED:
        logger.error("THREAD_ROUTING_ENABLED=False，归线总开关关闭，退出")
        return 1

    if settings.THREAD_ROUTING_SHADOW:
        logger.warning("=" * 60)
        logger.warning("影子模式仍开启：本次只会算分留痕，不会写入 thread_events。")
        logger.warning("历史事件不会真正挂线。若要真实归线，请先关闭影子模式：")
        logger.warning("    .env 设置 THREAD_ROUTING_SHADOW=false 并重启 alpha-web")
        logger.warning("=" * 60)

    ids = await get_pending_event_ids(args.order)
    if args.limit > 0:
        ids = ids[: args.limit]

    total = len(ids)
    logger.info("待归线事件：%d", total)
    if total == 0:
        logger.info("没有待归线事件，退出")
        return 0

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    ok = fail = 0
    errors: list[str] = []

    for i in range(0, total, MAX_CONCURRENCY):
        batch = ids[i : i + MAX_CONCURRENCY]
        results = await asyncio.gather(
            *(process_one(sem, eid) for eid in batch),
            return_exceptions=True,
        )
        for eid, res in zip(batch, results):
            if isinstance(res, Exception):
                fail += 1
                errors.append(f"{eid}: {res}")
            elif res[0]:
                ok += 1
            else:
                fail += 1
                errors.append(f"{eid}: {res[1]}")

        done = min(i + MAX_CONCURRENCY, total)
        logger.info("进度：%d / %d", done, total)

    logger.info("=" * 60)
    logger.info("归线完成：成功 %d、失败 %d、总计 %d", ok, fail, total)
    if errors:
        logger.warning("前 5 条失败：")
        for e in errors[:5]:
            logger.warning("  %s", e)
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
