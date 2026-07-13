"""回填未翻译的英文新闻标题和摘要。

背景：两阶段英文评分中，翻译阶段（stage 2）API 失败时条目仍会以英文标题入库。
本脚本找出存量中标题不含中文字符的英文信源新闻，重新调用翻译 API 补齐中文标题/摘要。

运行方式（容器内）：
  docker compose run --rm -v /home/Alphareader/backend/scripts:/app/scripts web python scripts/backfill_translation.py
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import httpx
from sqlalchemy import text

from app.database import async_session
from app.config import settings
from app.services.llm_news_filter import _translate_batch_once, RawNewsItem

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 10
MAX_CONCURRENCY = 3
WINDOW_DAYS = 7

# 英文信源列表（与 rss_fetcher.py 中的信源对应）
EN_SOURCES = (
    'MarketWatch', 'Seeking Alpha', 'CNBC', 'Investing.com', 'Reuters',
    'Yahoo Finance', 'SEC EDGAR', 'Finnhub', 'TechCrunch', 'Hacker News',
    'OpenAI Blog', 'Google AI Blog', 'Anthropic', 'Hugging Face',
    'MIT Tech Review', 'MarkTechPost', 'arXiv cs.AI', 'arXiv cs.CL',
    'The Verge AI', 'Last Week in AI', 'The Gradient', 'NVIDIA Blog',
    'Simon Willison',
)


def _contains_cjk(s: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in (s or ''))


async def main():
    async with async_session() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
        # 查找最近 WINDOW_DAYS 天内、英文信源、标题不含中文的条目
        result = await session.execute(text("""
            SELECT id, title, ai_summary, content, source, url
            FROM news
            WHERE source = ANY(:sources)
              AND created_at >= :cutoff
              AND ai_score >= 5
            ORDER BY created_at DESC
        """), {"sources": list(EN_SOURCES), "cutoff": cutoff})

        rows = [dict(r._mapping) for r in result.all()]
        untranslated = [r for r in rows if not _contains_cjk(r["title"])]
        logger.info("Found %d untranslated English news (out of %d total English news in %dd)",
                     len(untranslated), len(rows), WINDOW_DAYS)

        if not untranslated:
            logger.info("Nothing to backfill. All English news already translated.")
            return

        # 构建 RawNewsItem 列表
        items = []
        for r in untranslated:
            items.append(RawNewsItem(
                title=r["title"],
                content=r["content"] or r["ai_summary"] or r["title"],
                url=r["url"],
                source=r["source"],
            ))

        sem = asyncio.Semaphore(MAX_CONCURRENCY)
        updated = 0
        failed = 0

        async with httpx.AsyncClient(timeout=60.0) as client:
            for i in range(0, len(items), BATCH_SIZE):
                batch = items[i:i + BATCH_SIZE]
                batch_ids = [untranslated[i + j]["id"] for j in range(len(batch))]

                async with sem:
                    logger.info("Translating batch %d-%d / %d...", i + 1, i + len(batch), len(items))
                    translations = await _translate_batch_once(batch, client)

                if not translations:
                    logger.warning("Batch %d-%d translation failed (API error or content risk)", i + 1, i + len(batch))
                    failed += len(batch)
                    continue

                # 更新数据库
                for j, si in enumerate(batch):
                    idx1 = j + 1
                    nid = batch_ids[j]
                    if idx1 in translations:
                        t = translations[idx1]
                        new_title = t["chinese_title"] or si.title
                        new_summary = t["summary"] or ""
                        if _contains_cjk(new_title):
                            await session.execute(text("""
                                UPDATE news SET title = :title, ai_summary = :summary
                                WHERE id = :id
                            """), {"title": new_title[:500], "summary": new_summary[:1000], "id": nid})
                            updated += 1
                        else:
                            logger.warning("Translation still not Chinese for [%s] %s", si.source, si.title[:50])
                            failed += 1
                    else:
                        logger.warning("No translation for [%s] %s", si.source, si.title[:50])
                        failed += 1

                await session.commit()
                logger.info("Batch done. Updated: %d, Failed: %d", updated, failed)

        logger.info("═══ Backfill complete: %d translated, %d failed (out of %d) ═══",
                     updated, failed, len(items))


if __name__ == "__main__":
    asyncio.run(main())
