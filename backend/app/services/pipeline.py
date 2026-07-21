"""管道编排模块 (pipeline.py)
============================
职责：编排整个新闻处理流水线，按顺序执行五个阶段：

  Step 1: 抓取 (Fetch)      — 并发抓取所有信源
  Step 2: 去重 (Dedup)       — 长短文本路由：长文本三层去重 / 短文本智谱 Embedding API 语义去重
  Step 3: AI 评分 (Filter)   — 发送 DeepSeek API 批量评分，过滤 score < 6 的
  Step 4: 存储 (Store)       — Upsert 到 PostgreSQL（ON CONFLICT DO NOTHING）
  Step 5: 标记已处理 (Mark)  — 将成功存储的 URL 标记到 Redis，避免重复抓取

核心设计：
  - 每个阶段独立 try/except，部分失败不崩溃整个 pipeline
  - URL 只在存储成功后才标记为"已见"，防止数据丢失
  - 低分 URL 仅在 filter 全部成功时才标记，有错误时跳过标记以便下次重试
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.database import async_session
from app.models.analytics import PipelineRun
from app.models.news import News
from app.redis import get_redis
from app.services.llm_news_filter import FilterResult, ScoredNewsItem, filter_news
from app.services.rss_fetcher import REDIS_DEDUP_KEY, _normalize_url, fetch_all_feeds
from app.utils.deduplicator import NewsDeduplicator

logger = logging.getLogger("alphareader.pipeline")

# 新闻最大年龄（天）：published_at 超过此天数的文章视为过时，跳过处理
# 防止 RSS 返回全量历史文章（如 OpenAI Blog 一次返回数百篇从2016年至今的文章）
MAX_NEWS_AGE_DAYS = 7


def _contains_cjk(text: str) -> bool:
    """检查文本是否包含 CJK（中日韩）字符"""
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _hash_url(url: str) -> str:
    """将标准化后的 URL 转为 SHA-256 哈希值，用于 Redis 去重"""
    return hashlib.sha256(_normalize_url(url).encode()).hexdigest()


async def _mark_urls_as_seen(urls: list[str]) -> None:
    """将 URL 批量标记到 Redis Set 中，表示"已处理"。

    关键设计：只在 PostgreSQL 存储成功后才调用此函数，
    防止出现"URL 被锁定为已见但数据实际丢失"的 bug。
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


async def _load_historical_fingerprints() -> list[tuple[str, str, int, float]]:
    """P5: 从 DB 加载最近 N 天的 SimHash 指纹，用于注入去重器扩展旧闻识别窗口。

    返回 [(title, source, simhash_value, timestamp_epoch), ...]
    """
    days = getattr(settings, "DEDUP_HISTORICAL_DAYS", 7)
    if not isinstance(days, int) or days < 1:
        days = 7
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        async with async_session() as session:
            from sqlalchemy import select as sa_select
            stmt = (
                sa_select(News.title, News.source, News.simhash_fingerprint, News.published_at)
                .where(News.published_at.isnot(None))
                .where(News.published_at >= cutoff)
                .where(News.simhash_fingerprint.isnot(None))
            )
            result = await session.execute(stmt)
            entries: list[tuple[str, str, int, float]] = []
            for row in result.all():
                ts = row.published_at.timestamp() if row.published_at else 0.0
                entries.append((row.title, row.source, row.simhash_fingerprint, ts))
            logger.info(
                "Loaded %d historical SimHash fingerprints from DB (%d-day window)",
                len(entries), days,
            )
            return entries
    except Exception as e:
        logger.warning("Failed to load historical fingerprints: %s", e)
        return []


