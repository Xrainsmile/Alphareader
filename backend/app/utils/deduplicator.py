"""新闻去重引擎 — 在 LLM 评分之前执行多层去重，零 API 成本、毫秒级延迟。

架构概览：长短文本路由（Length-based Routing）
═══════════════════════════════════════════════
进入去重前，先根据"清洗后标题+正文"长度做路由：

  【长文本通道】长度 > 150 字 → 原有三层去重
    第一层：SimHash 指纹 + 汉明距离（≤5 视为重复）
    第二层：SequenceMatcher 标题相似度（>0.5 视为重复）
    第三层：TF-IDF 余弦相似度（>0.65 视为重复）

  【短文本语义通道】长度 ≤ 150 字（金融快讯等）
    基于 Sentence Embedding（BAAI/bge-small-zh-v1.5）计算向量余弦相似度，
    仅与过去 30 分钟内的短文本向量对比。
    - 余弦相似度 > 0.88 → 判定重复
    - 余弦相似度 0.80~0.88（灰色地带）→ 数值抗误杀检测：
      提取核心数值实体，若数值集合不同 → 保留（同一事件的不同指标），
      否则判定重复。
    降级策略：若 Embedding 模型加载失败，回退到 SequenceMatcher 标题相似度。

存储方案：
  - Redis Hash 持久化 24 小时 SimHash 索引
  - Redis Hash 持久化 30 分钟短文本 Embedding 索引
  - 写入均采用"先写临时 key → 原子 RENAME"策略
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

import jieba
import numpy as np
from simhash import Simhash
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.redis import get_redis

logger = logging.getLogger("alphareader.dedup")

# ══════════════════════════════════════════════
# 全局阈值配置（可通过环境变量覆盖）
# ══════════════════════════════════════════════

# 长短文本路由分界点（清洗后字符数）
SHORT_TEXT_THRESHOLD = 150

# ── 长文本通道阈值 ──
SIMHASH_HAMMING_THRESHOLD = 5       # 第一层：汉明距离 ≤ 5 判定为重复
SEQMATCH_RATIO_THRESHOLD = 0.5      # 第二层：SequenceMatcher 比值 > 0.5 判定为重复
TFIDF_COSINE_THRESHOLD = 0.65       # 第三层：TF-IDF 余弦相似度 > 0.65 判定为重复

# ── 短文本语义通道阈值 ──
EMBEDDING_COSINE_THRESHOLD = 0.88   # 语义相似度 > 0.88 → 直接判重
EMBEDDING_GRAY_ZONE_LOW = 0.80      # 灰色地带下界：0.80~0.88 之间触发数值抗误杀
SHORT_TEXT_TTL_SECONDS = 30 * 60    # 短文本向量对比窗口：30 分钟

# ── 公共配置 ──
INDEX_TTL_SECONDS = 24 * 3600       # SimHash 索引滑动窗口：24 小时
REDIS_SIMHASH_KEY = "alphareader:simhash_index"
REDIS_EMBEDDING_KEY = "alphareader:embedding_index"

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

# 金融数值提取正则：匹配 "140.4万户"、"6.2%"、"1.1%" 等核心数值
_NUMBER_RE = re.compile(
    r"(?<![a-zA-Z])"                      # 前面不是字母（排除 "v1.5" 等）
    r"(\d+(?:\.\d+)?)"                    # 数值主体：整数或小数
    r"(%|万[户亿元]?|亿[元]?|元|美元|"    # 单位：百分比、中文计量单位
    r"个百分点|基点|bp|bps)?"             # 金融专用单位
    r"(?![a-zA-Z\d])",                    # 后面不是字母或数字
    re.IGNORECASE,
)


# ══════════════════════════════════════════════
# Sentence Embedding 单例管理
# ══════════════════════════════════════════════

class _EmbeddingModel:
    """Sentence Embedding 单例封装。

    冷启动时加载 BAAI/bge-small-zh-v1.5（~90MB），后续复用。
    如果加载失败（无 GPU、内存不足、缺依赖等），优雅降级为 None，
    调用方回退到 SequenceMatcher。
    """

    _instance: _EmbeddingModel | None = None
    _model = None
    _available: bool | None = None  # None=未初始化, True=可用, False=不可用

    MODEL_NAME = "BAAI/bge-small-zh-v1.5"

    def __new__(cls) -> _EmbeddingModel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_loaded(self) -> bool:
        """懒加载模型，返回是否可用。"""
        if self._available is not None:
            return self._available

        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model: %s ...", self.MODEL_NAME)
            start = time.time()
            self._model = SentenceTransformer(self.MODEL_NAME)
            elapsed = time.time() - start
            logger.info("Embedding model loaded in %.1fs (device=%s)",
                        elapsed, self._model.device)
            self._available = True
        except Exception as e:
            logger.warning(
                "Embedding model unavailable (%s), short-text dedup will "
                "fallback to SequenceMatcher. Error: %s", self.MODEL_NAME, e
            )
            self._available = False

        return self._available

    @property
    def available(self) -> bool:
        return self._ensure_loaded()

    def encode(self, texts: list[str]) -> np.ndarray:
        """批量编码文本为归一化向量，返回 (N, dim) ndarray。

        使用 normalize_embeddings=True 使后续余弦相似度可直接用点积计算。
        """
        if not self._ensure_loaded() or self._model is None:
            raise RuntimeError("Embedding model not available")
        return self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=64,
        )


def get_embedding_model() -> _EmbeddingModel:
    """获取全局 Embedding 模型单例。"""
    return _EmbeddingModel()


# ══════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════

@dataclass
class _IndexEntry:
    """SimHash 索引中的单条记录。

    存储在 Redis Hash 中，key=title, value="simhash_int|source|timestamp"。
    """
    simhash_value: int
    title: str
    source: str
    timestamp: float


@dataclass
class _EmbeddingEntry:
    """短文本 Embedding 索引中的单条记录。

    存储在 Redis Hash 中，key=title, value=JSON{"vec": [...], "src": "...", "ts": ...}。
    """
    vector: np.ndarray
    title: str
    source: str
    timestamp: float


# ══════════════════════════════════════════════
# 核心去重器
# ══════════════════════════════════════════════

class NewsDeduplicator:
    """多通道新闻去重器，支持长短文本路由与语义向量去重。

    使用方式（与原接口完全兼容）：
        dedup = NewsDeduplicator()
        await dedup.load_index()                # 从 Redis 加载所有索引
        unique = await dedup.deduplicate(items)  # 过滤重复，返回唯一条目
        await dedup.save_index()                # 持久化所有索引回 Redis
    """

    def __init__(self) -> None:
        self._index: list[_IndexEntry] = []           # SimHash 索引（24h 窗口）
        self._emb_index: list[_EmbeddingEntry] = []   # Embedding 索引（30min 窗口）

    # ────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────

    async def load_index(self) -> None:
        """从 Redis 加载 SimHash 索引和 Embedding 索引。"""
        await self._load_simhash_index()
        await self._load_embedding_index()

    async def save_index(self) -> None:
        """将 SimHash 索引和 Embedding 索引持久化回 Redis。"""
        await self._save_simhash_index()
        await self._save_embedding_index()

    async def deduplicate(self, items: list) -> list:
        """对 RawNewsItem 列表执行去重（长短文本自动路由）。

        流程：
        1. 按来源优先级排序
        2. 逐条计算清洗后文本长度，路由到长/短文本通道
        3. 长文本：SimHash + SequenceMatcher（逐条） → 批量 TF-IDF（幸存者间）
        4. 短文本：Embedding 余弦相似度（30min 窗口） + 数值抗误杀
        5. 返回合并后的唯一条目列表
        """
        if not items:
            return []

        # 按来源优先级排序，高优先级先处理
        items_sorted = sorted(
            items,
            key=lambda x: SOURCE_PRIORITY.get(x.source, 99),
        )

        # ── 路由分流 ──
        long_items: list = []
        short_items: list = []

        for item in items_sorted:
            clean_text = self._get_clean_text(item)
            if len(clean_text) > SHORT_TEXT_THRESHOLD:
                long_items.append(item)
            else:
                short_items.append(item)

        logger.info(
            "Route: %d long-text + %d short-text (threshold=%d chars)",
            len(long_items), len(short_items), SHORT_TEXT_THRESHOLD,
        )

        # ── 长文本通道：原有三层去重 ──
        long_unique, long_dropped = self._dedup_long_text(long_items)

        # ── 短文本通道：语义向量去重 ──
        short_unique, short_dropped = self._dedup_short_text(short_items)

        # ── 合并结果 ──
        unique = long_unique + short_unique
        total_dropped = long_dropped + short_dropped

        logger.info(
            "Dedup result: %d in → %d unique (%d dropped: long=%d, short=%d)",
            len(items), len(unique), total_dropped, long_dropped, short_dropped,
        )
        return unique

    # ────────────────────────────────────────────
    # 长文本通道（原有逻辑，完整保留）
    # ────────────────────────────────────────────

    def _dedup_long_text(self, items: list) -> tuple[list, int]:
        """长文本去重：SimHash + SequenceMatcher + TF-IDF 三层。

        返回 (去重后列表, 被淘汰总数)。
        """
        if not items:
            return [], 0

        # ── Layer 1 + 2: SimHash + SequenceMatcher (against index) ──
        survivors: list = []
        l12_dropped = 0

        for item in items:
            text = self._build_text(item.title, getattr(item, "content", ""))
            sh = self._compute_simhash(text)
            clean_title = self._clean(item.title)

            dup_entry = self._find_duplicate(sh, clean_title)

            if dup_entry is not None:
                l12_dropped += 1
                logger.info(
                    'L1/L2 dup: [%s]"%s" ≈ [%s]"%s"',
                    item.source, item.title[:40],
                    dup_entry.source, dup_entry.title[:40],
                )
                continue

            # 通过 L1+L2，加入索引
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

        return unique, l12_dropped + l3_dropped

    def _find_duplicate(self, sh: Simhash, clean_title: str) -> _IndexEntry | None:
        """在 SimHash 索引中查找重复条目。

        第一层：汉明距离 ≤ 5 → 直接判定重复
        第二层：汉明距离 6~12 时，用 SequenceMatcher 做标题相似度兜底
        """
        for entry in self._index:
            dist = self._hamming(sh.value, entry.simhash_value)
            if dist <= SIMHASH_HAMMING_THRESHOLD:
                return entry

            if dist <= 12:
                existing_clean = self._clean(entry.title)
                if clean_title and existing_clean:
                    if clean_title in existing_clean or existing_clean in clean_title:
                        return entry
                    ratio = SequenceMatcher(None, clean_title, existing_clean).ratio()
                    if ratio > SEQMATCH_RATIO_THRESHOLD:
                        return entry

        return None

    def _tfidf_dedup(self, items: list) -> tuple[list, int]:
        """第三层：对当前批次幸存条目做 TF-IDF 余弦相似度去重。

        构建方式：标题×3 + 正文前200字 → jieba 分词 → TF-IDF 向量化 → 余弦相似度矩阵。
        贪心策略：保留先出现（高优先级）的条目。
        """
        texts = []
        for item in items:
            text = self._build_text(item.title, getattr(item, "content", ""))
            tokens = " ".join(w for w in jieba.cut(text) if len(w.strip()) > 1)
            texts.append(tokens)

        try:
            vectorizer = TfidfVectorizer(max_features=5000)
            tfidf_matrix = vectorizer.fit_transform(texts)
            sim_matrix = cosine_similarity(tfidf_matrix)
        except Exception as e:
            logger.warning("TF-IDF dedup failed, skipping Layer 3: %s", e)
            return items, 0

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
                        items[j].source, items[j].title[:40],
                        items[i].source, items[i].title[:40],
                        sim_matrix[i][j],
                    )

        unique = [item for item, dup in zip(items, is_dup) if not dup]
        dropped = sum(is_dup)
        return unique, dropped

    # ────────────────────────────────────────────
    # 短文本语义通道（新增）
    # ────────────────────────────────────────────

    def _dedup_short_text(self, items: list) -> tuple[list, int]:
        """短文本去重：Embedding 余弦相似度 + 数值抗误杀。

        策略：
        1. 尝试使用 Sentence Embedding 编码短文本
        2. 与 30 分钟内的 Embedding 索引做余弦相似度比对
        3. > 0.88 → 直接判重
        4. 0.80~0.88 → 数值抗误杀（提取核心数值，数值不同则保留）
        5. < 0.80 → 保留

        降级：若 Embedding 模型不可用，回退到 SequenceMatcher 标题相似度去重。
        """
        if not items:
            return [], 0

        emb_model = get_embedding_model()
        if not emb_model.available:
            logger.info("Embedding model unavailable, short-text fallback to SequenceMatcher")
            return self._dedup_short_text_fallback(items)

        return self._dedup_short_text_semantic(items, emb_model)

    def _dedup_short_text_semantic(
        self, items: list, emb_model: _EmbeddingModel
    ) -> tuple[list, int]:
        """使用 Embedding 向量对短文本做语义去重。

        返回 (唯一条目列表, 被淘汰数量)。
        """
        now = time.time()
        cutoff = now - SHORT_TEXT_TTL_SECONDS

        # 过滤出 30 分钟内的有效索引条目
        valid_index = [e for e in self._emb_index if e.timestamp >= cutoff]

        # 批量编码当前批次的短文本
        texts = [self._get_clean_text(item) for item in items]
        try:
            vectors = emb_model.encode(texts)  # (N, dim)
        except Exception as e:
            logger.warning("Embedding encode failed, fallback: %s", e)
            return self._dedup_short_text_fallback(items)

        # 构建索引向量矩阵（用于批量计算）
        if valid_index:
            index_vecs = np.stack([e.vector for e in valid_index])  # (M, dim)
        else:
            index_vecs = None

        survivors: list = []
        dropped = 0

        for i, item in enumerate(items):
            vec = vectors[i]
            is_dup = False

            # ── 与 30 分钟索引比对 ──
            if index_vecs is not None and len(index_vecs) > 0:
                # 向量已归一化，点积即余弦相似度
                sims = index_vecs @ vec  # (M,)
                max_sim = float(np.max(sims))
                max_idx = int(np.argmax(sims))

                if max_sim > EMBEDDING_COSINE_THRESHOLD:
                    # 超过高阈值 → 直接判重
                    is_dup = True
                    logger.info(
                        'Short-text dup (cos=%.3f): [%s]"%s" ≈ [%s]"%s"',
                        max_sim, item.source, item.title[:40],
                        valid_index[max_idx].source,
                        valid_index[max_idx].title[:40],
                    )
                elif max_sim > EMBEDDING_GRAY_ZONE_LOW:
                    # 灰色地带 → 数值抗误杀
                    is_dup = self._number_safeguard(
                        texts[i],
                        valid_index[max_idx].title,
                        max_sim,
                        item,
                        valid_index[max_idx],
                    )

            # ── 与当前批次已通过的幸存者比对（防止同批次内重复） ──
            if not is_dup and survivors:
                survivor_vecs = np.stack([
                    vectors[items.index(s)] for s in survivors
                ])
                sims = survivor_vecs @ vec
                max_sim = float(np.max(sims))
                max_idx_s = int(np.argmax(sims))

                if max_sim > EMBEDDING_COSINE_THRESHOLD:
                    is_dup = True
                    logger.info(
                        'Short-text batch dup (cos=%.3f): [%s]"%s" ≈ [%s]"%s"',
                        max_sim, item.source, item.title[:40],
                        survivors[max_idx_s].source,
                        survivors[max_idx_s].title[:40],
                    )
                elif max_sim > EMBEDDING_GRAY_ZONE_LOW:
                    survivor_text = self._get_clean_text(survivors[max_idx_s])
                    is_dup = self._number_safeguard_raw(
                        texts[i], survivor_text, max_sim, item, survivors[max_idx_s]
                    )

            if is_dup:
                dropped += 1
                continue

            # 通过去重，加入索引和幸存者列表
            self._emb_index.append(_EmbeddingEntry(
                vector=vec,
                title=item.title,
                source=item.source,
                timestamp=now,
            ))
            survivors.append(item)

        return survivors, dropped

    def _dedup_short_text_fallback(self, items: list) -> tuple[list, int]:
        """Embedding 不可用时的降级方案：SequenceMatcher 标题相似度去重。

        使用较高阈值 0.6（短文本标题更敏感），配合数值抗误杀。
        """
        if not items:
            return [], 0

        FALLBACK_RATIO = 0.6
        survivors: list = []
        dropped = 0

        for item in items:
            clean = self._clean(item.title)
            is_dup = False

            for kept in survivors:
                kept_clean = self._clean(kept.title)
                if not clean or not kept_clean:
                    continue

                # 子串包含检测
                if clean in kept_clean or kept_clean in clean:
                    is_dup = True
                    break

                ratio = SequenceMatcher(None, clean, kept_clean).ratio()
                if ratio > FALLBACK_RATIO:
                    # 对灰色地带做数值抗误杀
                    text_a = self._get_clean_text(item)
                    text_b = self._get_clean_text(kept)
                    nums_a = self._extract_numbers(text_a)
                    nums_b = self._extract_numbers(text_b)
                    if nums_a and nums_b and nums_a != nums_b:
                        continue  # 数值不同 → 保留
                    is_dup = True
                    logger.info(
                        'Short-text fallback dup (ratio=%.3f): [%s]"%s" ≈ [%s]"%s"',
                        ratio, item.source, item.title[:40],
                        kept.source, kept.title[:40],
                    )
                    break

            if is_dup:
                dropped += 1
            else:
                survivors.append(item)

        return survivors, dropped

    # ────────────────────────────────────────────
    # 金融数值抗误杀机制
    # ────────────────────────────────────────────

    def _number_safeguard(
        self,
        text_a: str,
        title_b: str,
        sim: float,
        item_a,
        entry_b: _EmbeddingEntry,
    ) -> bool:
        """数值抗误杀：灰色地带（0.80~0.88）的精细判定。

        逻辑：
        - 提取两条文本中的核心数值集合
        - 如果双方都有数值且数值集合不同 → 判定为"同一事件不同指标" → 保留（返回 False）
        - 否则 → 判定为重复（返回 True）

        返回 True 表示判定为重复。
        """
        nums_a = self._extract_numbers(text_a)
        nums_b = self._extract_numbers(title_b)

        if nums_a and nums_b and nums_a != nums_b:
            logger.info(
                'Short-text KEPT by number safeguard (cos=%.3f): '
                '[%s]"%s" nums=%s vs [%s]"%s" nums=%s',
                sim, item_a.source, item_a.title[:40], nums_a,
                entry_b.source, entry_b.title[:40], nums_b,
            )
            return False  # 不是重复，保留

        logger.info(
            'Short-text gray-zone dup (cos=%.3f): [%s]"%s" ≈ [%s]"%s"',
            sim, item_a.source, item_a.title[:40],
            entry_b.source, entry_b.title[:40],
        )
        return True  # 判定重复

    def _number_safeguard_raw(
        self,
        text_a: str,
        text_b: str,
        sim: float,
        item_a,
        item_b,
    ) -> bool:
        """数值抗误杀（批次内比对版本）。"""
        nums_a = self._extract_numbers(text_a)
        nums_b = self._extract_numbers(text_b)

        if nums_a and nums_b and nums_a != nums_b:
            logger.info(
                'Short-text batch KEPT by number safeguard (cos=%.3f): '
                '[%s]"%s" nums=%s vs [%s]"%s" nums=%s',
                sim, item_a.source, item_a.title[:40], nums_a,
                item_b.source, item_b.title[:40], nums_b,
            )
            return False

        logger.info(
            'Short-text batch gray-zone dup (cos=%.3f): [%s]"%s" ≈ [%s]"%s"',
            sim, item_a.source, item_a.title[:40],
            item_b.source, item_b.title[:40],
        )
        return True

    # ────────────────────────────────────────────
    # Redis 索引持久化：SimHash（24h）
    # ────────────────────────────────────────────

    async def _load_simhash_index(self) -> None:
        """从 Redis 加载 SimHash 索引，淘汰超过 24 小时的过期条目。"""
        r = get_redis()
        raw_entries = await r.hgetall(REDIS_SIMHASH_KEY)
        cutoff = time.time() - INDEX_TTL_SECONDS
        self._index = []

        for key, value in raw_entries.items():
            try:
                parts = value.decode() if isinstance(value, bytes) else value
                sh_str, source, ts_str = parts.rsplit("|", 2)
                ts = float(ts_str)
                if ts < cutoff:
                    continue
                title = key.decode() if isinstance(key, bytes) else key
                self._index.append(_IndexEntry(
                    simhash_value=int(sh_str),
                    title=title,
                    source=source,
                    timestamp=ts,
                ))
            except (ValueError, AttributeError) as e:
                logger.debug("Skipping malformed simhash entry: %s", e)

        logger.info("Loaded SimHash index: %d entries (24h window)", len(self._index))

    async def _save_simhash_index(self) -> None:
        """将 SimHash 索引持久化回 Redis（原子 RENAME 策略）。"""
        r = get_redis()
        cutoff = time.time() - INDEX_TTL_SECONDS
        tmp_key = f"{REDIS_SIMHASH_KEY}:tmp"

        await r.delete(tmp_key)

        if not self._index:
            await r.delete(REDIS_SIMHASH_KEY)
            logger.info("Saved SimHash index: 0 entries (cleared)")
            return

        pipe = r.pipeline()
        count = 0
        for entry in self._index:
            if entry.timestamp < cutoff:
                continue
            value = f"{entry.simhash_value}|{entry.source}|{entry.timestamp}"
            pipe.hset(tmp_key, entry.title, value)
            count += 1

        if count == 0:
            pipe.delete(tmp_key)
            pipe.delete(REDIS_SIMHASH_KEY)
            await pipe.execute()
            logger.info("Saved SimHash index: 0 entries (all expired)")
            return

        pipe.expire(tmp_key, INDEX_TTL_SECONDS + 3600)
        await pipe.execute()

        await r.rename(tmp_key, REDIS_SIMHASH_KEY)
        logger.info("Saved SimHash index: %d entries (atomic RENAME)", count)

    # ────────────────────────────────────────────
    # Redis 索引持久化：Embedding（30min）
    # ────────────────────────────────────────────

    async def _load_embedding_index(self) -> None:
        """从 Redis 加载短文本 Embedding 索引，淘汰超过 30 分钟的过期条目。"""
        r = get_redis()
        raw_entries = await r.hgetall(REDIS_EMBEDDING_KEY)
        cutoff = time.time() - SHORT_TEXT_TTL_SECONDS
        self._emb_index = []

        for key, value in raw_entries.items():
            try:
                raw = value.decode() if isinstance(value, bytes) else value
                data = json.loads(raw)
                ts = float(data["ts"])
                if ts < cutoff:
                    continue
                title = key.decode() if isinstance(key, bytes) else key
                self._emb_index.append(_EmbeddingEntry(
                    vector=np.array(data["vec"], dtype=np.float32),
                    title=title,
                    source=data["src"],
                    timestamp=ts,
                ))
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                logger.debug("Skipping malformed embedding entry: %s", e)

        logger.info("Loaded Embedding index: %d entries (30min window)", len(self._emb_index))

    async def _save_embedding_index(self) -> None:
        """将短文本 Embedding 索引持久化回 Redis（原子 RENAME 策略）。"""
        r = get_redis()
        cutoff = time.time() - SHORT_TEXT_TTL_SECONDS
        tmp_key = f"{REDIS_EMBEDDING_KEY}:tmp"

        await r.delete(tmp_key)

        if not self._emb_index:
            await r.delete(REDIS_EMBEDDING_KEY)
            logger.info("Saved Embedding index: 0 entries (cleared)")
            return

        pipe = r.pipeline()
        count = 0
        for entry in self._emb_index:
            if entry.timestamp < cutoff:
                continue
            data = json.dumps({
                "vec": entry.vector.tolist(),
                "src": entry.source,
                "ts": entry.timestamp,
            })
            pipe.hset(tmp_key, entry.title, data)
            count += 1

        if count == 0:
            pipe.delete(tmp_key)
            pipe.delete(REDIS_EMBEDDING_KEY)
            await pipe.execute()
            logger.info("Saved Embedding index: 0 entries (all expired)")
            return

        pipe.expire(tmp_key, SHORT_TEXT_TTL_SECONDS + 600)  # Extra 10min buffer
        await pipe.execute()

        await r.rename(tmp_key, REDIS_EMBEDDING_KEY)
        logger.info("Saved Embedding index: %d entries (atomic RENAME)", count)

    # ────────────────────────────────────────────
    # 工具方法
    # ────────────────────────────────────────────

    def _get_clean_text(self, item) -> str:
        """获取清洗后的完整文本（标题+正文），用于长短文本路由判定。"""
        title = item.title or ""
        content = getattr(item, "content", "") or ""
        raw = title + content
        # 去除括号标记、标点、空白，得到纯净文本用于长度判定
        return _PUNCT_RE.sub("", _BRACKET_RE.sub("", raw))

    @staticmethod
    def _extract_numbers(text: str) -> set[str]:
        """从文本中提取核心金融数值（带单位），用于抗误杀比对。

        示例：
          "美国12月新屋开工环比 6.2%，预期 1.1%" → {"6.2%", "1.1%"}
          "新屋开工 140.4万户，预期 130.4万户"     → {"140.4万户", "130.4万户"}

        策略：跳过看起来像"日期"的数字（如 12月、2月18日）。
        """
        # 预过滤：去除日期模式 "N月N日" / "N月"
        cleaned = re.sub(r"\d{1,2}月\d{1,2}日", "", text)
        cleaned = re.sub(r"\d{1,4}年", "", cleaned)
        cleaned = re.sub(r"(?<!\d)\d{1,2}月(?!\d)", "", cleaned)

        results = set()
        for match in _NUMBER_RE.finditer(cleaned):
            num, unit = match.group(1), match.group(2) or ""
            # 跳过纯整数且无单位（可能是日期残留或无意义数字）
            if not unit and "." not in num:
                continue
            results.add(f"{num}{unit}")
        return results

    @staticmethod
    def _build_text(title: str, content: str) -> str:
        """拼接标题+正文用于 SimHash / TF-IDF 计算。标题重复3次以加权。"""
        parts = [title] * 3
        if content and content != title:
            parts.append(content[:200])
        return " ".join(parts)

    @staticmethod
    def _compute_simhash(text: str) -> Simhash:
        """使用 jieba 分词计算 64-bit SimHash 指纹。"""
        words = list(jieba.cut(text))
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
        """清洗标题：去除方括号标记、标点符号、空白字符。"""
        t = _BRACKET_RE.sub("", title)
        t = _PUNCT_RE.sub("", t)
        return t
