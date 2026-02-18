"""新闻去重引擎 — 在 LLM 评分之前执行三层去重，零 API 成本、毫秒级延迟。

三层去重策略：
  第一层：SimHash 指纹 + 汉明距离（≤5 视为重复）
         —— 利用 64-bit 局部敏感哈希，对标题×3+正文前200字做指纹，
            位运算比较，O(n) 扫描现有索引。
  第二层：SequenceMatcher 标题相似度（>0.5 视为重复）
         —— 对汉明距离 6~12 的"可疑近似"条目，进一步做字符级对比，
            同时包含子串包含检测。
  第三层：TF-IDF 余弦相似度（>0.65 视为重复）
         —— 对通过前两层的幸存条目做批量 TF-IDF 向量化（jieba 分词），
            计算余弦相似度矩阵，贪心去重保留高优先级源。

存储方案：
  - Redis Hash 持久化 24 小时 SimHash 索引
  - 写入采用"先写临时 key → 原子 RENAME"策略，避免并发读取时索引为空
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

import jieba
from simhash import Simhash
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.redis import get_redis

logger = logging.getLogger("alphareader.dedup")

# ── 去重阈值配置 ──
SIMHASH_HAMMING_THRESHOLD = 5       # 第一层：汉明距离 ≤ 5 判定为重复（从3放宽到5）
SEQMATCH_RATIO_THRESHOLD = 0.5      # 第二层：SequenceMatcher 比值 > 0.5 判定为重复（从0.6放宽到0.5）
TFIDF_COSINE_THRESHOLD = 0.65       # 第三层：TF-IDF 余弦相似度 > 0.65 判定为重复
INDEX_TTL_SECONDS = 24 * 3600       # 索引滑动窗口：24 小时
REDIS_SIMHASH_KEY = "alphareader:simhash_index"  # Redis Hash 键名

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

# 标题清洗正则：去掉【】[]括号标记及其内容、去掉中英文标点和空白
_BRACKET_RE = re.compile(r"[【\[][^\]】]*[】\]]")
_PUNCT_RE = re.compile(
    r"[，。！？、；：\u201c\u201d\u2018\u2019（）\s.,!?;:\"'()\-\u3000]"
)


@dataclass
class _IndexEntry:
    """SimHash 索引中的单条记录。

    存储在 Redis Hash 中，key=title, value="simhash_int|source|timestamp"。
    """
    simhash_value: int   # 64-bit SimHash 指纹值
    title: str           # 新闻标题（同时作为 Redis Hash 的 field）
    source: str          # 来源名称（如"财联社"、"Reuters"）
    timestamp: float     # 入库时间戳（用于 24 小时过期淘汰）


class NewsDeduplicator:
    """三层新闻去重器，使用 Redis 持久化 24 小时 SimHash 索引。

    三层检测（由快到慢）：
      第一层：SimHash 汉明距离（位运算，最快）
      第二层：SequenceMatcher 标题相似度（字符级）
      第三层：TF-IDF 余弦相似度（词项级语义）

    使用方式：
        dedup = NewsDeduplicator()
        await dedup.load_index()                # 从 Redis 加载现有索引
        unique = await dedup.deduplicate(items)  # 过滤重复，返回唯一条目
        await dedup.save_index()                # 将更新后的索引持久化回 Redis
    """

    def __init__(self) -> None:
        self._index: list[_IndexEntry] = []

    # ────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────

    async def load_index(self) -> None:
        """从 Redis 加载 SimHash 索引，并淘汰超过 24 小时的过期条目。"""
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
        """将当前索引持久化回 Redis，使用原子 RENAME 策略。

        先写入临时 key（:tmp），写完后通过 RENAME 原子性地替换正式 key。
        这样可以避免"先 DEL 再 HSET"导致的空窗期（并发读取会漏判重复）。
        """
        r = get_redis()
        cutoff = time.time() - INDEX_TTL_SECONDS
        tmp_key = f"{REDIS_SIMHASH_KEY}:tmp"

        # Clean up any stale temp key from a previous crash
        await r.delete(tmp_key)

        if not self._index:
            # No entries — just delete the real key
            await r.delete(REDIS_SIMHASH_KEY)
            logger.info("Saved SimHash index: 0 entries (cleared)")
            return

        # Write all valid entries to the temp key via pipeline
        pipe = r.pipeline()
        count = 0
        for entry in self._index:
            if entry.timestamp < cutoff:
                continue
            value = f"{entry.simhash_value}|{entry.source}|{entry.timestamp}"
            pipe.hset(tmp_key, entry.title, value)
            count += 1

        if count == 0:
            # All entries expired — delete both keys
            pipe.delete(tmp_key)
            pipe.delete(REDIS_SIMHASH_KEY)
            await pipe.execute()
            logger.info("Saved SimHash index: 0 entries (all expired)")
            return

        pipe.expire(tmp_key, INDEX_TTL_SECONDS + 3600)  # Extra 1h buffer
        await pipe.execute()

        # Atomic swap: readers either see the old full key or the new full key
        await r.rename(tmp_key, REDIS_SIMHASH_KEY)

        logger.info("Saved SimHash index: %d entries (atomic RENAME)", count)

    async def deduplicate(self, items: list) -> list:
        """对 RawNewsItem 列表执行三层去重。

        第一层+第二层：逐条与 24 小时索引比对（SimHash + SequenceMatcher）。
        第三层：对幸存条目做批量 TF-IDF 余弦相似度检测。

        返回去重后的唯一条目列表，同时将新的唯一条目加入索引。
        """
        if not items:
            return []

        # Sort by source priority so higher-priority sources are processed first
        items_sorted = sorted(
            items,
            key=lambda x: SOURCE_PRIORITY.get(x.source, 99),
        )

        # ── Layer 1 + 2: SimHash + SequenceMatcher (against index) ──
        survivors: list = []
        l12_dropped = 0

        for item in items_sorted:
            text = self._build_text(item.title, getattr(item, "content", ""))
            sh = self._compute_simhash(text)
            clean_title = self._clean(item.title)

            dup_entry = self._find_duplicate(sh, clean_title)

            if dup_entry is not None:
                l12_dropped += 1
                logger.info(
                    'L1/L2 dup: [%s]"%s" ≈ [%s]"%s"',
                    item.source,
                    item.title[:40],
                    dup_entry.source,
                    dup_entry.title[:40],
                )
                continue

            # Passed L1+L2, add to index
            self._index.append(_IndexEntry(
                simhash_value=sh.value,
                title=item.title,
                source=item.source,
                timestamp=time.time(),
            ))
            survivors.append(item)

        # ── Layer 3: TF-IDF cosine similarity (among current batch survivors) ──
        l3_dropped = 0
        if len(survivors) >= 2:
            unique, l3_dropped = self._tfidf_dedup(survivors)
        else:
            unique = survivors

        total_dropped = l12_dropped + l3_dropped
        logger.info(
            "Dedup result: %d in → %d unique (%d dropped: L1/L2=%d, L3_tfidf=%d)",
            len(items), len(unique), total_dropped, l12_dropped, l3_dropped,
        )
        return unique

    # ────────────────────────────────────────────
    # Internal methods
    # ────────────────────────────────────────────

    def _find_duplicate(self, sh: Simhash, clean_title: str) -> _IndexEntry | None:
        """在索引中查找是否存在重复条目。

        第一层：汉明距离 ≤ 5 → 直接判定重复
        第二层：汉明距离 6~12 时，用 SequenceMatcher 做标题相似度兜底（> 0.5 判定重复）
               同时包含子串包含检测（如"A股大涨"包含于"A股大涨创新高"）
        """
        for entry in self._index:
            # Layer 1: SimHash
            dist = self._hamming(sh.value, entry.simhash_value)
            if dist <= SIMHASH_HAMMING_THRESHOLD:
                return entry

            # Layer 2: Title similarity (only if SimHash is close-ish, ≤12)
            # Skip full SequenceMatcher for clearly different texts
            if dist <= 12:
                existing_clean = self._clean(entry.title)
                if clean_title and existing_clean:
                    # Fast check: substring containment
                    if clean_title in existing_clean or existing_clean in clean_title:
                        return entry
                    ratio = SequenceMatcher(None, clean_title, existing_clean).ratio()
                    if ratio > SEQMATCH_RATIO_THRESHOLD:
                        return entry

        return None

    def _tfidf_dedup(self, items: list) -> tuple[list, int]:
        """第三层：对当前批次幸存条目做 TF-IDF 余弦相似度去重。

        构建方式：标题×3 + 正文前200字 → jieba 分词 → TF-IDF 向量化 → 余弦相似度矩阵。
        条目已按来源优先级排序（靠前 = 优先级高），贪心策略保留先出现的条目，
        当两条目余弦相似度 > 0.65 时，淘汰后出现（低优先级）的那条。

        返回 (去重后列表, 被淘汰数量)。
        """
        # Build texts for TF-IDF
        texts = []
        for item in items:
            text = self._build_text(item.title, getattr(item, "content", ""))
            # Tokenize with jieba for better Chinese handling
            tokens = " ".join(w for w in jieba.cut(text) if len(w.strip()) > 1)
            texts.append(tokens)

        try:
            vectorizer = TfidfVectorizer(max_features=5000)
            tfidf_matrix = vectorizer.fit_transform(texts)
            sim_matrix = cosine_similarity(tfidf_matrix)
        except Exception as e:
            logger.warning("TF-IDF dedup failed, skipping Layer 3: %s", e)
            return items, 0

        # Greedy dedup: keep earlier (higher priority) items
        n = len(items)
        is_dup = [False] * n

        for i in range(n):
            if is_dup[i]:
                continue
            for j in range(i + 1, n):
                if is_dup[j]:
                    continue
                if sim_matrix[i][j] > TFIDF_COSINE_THRESHOLD:
                    is_dup[j] = True
                    logger.info(
                        'L3 TF-IDF dup: [%s]"%s" ≈ [%s]"%s" (cos=%.3f)',
                        items[j].source,
                        items[j].title[:40],
                        items[i].source,
                        items[i].title[:40],
                        sim_matrix[i][j],
                    )

        unique = [item for item, dup in zip(items, is_dup) if not dup]
        dropped = sum(is_dup)
        return unique, dropped

    @staticmethod
    def _build_text(title: str, content: str) -> str:
        """拼接标题+正文用于 SimHash / TF-IDF 计算。标题重复3次以加权。"""
        # Title is more important, repeat it to boost weight
        parts = [title] * 3
        if content and content != title:
            # Take first 200 chars of content to keep it fast
            parts.append(content[:200])
        return " ".join(parts)

    @staticmethod
    def _compute_simhash(text: str) -> Simhash:
        """使用 jieba 分词计算 64-bit SimHash 指纹。"""
        words = list(jieba.cut(text))
        # Filter out single-char words and punctuation
        words = [w for w in words if len(w.strip()) > 1]
        return Simhash(words)

    @staticmethod
    def _hamming(a: int, b: int) -> int:
        """计算两个 64-bit 整数之间的汉明距离（异或后数 1 的个数）。"""
        x = a ^ b
        count = 0
        while x:
            count += 1
            x &= x - 1
        return count

    @staticmethod
    def _clean(title: str) -> str:
        """清洗标题：去除方括号标记、标点符号、空白字符，用于标题相似度比较。"""
        t = _BRACKET_RE.sub("", title)
        t = _PUNCT_RE.sub("", t)
        return t
