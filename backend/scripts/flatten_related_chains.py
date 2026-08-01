"""一次性回填：压平历史事件聚合链（A←B←C → A←C）。

背景：去重器基于 90 分钟 embedding 索引做事件聚合，后到的报道可能
挂到中间节点而非最终根，形成链式结构。hot-topics、前端分组、事件合成
均假设星型拓扑（根+直接子报道），链式会导致：
  - 前端分组时孙子节点找不到父 → 变成孤儿卡
  - 事件合成候选查询（根必须 related_to_id IS NULL）漏掉整个簇
pipeline 已在入库时压平新数据（_resolve_event_roots），本脚本处理存量。

执行（容器内）：
    docker compose run --rm -e PYTHONPATH=/app \
        -v /home/Alphareader/backend/scripts:/app/scripts \
        web python scripts/flatten_related_chains.py
"""

import asyncio
import logging

from sqlalchemy import text

from app.database import async_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("flatten_chains")

# 递归 CTE 求每个节点的最终根，再把所有非根节点的 related_to_id 直指根。
# depth 限 10 防环路；n.related_to_id IS NOT NULL 防止把根指向自己。
FLATTEN_SQL = text("""
    WITH RECURSIVE chain AS (
        SELECT id, id AS root, 0 AS depth
        FROM news
        WHERE related_to_id IS NULL
        UNION ALL
        SELECT n.id, c.root, c.depth + 1
        FROM news n
        JOIN chain c ON n.related_to_id = c.id
        WHERE c.depth < 10
    )
    UPDATE news n
    SET related_to_id = chain.root
    FROM chain
    WHERE n.id = chain.id
      AND n.related_to_id IS NOT NULL
      AND n.related_to_id IS DISTINCT FROM chain.root
""")

CHAIN_COUNT_SQL = text("""
    SELECT COUNT(*)
    FROM news child
    JOIN news parent ON parent.id = child.related_to_id
    WHERE parent.related_to_id IS NOT NULL
""")


async def main() -> None:
    async with async_session() as session:
        before = (await session.execute(CHAIN_COUNT_SQL)).scalar() or 0
        logger.info("链式中间节点的子报道（待压平）: %d", before)
        if before == 0:
            logger.info("无需处理")
            return
        result = await session.execute(FLATTEN_SQL)
        await session.commit()
        logger.info("已压平 %d 行", result.rowcount)
        after = (await session.execute(CHAIN_COUNT_SQL)).scalar() or 0
        logger.info("压平后剩余链式子报道: %d", after)


if __name__ == "__main__":
    asyncio.run(main())
