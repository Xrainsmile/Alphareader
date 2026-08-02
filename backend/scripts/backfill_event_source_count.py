"""回填历史事件的 event_source_count，使其与统一口径一致。

统一口径：独立信源数 = COUNT(DISTINCT source)
                       WHERE id = 事件根 OR related_to_id = 事件根
即对整个事件（根报道 + 全部子报道）的来源去重，根来源与子报道来源相同时只计 1 次。

历史数据可能因「根来源 +1」逻辑而高估信源数，本脚本一次性用正确口径重算
event_source_count；后续事件合成器已按相同口径写入，无需重复运行。
"""

import asyncio
import logging
import sys

# 确保能导入 app 模块（容器内工作目录为 /app，本地可能为 backend）
sys.path.insert(0, "/app")
sys.path.insert(0, "/workspace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


async def backfill():
    from app.database import async_session
    from sqlalchemy import text

    async with async_session() as session:
        # 单语句批量更新所有事件根：
        # 子查询按 root_id 聚合去重信源数（根报道 + 子报道 UNION ALL），
        # 再用它更新 news 表中 related_to_id IS NULL 的根记录。
        result = await session.execute(text("""
            UPDATE news AS p
            SET event_source_count = GREATEST(sub.source_count, 1)
            FROM (
                SELECT root_id, COUNT(DISTINCT source) AS source_count
                FROM (
                    SELECT id AS root_id, source
                    FROM news
                    WHERE related_to_id IS NULL
                    UNION ALL
                    SELECT related_to_id AS root_id, source
                    FROM news
                    WHERE related_to_id IS NOT NULL
                ) sources
                GROUP BY root_id
            ) sub
            WHERE p.id = sub.root_id
              AND p.related_to_id IS NULL
        """))
        await session.commit()
        logger.info("event_source_count backfilled: %s rows updated", result.rowcount)


if __name__ == "__main__":
    asyncio.run(backfill())