async def _store_scored_items(items: list[ScoredNewsItem]) -> tuple[int, list[str]]:
    """将评分通过的新闻条目存入 PostgreSQL。

    返回 (新增行数, 成功存储的 URL 列表)。

    关键机制：
    - 使用 INSERT ... ON CONFLICT (url) DO NOTHING 防止重复插入
    - 每条记录使用独立的 Savepoint（session.begin_nested()），
      单条失败不会回滚整个事务
    - 英文新闻使用翻译后的中文标题/摘要存入 title 和 ai_summary 字段
    - relevant_tickers 合并为 $TICKER 格式加入 tags 数组
    - 事件聚合：将 related_to_url 转换为 related_to_id（查库获取已存在的新闻 ID）
    """
    if not items:
        return 0, []

    # ── 预查询：批量将 related_to_url 转换为 related_to_id ──
    related_urls = {
        item.raw.related_to_url
        for item in items
        if getattr(item.raw, "related_to_url", None)
    }
    url_to_id: dict[str, str] = {}
    if related_urls:
        try:
            async with async_session() as lookup_session:
                from sqlalchemy import select as sa_select
                stmt = sa_select(News.id, News.url).where(News.url.in_(related_urls))
                result = await lookup_session.execute(stmt)
                for row in result.all():
                    url_to_id[row.url] = row.id
            logger.info(
                "Event-cluster URL→ID lookup: %d URLs queried, %d found",
                len(related_urls), len(url_to_id),
            )
        except Exception as e:
            logger.warning("Failed to lookup related_to URLs: %s", e)

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
                    # Log untranslated English titles for debugging
                    if not item.chinese_title and item.raw.title and not _contains_cjk(item.raw.title):
                        logger.warning(
                            "⚠️ English news stored without translation: '%s' [%s]",
                            item.raw.title[:50], item.raw.source,
                        )
                    # Already chinese_summary for EN items; fallback to
                    # truncated content for CN items where DeepSeek omits summary
                    summary = item.summary or (item.raw.content or "")[:100]

                    # Merge relevant_tickers into tags if present
                    tags = item.tags or item.raw.tags
                    if item.relevant_tickers:
                        tickers_as_tags = [f"${t}" for t in item.relevant_tickers]
                        tags = list(set((tags or []) + tickers_as_tags))

                    # 去除与 source 同名的 tag（LLM 有时会把来源名当标签返回，
                    # 而 meta 行已显示 source，tag 中重复无信息增量）
                    src_name = (item.raw.source or "").strip()
                    if src_name and tags:
                        tags = [t for t in tags if t != src_name]

                    # 事件聚合：related_to_url → related_to_id
                    related_to_id = None
                    raw_related_url = getattr(item.raw, "related_to_url", None)
                    if raw_related_url:
                        related_to_id = url_to_id.get(raw_related_url)

                    # P5: 计算去重指纹并持久化
                    from app.utils.deduplicator import NewsDeduplicator
                    import hashlib as _hashlib
                    dedup_text = NewsDeduplicator._build_text(title, item.raw.content or "")
                    sh = NewsDeduplicator._compute_simhash(dedup_text)
                    content_hash = _hashlib.sha256(
                        (title + (item.raw.content or "")[:500]).encode("utf-8", errors="ignore")
                    ).hexdigest()

                    values = dict(
                        title=title,
                        content=item.raw.content,
                        source=item.raw.source,
                        category=getattr(item.raw, "category", "财经"),
                        url=_normalize_url(item.raw.url),
                        published_at=item.raw.published_at,
                        ai_score=item.score,
                        ai_summary=summary,
                        why_it_matters=item.why_it_matters or None,
                        is_highlight=bool(getattr(item, "is_highlight", False)),
                        tags=tags,
                        content_hash=content_hash,
                        # Simhash.value 是无符号 64 位整数，PostgreSQL BIGINT 是有符号
                        # 超过 2^63 的值需转换为负数，否则报 "value out of int64 range"
                        simhash_fingerprint=sh.value if sh.value < 2**63 else sh.value - 2**64,
                    )
                    if related_to_id is not None:
                        values["related_to_id"] = related_to_id
                    if item.sentiment_score is not None:
                        values["sentiment_score"] = item.sentiment_score
                        values["surprise_factor"] = item.surprise_factor
                        values["catalyst_type"] = item.catalyst_type
                        values["sentiment_entity"] = item.sentiment_entity
                        values["sentiment_reasoning"] = item.sentiment_reasoning

                    stmt = (
                        pg_insert(News)
                        .values(**values)
                        .on_conflict_do_nothing(index_elements=["url"])
                    )
                    result = await session.execute(stmt)
                    if result.rowcount and result.rowcount > 0:
                        stored += 1
                        stored_urls.append(item.raw.url)
                        if related_to_id:
                            logger.debug(
                                "Stored (event-cluster → %s): %s",
                                related_to_id, item.raw.title[:60],
                            )
                        else:
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
    """执行完整的新闻处理 Pipeline（由定时调度器调用的主入口）。

    五个阶段：
    1. Fetch  — 并发抓取所有信源（含 Redis URL 去重）
    2. Dedup  — 长短文本路由去重（长文本三层 + 短文本智谱 Embedding API，24h/30min 窗口）
    3. Filter — DeepSeek 批量评分（每批 20 条），丢弃 score < 阈值的
    4. Store  — 高分条目 Upsert 到 PostgreSQL
    5. Mark   — 成功存储的 URL 标记到 Redis 防止下次重复抓取

    每个阶段都有独立的错误处理，部分失败会记录日志但不中断整个流程。
    返回摘要 dict 用于日志和 API 响应。
    """
    logger.info("═══ Pipeline run starting ═══")
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    summary: dict = {"fetched": 0, "deduped": 0, "scored": 0, "stored": 0, "errors": []}
    by_source: dict[str, dict] = {}
    score_distribution: dict[str, int] = {}

    # Step 1: Fetch
    try:
        fetch_result = await fetch_all_feeds()
        raw_items = fetch_result.items
        by_source = {name: {"fetched": cnt, "passed": 0} for name, cnt in fetch_result.by_source.items()}
    except Exception as e:
        logger.error("Fatal error in fetch stage: %s", e)
        summary["errors"].append(f"fetch: {e}")
        await _save_pipeline_run(started_at, t0, summary, by_source, score_distribution)
        return summary

    summary["fetched"] = len(raw_items)
    if not raw_items:
        logger.info("No new items fetched, pipeline done.")
        await _save_pipeline_run(started_at, t0, summary, by_source, score_distribution)
        return summary

    # Step 1.5: 过滤掉过于陈旧的新闻
    # 某些 RSS 源（如 OpenAI Blog）会返回全量历史文章，需要剔除
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=MAX_NEWS_AGE_DAYS)
    fresh_items: list = []
    stale_count = 0
    for item in raw_items:
        if item.published_at and item.published_at < cutoff_dt:
            stale_count += 1
            continue
        fresh_items.append(item)
    if stale_count:
        logger.info(
            "Stale-filter: dropped %d items with published_at > %d days old (cutoff=%s)",
            stale_count, MAX_NEWS_AGE_DAYS, cutoff_dt.isoformat(),
        )
    raw_items = fresh_items

    if not raw_items:
        logger.info("All items were stale, pipeline done.")
        await _save_pipeline_run(started_at, t0, summary, by_source, score_distribution)
        return summary

    # Step 2: SimHash + title similarity + TF-IDF semantic dedup
    try:
        dedup = NewsDeduplicator()
        await dedup.load_index()
        # P5: 注入 DB 历史指纹，扩展旧闻识别窗口到 7 天
        historical = await _load_historical_fingerprints()
        if historical:
            dedup.preload_historical(historical)
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
        await _save_pipeline_run(started_at, t0, summary, by_source, score_distribution)
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

    # Step 3.1: 过滤 AI 标记为"无效噪音"的边界分文章
    # 当 LLM 标记了"无效噪音"标签但分数刚好过阈值（如5分），说明 LLM 认为内容
    # 质量极低但数值上给了"同情分"。这类文章应该被丢弃。
    noise_tag = "无效噪音"
    noise_filtered = []
    noise_count = 0
    for si in scored_items:
        if noise_tag in si.tags and si.score <= settings.LLM_SCORE_THRESHOLD:
            noise_count += 1
            logger.debug(
                "Noise filter: drop '%s' (score=%d, tags=%s)",
                si.raw.title[:50], si.score, si.tags,
            )
            continue
        noise_filtered.append(si)
    if noise_count:
        logger.info("Noise filter: dropped %d items tagged '%s' with score <= %d",
                     noise_count, noise_tag, settings.LLM_SCORE_THRESHOLD)
    scored_items = noise_filtered

    # 收集评分分布 & 各信源通过数
    score_counter: Counter[int] = Counter()
    source_pass_counter: Counter[str] = Counter()
    for si in scored_items:
        score_counter[si.score] += 1
        source_pass_counter[si.raw.source] += 1
    score_distribution = {str(k): v for k, v in sorted(score_counter.items())}
    for src_name in by_source:
        by_source[src_name]["passed"] = source_pass_counter.get(src_name, 0)

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
    # by DeepSeek (score < threshold). These are legitimately processed and should not
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

    # Step 6: 持久化运行记录到 pipeline_runs 表
    await _save_pipeline_run(started_at, t0, summary, by_source, score_distribution)

    return summary


async def _save_pipeline_run(
    started_at: datetime,
    t0: float,
    summary: dict,
    by_source: dict,
    score_distribution: dict,
) -> None:
    """将本次 Pipeline 运行结果写入 pipeline_runs 表。"""
    duration = round(time.monotonic() - t0, 2)
    try:
        async with async_session() as session:
            run = PipelineRun(
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                duration_sec=duration,
                total_fetched=summary.get("fetched", 0),
                after_dedup=summary.get("deduped", 0),
                after_score=summary.get("scored", 0),
                stored=summary.get("stored", 0),
                by_source=by_source,
                score_distribution=score_distribution,
                errors=summary.get("errors", []),
            )
            session.add(run)
            await session.commit()
            logger.info("Pipeline run record saved (%.1fs)", duration)
    except Exception as e:
        logger.warning("Failed to save pipeline run record: %s", e)
