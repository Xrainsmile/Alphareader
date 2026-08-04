"""回填历史事件的语义向量（news.event_embedding），为「跨周期相似事件召回」冷启动。

事件合成器只在合成时写入向量，若不回填，需要等数周才能积累出可用的历史索引。
本脚本一次性把近 N 天已有事件包的聚合根全部向量化。

用法（容器内）：
    docker compose run --rm -v /home/Alphareader/backend/scripts:/app/scripts \\
        web python scripts/backfill_event_embeddings.py [天数]

默认回填 settings.EVENT_MEMORY_LOOKBACK_DAYS 天。可重复运行：
已有当前模型标签向量的记录会被跳过，切换 EMBEDDING_PROVIDER 后重跑即可整体重建。

成本参考：每条事件约 100 token，1000 条 ≈ 10 万 token，
按智谱 embedding-3 计价不足 ¥0.1。
"""

import asyncio
import logging
import sys

# 确保能导入 app 模块（容器内工作目录为 /app，本地可能为 backend）
sys.path.insert(0, "/app")
sys.path.insert(0, "/workspace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# 每批送去 Embedding API 的条数。批量调用可摊薄网络开销，
# 过大会触及部分服务商的单请求限制，32 是保守值。
BATCH_SIZE = 32


async def backfill(days: int | None = None) -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from app.config import settings
    from app.database import async_session
    from app.services import event_memory

    days = days or settings.EVENT_MEMORY_LOOKBACK_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    tag = event_memory.embedding_tag()

    async with async_session() as session:
        rows = (await session.execute(text("""
            SELECT id, event_title, event_summary
            FROM news
            WHERE related_to_id IS NULL
              AND event_title IS NOT NULL
              AND created_at >= :cutoff
              AND (event_embedding IS NULL OR event_embedding_model IS DISTINCT FROM :tag)
            ORDER BY created_at DESC
        """), {"cutoff": cutoff, "tag": tag})).mappings().all()

    if not rows:
        logger.info("No events need embedding (lookback=%dd, model=%s)", days, tag)
        return

    logger.info("Backfilling %d events (lookback=%dd, model=%s)", len(rows), days, tag)

    total = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        texts = [
            event_memory.event_doc_text(r["event_title"], r["event_summary"])
            for r in batch
        ]
        vectors = await event_memory.embed_texts(texts)
        pairs = [
            (str(r["id"]), vec)
            for r, vec in zip(batch, vectors)
            if vec
        ]
        if not pairs:
            # 整批失败通常是 API Key / 配额问题，继续跑下去只会重复失败
            logger.error("Batch %d-%d returned no vectors, aborting",
                         start, start + len(batch))
            break
        total += await event_memory.persist_embeddings(pairs)
        logger.info("  %d/%d done", total, len(rows))

    logger.info("event_embedding backfilled: %d rows", total)


if __name__ == "__main__":
    arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(backfill(arg))
