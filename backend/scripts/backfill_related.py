"""回填历史数据的 related_to_id。

使用 PostgreSQL pg_trgm 扩展的 trigram 相似度函数 similarity()，
找出 72 小时内不同源但标题高度相似的新闻对。
将后入库的 related_to_id 指向先入库的那条。
"""

import asyncio
import logging
import sys

# 确保能导入 app 模块
sys.path.insert(0, "/workspace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


async def backfill():
    from app.database import async_session
    from sqlalchemy import text

    # 确保 pg_trgm 扩展可用
    async with async_session() as session:
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await session.commit()
    logger.info("pg_trgm extension ready")

    async with async_session() as session:
        # 找 72 小时内、不同源但标题 trigram 相似度 > 0.5 的新闻对
        # 只处理 related_to_id 为 NULL 的 newer 记录
        result = await session.execute(text("""
            WITH pairs AS (
                SELECT
                    a.id AS older_id,
                    a.title AS older_title,
                    a.source AS older_source,
                    a.created_at AS older_time,
                    b.id AS newer_id,
                    b.title AS newer_title,
                    b.source AS newer_source,
                    b.created_at AS newer_time,
                    similarity(a.title, b.title) AS sim
                FROM news a
                JOIN news b ON a.id != b.id
                    AND a.source != b.source
                    AND a.created_at < b.created_at
                    AND b.created_at - a.created_at < interval '6 hours'
                WHERE a.created_at > NOW() - interval '72 hours'
                  AND b.created_at > NOW() - interval '72 hours'
                  AND b.related_to_id IS NULL
                  AND similarity(a.title, b.title) > 0.5
            )
            SELECT older_id, older_title, older_source,
                   newer_id, newer_title, newer_source, sim
            FROM pairs
            ORDER BY sim DESC
        """))
        rows = result.fetchall()
        logger.info("Found %d potential pairs", len(rows))

        # 去重：每个 newer_id 只保留相似度最高的一个配对
        seen_newer = set()
        updates = []
        for row in rows:
            older_id, older_title, older_source, newer_id, newer_title, newer_source, sim = row
            if newer_id in seen_newer:
                continue
            seen_newer.add(newer_id)
            updates.append((newer_id, older_id))
            logger.info(
                "  [%.3f] %s: \"%s\" -> %s: \"%s\"",
                sim, newer_source, newer_title[:50],
                older_source, older_title[:50],
            )

        logger.info("Will update %d records", len(updates))

        # 执行批量更新
        count = 0
        for newer_id, older_id in updates:
            await session.execute(
                text("UPDATE news SET related_to_id = :parent WHERE id = :child"),
                {"parent": str(older_id), "child": str(newer_id)},
            )
            count += 1

        await session.commit()
        logger.info("Done! Updated %d records with related_to_id", count)

    # 验证结果
    async with async_session() as session:
        result = await session.execute(text(
            "SELECT COUNT(*) AS total, COUNT(related_to_id) AS has_related FROM news "
            "WHERE created_at > NOW() - interval '72 hours'"
        ))
        row = result.fetchone()
        logger.info("Verification: %d total news (72h), %d with related_to_id", row[0], row[1])


if __name__ == "__main__":
    asyncio.run(backfill())
