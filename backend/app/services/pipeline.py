"""News Pipeline — orchestrates Fetch → Dedup → Filter → Store.

This is the main entry point called by the scheduler.
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.news import News
from app.services.deepseek_filter import ScoredNewsItem, filter_news
from app.services.rss_fetcher import fetch_all_feeds
from app.utils.deduplicator import NewsDeduplicator

logger = logging.getLogger("alphareader.pipeline")


async def _store_scored_items(items: list[ScoredNewsItem]) -> int:
    """Upsert scored news items into PostgreSQL. Returns count of new rows.

    Per-item error isolation: a single bad item won't prevent others from being stored.
    """
    if not items:
        return 0

    stored = 0
    errors = 0
    async with async_session() as session:
        for item in items:
            try:
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
            except Exception as e:
                errors += 1
                logger.warning("Failed to store item '%s': %s", item.raw.title[:40], e)
                continue

        await session.commit()

    if errors:
        logger.warning("⚠️ %d item(s) failed to store", errors)
    logger.info("Stored %d new scored items to DB", stored)
    return stored


async def run_pipeline() -> dict:
    """Execute the full news pipeline:
    1. Fetch all RSS feeds (with Redis URL dedup)
    2. SimHash + SequenceMatcher dedup (cross-source, 24h window)
    3. Score via DeepSeek (batch of 20)
    4. Store high-scoring items to PostgreSQL

    Each step is wrapped in error handling so partial failures
    are logged but don't crash the entire pipeline run.

    Returns a summary dict for logging / API response.
    """
    logger.info("═══ Pipeline run starting ═══")
    summary: dict = {"fetched": 0, "deduped": 0, "scored": 0, "stored": 0, "errors": []}

    # Step 1: Fetch
    try:
        raw_items = await fetch_all_feeds()
    except Exception as e:
        logger.error("Fatal error in fetch stage: %s", e)
        summary["errors"].append(f"fetch: {e}")
        return summary

    summary["fetched"] = len(raw_items)
    if not raw_items:
        logger.info("No new items fetched, pipeline done.")
        return summary

    # Step 2: SimHash + title similarity dedup
    try:
        dedup = NewsDeduplicator()
        await dedup.load_index()
        unique_items = await dedup.deduplicate(raw_items)
        await dedup.save_index()
    except Exception as e:
        logger.error("Dedup stage failed, using raw items as fallback: %s", e)
        summary["errors"].append(f"dedup: {e}")
        unique_items = raw_items  # graceful degradation

    dedup_dropped = len(raw_items) - len(unique_items)
    summary["deduped"] = dedup_dropped
    logger.info("Dedup: %d → %d items (%d dropped)", len(raw_items), len(unique_items), dedup_dropped)

    if not unique_items:
        logger.info("All items were duplicates, pipeline done.")
        return summary

    # Step 3: Filter via DeepSeek
    try:
        scored_items = await filter_news(unique_items)
    except Exception as e:
        logger.error("DeepSeek filter stage failed: %s", e)
        summary["errors"].append(f"filter: {e}")
        scored_items = []

    summary["scored"] = len(scored_items)

    # Step 4: Store to DB
    try:
        stored_count = await _store_scored_items(scored_items)
    except Exception as e:
        logger.error("Store stage failed: %s", e)
        summary["errors"].append(f"store: {e}")
        stored_count = 0

    summary["stored"] = stored_count

    # Clean up empty errors list for cleaner output
    if not summary["errors"]:
        del summary["errors"]

    logger.info("═══ Pipeline run complete: %s ═══", summary)
    return summary
