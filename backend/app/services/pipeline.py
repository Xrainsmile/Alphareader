"""News Pipeline — orchestrates Fetch → Dedup → Filter → Store.

This is the main entry point called by the scheduler.
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.news import News
from app.redis import get_redis
from app.services.deepseek_filter import FilterResult, ScoredNewsItem, filter_news
from app.services.rss_fetcher import REDIS_DEDUP_KEY, fetch_all_feeds
from app.utils.deduplicator import NewsDeduplicator

logger = logging.getLogger("alphareader.pipeline")


def _hash_url(url: str) -> str:
    """SHA-256 hash of URL for Redis dedup set."""
    return hashlib.sha256(url.encode()).hexdigest()


async def _mark_urls_as_seen(urls: list[str]) -> None:
    """Mark successfully stored URLs in Redis seen_urls set.

    Only called AFTER items are confirmed stored in PostgreSQL.
    """
    if not urls:
        return

    r = get_redis()
    hashes = [_hash_url(u) for u in urls]
    try:
        added = await r.sadd(REDIS_DEDUP_KEY, *hashes)
        logger.info("Marked %d URL(s) as seen in Redis (SADD returned %d)", len(hashes), added)
    except Exception as e:
        logger.error("Failed to mark URLs as seen in Redis: %s", e)


async def _store_scored_items(items: list[ScoredNewsItem]) -> tuple[int, list[str]]:
    """Upsert scored news items into PostgreSQL.

    Returns (count_of_new_rows, list_of_successfully_stored_urls).
    Per-item error isolation: a single bad item won't prevent others from being stored.
    """
    if not items:
        return 0, []

    stored = 0
    errors = 0
    stored_urls: list[str] = []
    async with async_session() as session:
        for item in items:
            try:
                # Use a savepoint so a single bad item doesn't roll back
                # the entire transaction — other items remain committed.
                async with session.begin_nested():
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
                        stored_urls.append(item.raw.url)
                        logger.debug("Stored: %s", item.raw.title[:60])
                    else:
                        # ON CONFLICT DO NOTHING — URL already in DB, still mark as seen
                        stored_urls.append(item.raw.url)
            except Exception as e:
                errors += 1
                logger.warning("Failed to store item '%s': %s", item.raw.title[:40], e)
                # Savepoint auto-rolled back; outer transaction still alive.
                # Do NOT add this URL to stored_urls — it will be retried next run.
                continue

        # Commit all successful savepoints in one shot
        await session.commit()

    if errors:
        logger.warning("⚠️ %d item(s) failed to store", errors)
    logger.info("Stored %d new scored items to DB (%d total processed)", stored, len(stored_urls))
    return stored, stored_urls


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
    filter_result: FilterResult | None = None
    try:
        filter_result = await filter_news(unique_items)
        scored_items = filter_result.scored
    except Exception as e:
        logger.error("DeepSeek filter stage failed: %s", e)
        summary["errors"].append(f"filter: {e}")
        scored_items = []

    summary["scored"] = len(scored_items)

    # Step 4: Store to DB
    try:
        stored_count, stored_urls = await _store_scored_items(scored_items)
    except Exception as e:
        logger.error("Store stage failed: %s", e)
        summary["errors"].append(f"store: {e}")
        stored_count = 0
        stored_urls = []

    summary["stored"] = stored_count

    # Step 5: Mark successfully stored URLs as seen in Redis
    # This is CRITICAL — only mark URLs AFTER content is persisted to DB.
    # Prevents the bug where URLs are locked as "seen" but data is lost.
    if stored_urls:
        await _mark_urls_as_seen(stored_urls)

    # Also mark URLs that passed through the entire pipeline but were filtered
    # by DeepSeek (score < 6). These are legitimately processed and should not
    # be re-fetched.
    #
    # SAFETY: Only do this when ALL batches succeeded. If any batch had errors,
    # we can't tell which URLs failed vs. which were legitimately low-score.
    # In that case, skip marking — those URLs will be retried next run.
    filter_fully_succeeded = (
        filter_result is not None
        and not filter_result.had_errors
        and "filter" not in " ".join(summary.get("errors", []))
    )
    if filter_fully_succeeded:
        try:
            scored_url_set = {item.raw.url for item in scored_items}
            filtered_out_urls = [
                item.url for item in unique_items
                if item.url not in scored_url_set
                and item.url not in (stored_urls or [])
            ]
            if filtered_out_urls:
                await _mark_urls_as_seen(filtered_out_urls)
                logger.info("Marked %d low-score/filtered URLs as seen", len(filtered_out_urls))
        except Exception as e:
            logger.warning("Failed to mark filtered URLs as seen: %s", e)
    elif unique_items and not filter_fully_succeeded:
        skipped_info = ""
        if filter_result and filter_result.had_errors:
            skipped_info = (
                f" ({filter_result.skipped_batches}/{filter_result.total_batches} batches failed)"
            )
        logger.warning(
            "Skipping URL marking for %d items — DeepSeek filter had errors%s",
            len(unique_items), skipped_info,
        )

    # Clean up empty errors list for cleaner output
    if not summary["errors"]:
        del summary["errors"]

    logger.info("═══ Pipeline run complete: %s ═══", summary)
    return summary
