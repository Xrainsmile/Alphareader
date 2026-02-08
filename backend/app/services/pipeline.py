"""News Pipeline — orchestrates Fetch → Dedup → Filter → Store.

This is the main entry point called by the scheduler.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.news import News
from app.services.deepseek_filter import ScoredNewsItem, filter_news
from app.services.rss_fetcher import fetch_all_feeds
from app.utils.deduplicator import NewsDeduplicator

logger = logging.getLogger("alphareader.pipeline")


async def _store_scored_items(items: list[ScoredNewsItem]) -> int:
    """Upsert scored news items into PostgreSQL. Returns count of new rows."""
    if not items:
        return 0

    stored = 0
    async with async_session() as session:
        for item in items:
            # For English news with translated title/summary, use Chinese versions
            title = item.chinese_title or item.raw.title
            summary = item.summary  # Already chinese_summary for EN items

            # Merge relevant_tickers into tags if present
            tags = item.tags or item.raw.tags
            if item.relevant_tickers:
                tickers_as_tags = [f"${t}" for t in item.relevant_tickers]
                tags = list(set((tags or []) + tickers_as_tags))

            stmt = (
                pg_insert(News)
                .values(
                    title=title,
                    content=item.raw.content,
                    source=item.raw.source,
                    url=item.raw.url,
                    published_at=item.raw.published_at,
                    ai_score=item.score,
                    ai_summary=summary,
                    tags=tags,
                )
                .on_conflict_do_nothing(index_elements=["url"])
            )
            result = await session.execute(stmt)
            if result.rowcount and result.rowcount > 0:
                stored += 1

        await session.commit()

    logger.info("Stored %d new scored items to DB", stored)
    return stored


async def run_pipeline() -> dict:
    """Execute the full news pipeline:
    1. Fetch all RSS feeds (with Redis URL dedup)
    2. SimHash + SequenceMatcher dedup (cross-source, 24h window)
    3. Score via DeepSeek (batch of 20)
    4. Store high-scoring items to PostgreSQL

    Returns a summary dict for logging / API response.
    """
    logger.info("═══ Pipeline run starting ═══")

    # Step 1: Fetch
    raw_items = await fetch_all_feeds()
    if not raw_items:
        logger.info("No new items fetched, pipeline done.")
        return {"fetched": 0, "deduped": 0, "scored": 0, "stored": 0}

    # Step 2: SimHash + title similarity dedup
    dedup = NewsDeduplicator()
    await dedup.load_index()
    unique_items = await dedup.deduplicate(raw_items)
    await dedup.save_index()

    dedup_dropped = len(raw_items) - len(unique_items)
    logger.info("Dedup: %d → %d items (%d dropped)", len(raw_items), len(unique_items), dedup_dropped)

    if not unique_items:
        logger.info("All items were duplicates, pipeline done.")
        return {"fetched": len(raw_items), "deduped": dedup_dropped, "scored": 0, "stored": 0}

    # Step 3: Filter via DeepSeek
    scored_items = await filter_news(unique_items)

    # Step 4: Store to DB
    stored_count = await _store_scored_items(scored_items)

    summary = {
        "fetched": len(raw_items),
        "deduped": dedup_dropped,
        "scored": len(scored_items),
        "stored": stored_count,
    }
    logger.info("═══ Pipeline run complete: %s ═══", summary)
    return summary
