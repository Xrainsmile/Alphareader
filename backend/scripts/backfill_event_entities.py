"""把已回填的 news.entities 搬运进实体层（entities / event_entities）。

背景：backfill_entities.py 补齐了历史新闻的 news.entities / entity_types，
但 entities 表只由事件合成阶段（synthesize_events）填充，而该阶段只扫描
最近 EVENT_SYNTH_WINDOW_HOURS(12h) 内有新报道的簇，历史事件不会被重新合成。

因此历史事件虽有实体，却进不了实体层。本脚本绕过窗口限制，直接对
现存 events 重跑「收集簇实体 → 关联入库」这一步：

    _collect_cluster_entities(event_id) → entity_writer.link_event_entities()

不调用 LLM、不改动 events 表、不扰动已有事件，仅补齐实体层关联。
幂等：重复执行不会产生重复关联（link_event_entities 内部保证）。

在容器内运行：python scripts/backfill_event_entities.py
"""

import asyncio
import logging
import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ── 可调参数 ──
BATCH_LOG = 50          # 每处理 N 个事件打印一次进度
MAX_CONCURRENCY = 3      # 数据库并发上限（并发过高会在 entities 唯一键上死锁）


async def main() -> None:
    from app.database import async_session
    from app.services import entity_writer
    from app.services.event_synthesizer import _collect_cluster_entities

    if not entity_writer.enabled():
        logger.error("实体抽取总开关未启用（ENTITY_EXTRACTION_ENABLED=False），结束。")
        return

    # 1) 取全部事件 id
    async with async_session() as session:
        result = await session.execute(text("SELECT id FROM events ORDER BY created_at DESC"))
        event_ids = [str(r[0]) for r in result.fetchall()]

    logger.info("待处理事件数：%d", len(event_ids))
    if not event_ids:
        return

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    linked_events = 0
    linked_total = 0
    empty_events = 0
    failed = 0
    done = 0

    async def _worker(eid: str):
        nonlocal linked_events, linked_total, empty_events, failed, done
        async with sem:
            try:
                # 注意：_collect_cluster_entities 异常时返回 []（长度为 1 的 tuple 亦兼容）
                res = await _collect_cluster_entities(eid)
                names = res[0] if isinstance(res, (list, tuple)) else []
                type_map = res[1] if isinstance(res, tuple) and len(res) > 1 else {}
                if not names:
                    empty_events += 1
                else:
                    async with async_session() as s:
                        n = await entity_writer.link_event_entities(
                            s, eid, names, type_map=type_map
                        )
                        await s.commit()
                    if n:
                        linked_events += 1
                        linked_total += n
            except Exception as e:  # noqa: BLE001 — 单条失败不影响整体
                failed += 1
                logger.warning("事件 %s 实体关联失败：%s", eid, e)
            finally:
                done += 1
                if done % BATCH_LOG == 0:
                    logger.info("进度：%d / %d", done, len(event_ids))

    await asyncio.gather(*[_worker(e) for e in event_ids])

    logger.info(
        "搬运完成：关联事件 %d 个、关联记录 %d 条；无实体事件 %d 个；失败 %d 个；总计 %d",
        linked_events, linked_total, empty_events, failed, len(event_ids),
    )


if __name__ == "__main__":
    asyncio.run(main())
