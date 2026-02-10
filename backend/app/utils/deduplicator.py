"""NewsDeduplicator — Two-layer dedup before LLM scoring.

Layer 1: SimHash fingerprint + Hamming distance (≤3 = duplicate)
Layer 2: SequenceMatcher title similarity (>0.6 = duplicate)

Uses Redis for persistent 24h SimHash index. Zero API cost, millisecond latency.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

import jieba
from simhash import Simhash

from app.redis import get_redis

logger = logging.getLogger("alphareader.dedup")

# ── Config ──
SIMHASH_HAMMING_THRESHOLD = 3       # Hamming distance ≤ 3 → duplicate
SEQMATCH_RATIO_THRESHOLD = 0.6      # SequenceMatcher ratio > 0.6 → duplicate
INDEX_TTL_SECONDS = 24 * 3600       # 24-hour sliding window
REDIS_SIMHASH_KEY = "alphareader:simhash_index"

# 源优先级：数值越小越优先保留
SOURCE_PRIORITY = {
    "财联社": 1,
    "华尔街见闻": 2,
    "第一财经": 3,
    "Reuters": 4,
    "MarketWatch": 4,
    "CNBC": 5,
    "Seeking Alpha": 6,
    "TechCrunch": 7,
    "新浪财经": 8,
    "同花顺": 9,
    "东方财富": 10,
    "东方财富快讯": 11,
}

# 标题清洗：去掉标点、括号标记
_BRACKET_RE = re.compile(r"[【\[][^\]】]*[】\]]")
_PUNCT_RE = re.compile(
    r"[，。！？、；：\u201c\u201d\u2018\u2019（）\s.,!?;:\"'()\-\u3000]"
)


@dataclass
class _IndexEntry:
    """One entry in the SimHash index."""
    simhash_value: int
    title: str
    source: str
    timestamp: float


class NewsDeduplicator:
    """Two-layer news deduplicator with Redis-backed 24h SimHash index.

    Usage:
        dedup = NewsDeduplicator()
        await dedup.load_index()          # Load existing index from Redis
        unique = await dedup.deduplicate(items)  # Filter duplicates
        await dedup.save_index()          # Persist updated index to Redis
    """

    def __init__(self) -> None:
        self._index: list[_IndexEntry] = []

    # ────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────

    async def load_index(self) -> None:
        """Load SimHash index from Redis. Prune entries older than 24h."""
        r = get_redis()
        raw_entries = await r.hgetall(REDIS_SIMHASH_KEY)
        cutoff = time.time() - INDEX_TTL_SECONDS
        self._index = []

        for key, value in raw_entries.items():
            try:
                # value format: "simhash_int|source|timestamp"
                parts = value.decode() if isinstance(value, bytes) else value
                sh_str, source, ts_str = parts.rsplit("|", 2)
                ts = float(ts_str)
                if ts < cutoff:
                    continue  # Expired, skip
                title = key.decode() if isinstance(key, bytes) else key
                self._index.append(_IndexEntry(
                    simhash_value=int(sh_str),
                    title=title,
                    source=source,
                    timestamp=ts,
                ))
            except (ValueError, AttributeError) as e:
                logger.debug("Skipping malformed index entry: %s", e)

        logger.info("Loaded SimHash index: %d entries (24h window)", len(self._index))

    async def save_index(self) -> None:
        """Persist the current index back to Redis. Prune expired entries."""
        r = get_redis()
        cutoff = time.time() - INDEX_TTL_SECONDS

        # Delete old key, rewrite
        await r.delete(REDIS_SIMHASH_KEY)

        if not self._index:
            return

        pipe = r.pipeline()
        count = 0
        for entry in self._index:
            if entry.timestamp < cutoff:
                continue
            value = f"{entry.simhash_value}|{entry.source}|{entry.timestamp}"
            pipe.hset(REDIS_SIMHASH_KEY, entry.title, value)
            count += 1
        pipe.expire(REDIS_SIMHASH_KEY, INDEX_TTL_SECONDS + 3600)  # Extra 1h buffer
        await pipe.execute()

        logger.info("Saved SimHash index: %d entries", count)

    async def deduplicate(self, items: list) -> list:
        """Run two-layer dedup on a list of RawNewsItem.

        Returns only unique items. Adds unique items to the index.
        """
        if not items:
            return []

        # Sort by source priority so higher-priority sources are processed first
        items_sorted = sorted(
            items,
            key=lambda x: SOURCE_PRIORITY.get(x.source, 99),
        )

        unique: list = []
        total_dropped = 0

        for item in items_sorted:
            text = self._build_text(item.title, getattr(item, "content", ""))
            sh = self._compute_simhash(text)
            clean_title = self._clean(item.title)

            # Check against existing index
            dup_entry = self._find_duplicate(sh, clean_title)

            if dup_entry is not None:
                total_dropped += 1
                logger.info(
                    'Duplicate found: [%s]"%s" is similar to [%s]"%s", distance=%d',
                    item.source,
                    item.title[:40],
                    dup_entry.source,
                    dup_entry.title[:40],
                    self._hamming(sh.value, dup_entry.simhash_value),
                )
                continue

            # Not a duplicate — add to index and keep
            self._index.append(_IndexEntry(
                simhash_value=sh.value,
                title=item.title,
                source=item.source,
                timestamp=time.time(),
            ))
            unique.append(item)

        logger.info(
            "Dedup result: %d in → %d unique, %d duplicates dropped",
            len(items), len(unique), total_dropped,
        )
        return unique

    # ────────────────────────────────────────────
    # Internal methods
    # ────────────────────────────────────────────

    def _find_duplicate(self, sh: Simhash, clean_title: str) -> _IndexEntry | None:
        """Check if a news item is duplicate against the index.

        Layer 1: SimHash Hamming distance ≤ 3
        Layer 2: SequenceMatcher ratio > 0.6 (fallback for title-only similarity)
        """
        for entry in self._index:
            # Layer 1: SimHash
            dist = self._hamming(sh.value, entry.simhash_value)
            if dist <= SIMHASH_HAMMING_THRESHOLD:
                return entry

            # Layer 2: Title similarity (only if SimHash is close-ish, ≤10)
            # Skip full SequenceMatcher for clearly different texts
            if dist <= 10:
                existing_clean = self._clean(entry.title)
                if clean_title and existing_clean:
                    # Fast check: substring containment
                    if clean_title in existing_clean or existing_clean in clean_title:
                        return entry
                    ratio = SequenceMatcher(None, clean_title, existing_clean).ratio()
                    if ratio > SEQMATCH_RATIO_THRESHOLD:
                        return entry

        return None

    @staticmethod
    def _build_text(title: str, content: str) -> str:
        """Combine title + content for SimHash computation. Title is weighted 3x."""
        # Title is more important, repeat it to boost weight
        parts = [title] * 3
        if content and content != title:
            # Take first 200 chars of content to keep it fast
            parts.append(content[:200])
        return " ".join(parts)

    @staticmethod
    def _compute_simhash(text: str) -> Simhash:
        """Compute 64-bit SimHash using jieba word segmentation."""
        words = list(jieba.cut(text))
        # Filter out single-char words and punctuation
        words = [w for w in words if len(w.strip()) > 1]
        return Simhash(words)

    @staticmethod
    def _hamming(a: int, b: int) -> int:
        """Compute Hamming distance between two 64-bit integers."""
        x = a ^ b
        count = 0
        while x:
            count += 1
            x &= x - 1
        return count

    @staticmethod
    def _clean(title: str) -> str:
        """Strip brackets, punctuation, whitespace for title comparison."""
        t = _BRACKET_RE.sub("", title)
        t = _PUNCT_RE.sub("", t)
        return t
