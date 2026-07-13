"""新闻去重引擎 — 在 LLM 评分之前执行多层去重，零 API 成本（长文本）+ 低成本 API（短文本快讯）。

架构概览：长短文本路由（Length-based Routing）
═══════════════════════════════════════════════
进入去重前，先根据"清洗后标题+正文"长度做路由：

  【长文本通道】长度 > 150 字 → 四层去重
    第一层：SimHash 指纹 + 汉明距离（≤5 视为重复）
    第二层：SequenceMatcher 标题相似度（>0.5 视为重复），2 小时窗口逐条比对
    第三层：TF-IDF 余弦相似度（>0.65 视为重复），当前批次内部比对
    第四层：标题语义去重（Embedding API），跨批次跨源跨措辞识别同一事件

  【短文本语义通道】长度 ≤ 150 字（金融快讯等）
    调用 Embedding API 获取向量（提供商可通过 EMBEDDING_PROVIDER 环境变量切换：
    zhipu → 智谱 embedding-3/embedding-2，siliconflow → 硅基流动 BAAI/bge-m3 免费），
    计算余弦相似度，仅与过去 30 分钟内的短文本向量对比。
    - 同源（same source）且余弦相似度 > 0.80 → 判定重复（真重复，直接丢弃）
    - 跨源（different source）且余弦相似度 > 0.80 → 事件聚合：放行但标记 related_to_url
    - 余弦相似度 0.73~0.80（灰色地带）→ 数值抗误杀检测：
      提取核心数值实体，若数值集合不同 → 保留（同一事件的不同指标），
      同源且数值相同 → 判定重复丢弃，
      跨源且数值相同 → 事件聚合（放行但标记 related_to_url）。
    - 余弦相似度 0.67~0.80 → 事件聚合区：放行但标记 related_to_url，
      前端可据此将关联报道折叠展示。
    - 余弦相似度 ≤ 0.67 → 独立事件，正常放行。
    降级策略：若 API 调用失败，回退到 SequenceMatcher 标题相似度。

存储方案：
  - Redis Hash 持久化 24 小时 SimHash 索引
  - Redis Hash 持久化 30 分钟短文本 Embedding 索引
  - 写入均采用"先写临时 key → 原子 RENAME"策略
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

import httpx
import jieba
from simhash import Simhash
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.config import settings
from app.redis import get_redis

logger = logging.getLogger("alphareader.dedup")

# ── 长短文本路由阈值 ──
SHORT_TEXT_LENGTH_THRESHOLD = 150   # ≤150 字 → 短文本语义通道

# ── 长文本去重阈值 ──
SIMHASH_HAMMING_THRESHOLD = 5       # 第一层：汉明距离 ≤ 5 判定为重复
SEQMATCH_RATIO_THRESHOLD = 0.5      # 第二层：SequenceMatcher 比值 > 0.5 判定为重复
TFIDF_COSINE_THRESHOLD = 0.65       # 第三层：TF-IDF 余弦相似度 > 0.65 判定为重复
INDEX_TTL_SECONDS = 24 * 3600       # SimHash 索引滑动窗口：24 小时
REDIS_SIMHASH_KEY = "alphareader:simhash_index"

# ── 短文本语义通道阈值 ──
EMBEDDING_COSINE_THRESHOLD = 0.80   # 余弦相似度 > 0.80 → 直接判重（绝对去重区）
EMBEDDING_CLUSTER_THRESHOLD = 0.67  # 余弦相似度 > 0.67 → 事件聚合区（放行但标记关联）
EMBEDDING_GRAY_ZONE_LOW = 0.73      # 灰色地带下界：0.73~0.80 触发数值抗误杀
SHORT_TEXT_TTL_SECONDS = 90 * 60    # Embedding 索引滑动窗口：90 分钟
REDIS_EMBEDDING_KEY = "alphareader:embedding_index"

# ── Embedding API 配置（多提供商支持）──
# 提供商：zhipu（智谱 AI）或 siliconflow（硅基流动，免费）
EMBEDDING_PROVIDER = settings.EMBEDDING_PROVIDER.lower()

# 提供商配置表
_PROVIDER_CONFIG = {
    "zhipu": {
        "api_url": "https://open.bigmodel.cn/api/paas/v4/embeddings",
        "api_key": settings.ZHIPU_API_KEY,
        "model": settings.ZHIPU_EMBEDDING_MODEL,
        # embedding-3 用 256 维节省存储；embedding-2 固定 1024 维
        "dimensions": 256 if settings.ZHIPU_EMBEDDING_MODEL == "embedding-3" else 1024,
        # embedding-3 支持自定义维度参数；embedding-2 不支持
        "supports_dimensions": settings.ZHIPU_EMBEDDING_MODEL == "embedding-3",
        "batch_size": 64,
    },
    "siliconflow": {
        "api_url": "https://api.siliconflow.cn/v1/embeddings",
        "api_key": settings.SILICONFLOW_API_KEY,
        "model": settings.SILICONFLOW_EMBEDDING_MODEL,
        # BAAI/bge-m3, bge-large-zh-v1.5 均为固定 1024 维
        "dimensions": 1024,
        "supports_dimensions": False,
        "batch_size": 32,  # SiliconFlow batch size 最大 32
    },
}

_active_provider = _PROVIDER_CONFIG.get(EMBEDDING_PROVIDER, _PROVIDER_CONFIG["siliconflow"])
EMBEDDING_API_URL = _active_provider["api_url"]
EMBEDDING_API_KEY = _active_provider["api_key"]
EMBEDDING_MODEL = _active_provider["model"]
EMBEDDING_DIMENSIONS = _active_provider["dimensions"]
EMBEDDING_SUPPORTS_DIMENSIONS = _active_provider["supports_dimensions"]
EMBEDDING_BATCH_SIZE = _active_provider["batch_size"]
EMBEDDING_API_TIMEOUT = 15          # API 超时秒数

# 源优先级：数值越小越优先保留
SOURCE_PRIORITY = {
    "财联社": 1,
    "华尔街见闻": 2,
    "第一财经": 3,
    "Reuters": 4,
    "MarketWatch": 4,
    "Seeking Alpha": 6,
    "TechCrunch": 7,
    "Finnhub": 8,
}

# 标题清洗正则：去掉【】[]括号标记及其内容、去掉中英文标点和空白
_BRACKET_RE = re.compile(r"[【\[][^\]】]*[】\]]")
_PUNCT_RE = re.compile(
    r"[，。！？、；：\u201c\u201d\u2018\u2019（）\s.,!?;:\"'()\-\u3000]"
)

# 金融数值提取正则：匹配"6.2%"、"140.4万户"、"1.234亿美元"等，排除日期干扰
_NUMBER_RE = re.compile(
    r"(?<!\d月)(?<!\d日)"               # 排除"2月"、"18日"后紧跟的数字
    r"(\d+(?:\.\d+)?)"                   # 核心数字（整数或小数）
    r"(%|万户|亿[美元人民币欧元日元英镑]*|万亿|万|个基点|bp|bps)?"  # 单位后缀
)
# 日期模式：用于过滤掉"2月18日"、"12月"等日期数字
_DATE_FILTER_RE = re.compile(r"\d{1,2}月\d{1,2}日|\d{1,4}年|\d{1,2}月")


# ══════════════════════════════════════════════
# Embedding API 客户端（异步，基于 httpx，多提供商）
# ══════════════════════════════════════════════

async def _call_embedding(texts: list[str]) -> list[list[float]] | None:
    """调用 Embedding API 获取文本向量（支持智谱 / 硅基流动）。

    根据 EMBEDDING_PROVIDER 配置自动路由到对应的 API 端点。
    接口协议均为 OpenAI 兼容格式（/v1/embeddings）。

    参数：
        texts: 待向量化的文本列表

    返回：
        向量列表，失败返回 None。
    """
    if not EMBEDDING_API_KEY:
        logger.warning(
            "%s API key not configured, embedding unavailable (provider=%s)",
            EMBEDDING_PROVIDER, EMBEDDING_PROVIDER,
        )
        return None

    headers = {
        "Authorization": f"Bearer {EMBEDDING_API_KEY}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": EMBEDDING_MODEL,
        "input": texts,
    }
    # 仅在支持自定义维度的模型上传 dimensions 参数
    if EMBEDDING_SUPPORTS_DIMENSIONS:
        payload["dimensions"] = EMBEDDING_DIMENSIONS

    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_API_TIMEOUT) as client:
            resp = await client.post(
                EMBEDDING_API_URL,
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        # 按 index 排序，确保顺序与输入一致
        embeddings_data = sorted(data["data"], key=lambda x: x["index"])
        vectors = [item["embedding"] for item in embeddings_data]

        tokens_used = data.get("usage", {}).get("total_tokens", 0)
        logger.info(
            "Embedding [%s/%s]: %d texts → %d vectors (%d-dim, %d tokens)",
            EMBEDDING_PROVIDER, EMBEDDING_MODEL,
            len(texts), len(vectors), EMBEDDING_DIMENSIONS, tokens_used,
        )
        return vectors

    except httpx.HTTPStatusError as e:
        logger.warning(
            "Embedding API HTTP error %d (provider=%s): %s",
            e.response.status_code, EMBEDDING_PROVIDER, e,
        )
        return None
    except Exception as e:
        logger.warning("Embedding API call failed (provider=%s): %s", EMBEDDING_PROVIDER, e)
        return None


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度（纯 Python 实现，无需 numpy）。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


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

    存储在 Redis Hash 中，key=title, value=JSON{"vec": [...], "src": "...", "ts": ..., "url": "..."}。
    """
    vector: list[float]
    title: str
    source: str
    timestamp: float
    url: str = ""  # 用于事件聚合时回溯关联新闻的 URL


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
        self._index: list[_IndexEntry] = []           # SimHash 索引（24h 窗口，Redis 持久化）
        self._historical_index: list[_IndexEntry] = []  # P5: DB 加载的历史指纹（7天，不回写 Redis）
        self._emb_index: list[_EmbeddingEntry] = []   # Embedding 索引（90min 窗口）

    # ────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────

    async def load_index(self) -> None:
        """从 Redis 加载 SimHash 索引和 Embedding 索引。"""
        await self._load_simhash_index()
        await self._load_embedding_index()

    def preload_historical(self, entries: list[tuple[str, str, int, float]]) -> None:
        """P5: 注入 DB 加载的历史 SimHash 指纹，扩展去重窗口到 7 天。

        entries: [(title, source, simhash_value, timestamp_epoch), ...]
        这些条目加入 _historical_index，参与 _find_duplicate 比对，
        但不会通过 save_index() 回写 Redis（避免 Redis 膨胀）。
        """
        for title, source, sh_val, ts in entries:
            self._historical_index.append(_IndexEntry(
                simhash_value=sh_val,
                title=title,
                source=source,
                timestamp=ts,
            ))
        logger.info("Preloaded %d historical SimHash entries from DB (7-day window)", len(entries))

    async def save_index(self) -> None:
        """将 SimHash 索引和 Embedding 索引持久化回 Redis。"""
        await self._save_simhash_index()
        await self._save_embedding_index()

    async def deduplicate(self, items: list) -> list:
        """对 RawNewsItem 列表执行去重（自动路由长/短文本通道）。

        返回去重后的唯一条目列表，同时将新的唯一条目加入索引。
        """
        if not items:
            return []

        # 按源优先级排序，高优先级先处理
        items_sorted = sorted(
            items,
            key=lambda x: SOURCE_PRIORITY.get(x.source, 99),
        )

        # ── 路由：按文本长度分流 ──
        short_items: list = []
        long_items: list = []

        for item in items_sorted:
            clean_text = self._get_clean_text(item)
            if len(clean_text) <= SHORT_TEXT_LENGTH_THRESHOLD:
                short_items.append(item)
            else:
                long_items.append(item)

        logger.info(
            "Text routing: %d short (≤%d) + %d long (>%d)",
            len(short_items), SHORT_TEXT_LENGTH_THRESHOLD,
            len(long_items), SHORT_TEXT_LENGTH_THRESHOLD,
        )

        # ── 长文本通道：SimHash + SequenceMatcher + TF-IDF ──
        long_unique, long_dropped = await self._dedup_long_text(long_items)

        # ── 短文本通道：Embedding 余弦相似度 ──
        short_unique, short_dropped = await self._dedup_short_text(short_items)

        unique = long_unique + short_unique
        total_dropped = long_dropped + short_dropped

        logger.info(
            "Dedup result: %d in → %d unique (%d dropped: long=%d, short=%d)",
            len(items), len(unique), total_dropped, long_dropped, short_dropped,
        )
        return unique

    # ────────────────────────────────────────────
    # 长文本通道（四层去重）
    # ────────────────────────────────────────────

    async def _dedup_long_text(self, items: list) -> tuple[list, int]:
        """长文本四层去重：SimHash + SequenceMatcher + TF-IDF + 标题语义。"""
        if not items:
            return [], 0

        # ── Layer 1 + 2: SimHash + SequenceMatcher（逐条与历史索引比对）──
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

            # Passed L1+L2, add to index
            self._index.append(_IndexEntry(
                simhash_value=sh.value,
                title=item.title,
                source=item.source,
                timestamp=time.time(),
            ))
            survivors.append(item)

        # ── Layer 3: TF-IDF 余弦相似度（当前批次幸存者内部比对）──
        l3_dropped = 0
        if len(survivors) >= 2:
            unique, l3_dropped = self._tfidf_dedup(survivors)
        else:
            unique = survivors

        # ── Layer 4: 标题语义去重（Embedding 跨批次检查）──
        # 针对不同措辞描述同一事件的情况（如中英文翻译差异、改写）
        l4_dropped = 0
        if len(unique) >= 1:
            unique, l4_dropped = await self._title_semantic_dedup(unique)

        total_dropped = l12_dropped + l3_dropped + l4_dropped
        return unique, total_dropped

    async def _title_semantic_dedup(self, items: list) -> tuple[list, int]:
        """Layer 4: 对长文本标题做 Embedding 语义去重（含跨源聚合）。

        用 Embedding API 获取标题向量，与 Embedding 索引中的近期标题
        以及当前批次内部做余弦相似度比对。
        仅用标题（非全文），有效识别跨源/跨语言的同一事件。

        跨源聚合策略（与短文本通道一致）：
          同源 + cos > 0.80  → 去重丢弃
          跨源 + cos > 0.70  → 放行，标记 related_to_url
          cos ≤ 0.67         → 独立事件
        """
        titles = [item.title for item in items]
        vectors = await _call_embedding(titles)

        if vectors is None or len(vectors) != len(items):
            logger.debug("L4 title semantic dedup skipped: embedding unavailable")
            return items, 0

        now = time.time()
        cutoff = now - SHORT_TEXT_TTL_SECONDS
        valid_emb_index = [e for e in self._emb_index if e.timestamp >= cutoff]

        survivors: list = []
        dropped = 0

        for i, item in enumerate(items):
            vec = vectors[i]
            is_dup = False
            cluster_url: str | None = None

            # 与 Embedding 索引（含短文本历史）比对
            for entry in valid_emb_index:
                sim = _cosine_sim(vec, entry.vector)
                same_source = (item.source == entry.source)

                if sim > EMBEDDING_COSINE_THRESHOLD:
                    if same_source:
                        is_dup = True
                        logger.info(
                            'L4 title-semantic same-source dup (cos=%.3f): [%s]"%s" ≈ [%s]"%s"',
                            sim, item.source, item.title[:40],
                            entry.source, entry.title[:40],
                        )
                        break
                    else:
                        if entry.url and cluster_url is None:
                            cluster_url = entry.url
                            logger.info(
                                'L4 title-semantic cross-source cluster (cos=%.3f): '
                                '[%s]"%s" → related_to [%s]"%s"',
                                sim, item.source, item.title[:40],
                                entry.source, entry.title[:40],
                            )
                elif sim > EMBEDDING_GRAY_ZONE_LOW:
                    title_text = self._get_clean_text(item)
                    safeguard_dup = self._number_safeguard(
                        title_text, entry.title, sim, item, entry,
                    )
                    if safeguard_dup:
                        if same_source:
                            is_dup = True
                            break
                        else:
                            if entry.url and cluster_url is None:
                                cluster_url = entry.url
                    else:
                        if entry.url and cluster_url is None:
                            cluster_url = entry.url
                elif sim > EMBEDDING_CLUSTER_THRESHOLD:
                    if entry.url and cluster_url is None:
                        cluster_url = entry.url
                        logger.info(
                            'L4 title-semantic event-cluster (cos=%.3f): '
                            '[%s]"%s" → related_to [%s]"%s"',
                            sim, item.source, item.title[:40],
                            entry.source, entry.title[:40],
                        )

            # 与当前批次已通过的幸存者比对
            if not is_dup:
                for j, kept in enumerate(survivors):
                    kept_idx = items.index(kept)
                    sim = _cosine_sim(vec, vectors[kept_idx])
                    same_source = (item.source == kept.source)

                    if sim > EMBEDDING_COSINE_THRESHOLD:
                        if same_source:
                            is_dup = True
                            logger.info(
                                'L4 title-semantic batch same-source dup (cos=%.3f): '
                                '[%s]"%s" ≈ [%s]"%s"',
                                sim, item.source, item.title[:40],
                                kept.source, kept.title[:40],
                            )
                            break
                        else:
                            if kept.url and cluster_url is None:
                                cluster_url = kept.url
                    elif sim > EMBEDDING_GRAY_ZONE_LOW:
                        kept_text = self._get_clean_text(kept)
                        title_text = self._get_clean_text(item)
                        safeguard_dup = self._number_safeguard(
                            title_text, kept_text, sim, item, kept,
                        )
                        if safeguard_dup:
                            if same_source:
                                is_dup = True
                                break
                            else:
                                if kept.url and cluster_url is None:
                                    cluster_url = kept.url
                        else:
                            if kept.url and cluster_url is None:
                                cluster_url = kept.url
                    elif sim > EMBEDDING_CLUSTER_THRESHOLD:
                        if kept.url and cluster_url is None:
                            cluster_url = kept.url

            if is_dup:
                dropped += 1
                continue

            # 写入事件聚合标记
            if cluster_url is not None:
                item.related_to_url = cluster_url

            # 通过去重，将标题向量加入 Embedding 索引（供后续批次使用）
            self._emb_index.append(_EmbeddingEntry(
                vector=vec,
                title=item.title,
                source=item.source,
                timestamp=now,
                url=getattr(item, "url", ""),
            ))
            survivors.append(item)

        if dropped > 0:
            logger.info("L4 title-semantic: dropped %d long-text duplicates", dropped)
        return survivors, dropped

    # ────────────────────────────────────────────
    # 短文本语义通道（Embedding API）
    # ────────────────────────────────────────────

    async def _dedup_short_text(self, items: list) -> tuple[list, int]:
        """短文本去重入口：调用 Embedding API 获取向量后做余弦相似度比对。

        失败时降级到 SequenceMatcher。
        """
        if not items:
            return [], 0

        # 准备文本
        texts = [self._get_clean_text(item) for item in items]

        # 调用 Embedding API
        vectors = await _call_embedding(texts)

        if vectors is None or len(vectors) != len(items):
            logger.warning("Embedding API failed or mismatch, fallback to SequenceMatcher")
            return self._dedup_short_text_fallback(items)

        return self._dedup_short_text_semantic(items, texts, vectors)

    def _dedup_short_text_semantic(
        self, items: list, texts: list[str], vectors: list[list[float]]
    ) -> tuple[list, int]:
        """使用 Embedding 向量对短文本做语义去重（跨源聚合策略）。

        核心策略：同源去重，跨源聚合。
          同源 + cos > 0.80  → 真重复，丢弃
          跨源 + cos > 0.70  → 同一事件多源报道，放行但标记 related_to_url
          cos ≤ 0.67         → 独立事件，正常放行

        0.73~0.80 灰色地带叠加数值抗误杀检测。
        """
        now = time.time()
        cutoff = now - SHORT_TEXT_TTL_SECONDS

        # 过滤出 90 分钟内的有效索引条目
        valid_index = [e for e in self._emb_index if e.timestamp >= cutoff]

        survivors: list = []
        dropped = 0

        for i, item in enumerate(items):
            vec = vectors[i]
            is_dup = False
            cluster_url: str | None = None  # 事件聚合区匹配到的关联 URL

            # ── 与历史索引比对 ──
            for entry in valid_index:
                sim = _cosine_sim(vec, entry.vector)
                same_source = (item.source == entry.source)

                if sim > EMBEDDING_COSINE_THRESHOLD:
                    if same_source:
                        # ── 同源 + 高相似度 → 真重复，丢弃 ──
                        is_dup = True
                        logger.info(
                            'Short-text same-source dup (cos=%.3f): [%s]"%s" ≈ [%s]"%s"',
                            sim, item.source, item.title[:40],
                            entry.source, entry.title[:40],
                        )
                        break
                    else:
                        # ── 跨源 + 高相似度 → 同一事件，标记聚合 ──
                        if entry.url and cluster_url is None:
                            cluster_url = entry.url
                            logger.info(
                                'Short-text cross-source cluster (cos=%.3f): '
                                '[%s]"%s" → related_to [%s]"%s"',
                                sim, item.source, item.title[:40],
                                entry.source, entry.title[:40],
                            )
                elif sim > EMBEDDING_GRAY_ZONE_LOW:
                    # ── 灰色地带 (0.73~0.80)：数值抗误杀 ──
                    safeguard_dup = self._number_safeguard(
                        texts[i], entry.title, sim, item, entry,
                    )
                    if safeguard_dup:
                        if same_source:
                            is_dup = True
                            break
                        else:
                            # 跨源 + 数值相同 → 聚合而非丢弃
                            if entry.url and cluster_url is None:
                                cluster_url = entry.url
                                logger.info(
                                    'Short-text cross-source cluster (cos=%.3f, gray-zone): '
                                    '[%s]"%s" → related_to [%s]"%s"',
                                    sim, item.source, item.title[:40],
                                    entry.source, entry.title[:40],
                                )
                    else:
                        # 数值不同 → 保留，但仍属于事件聚合区
                        if entry.url and cluster_url is None:
                            cluster_url = entry.url
                            logger.info(
                                'Short-text event-cluster (cos=%.3f, gray-zone kept): '
                                '[%s]"%s" → related_to [%s]"%s"',
                                sim, item.source, item.title[:40],
                                entry.source, entry.title[:40],
                            )
                elif sim > EMBEDDING_CLUSTER_THRESHOLD:
                    # ── 事件聚合区 (0.70~0.73)：放行但标记关联 ──
                    if entry.url and cluster_url is None:
                        cluster_url = entry.url
                        logger.info(
                            'Short-text event-cluster (cos=%.3f): '
                            '[%s]"%s" → related_to [%s]"%s"',
                            sim, item.source, item.title[:40],
                            entry.source, entry.title[:40],
                        )

            # ── 与当前批次已通过的幸存者比对（防止同批次内重复）──
            if not is_dup:
                for j, kept in enumerate(survivors):
                    kept_idx = items.index(kept)
                    sim = _cosine_sim(vec, vectors[kept_idx])
                    same_source = (item.source == kept.source)

                    if sim > EMBEDDING_COSINE_THRESHOLD:
                        if same_source:
                            is_dup = True
                            logger.info(
                                'Short-text batch same-source dup (cos=%.3f): [%s]"%s" ≈ [%s]"%s"',
                                sim, item.source, item.title[:40],
                                kept.source, kept.title[:40],
                            )
                            break
                        else:
                            # 跨源 → 聚合
                            if kept.url and cluster_url is None:
                                cluster_url = kept.url
                                logger.info(
                                    'Short-text batch cross-source cluster (cos=%.3f): '
                                    '[%s]"%s" → related_to [%s]"%s"',
                                    sim, item.source, item.title[:40],
                                    kept.source, kept.title[:40],
                                )
                    elif sim > EMBEDDING_GRAY_ZONE_LOW:
                        kept_text = self._get_clean_text(kept)
                        safeguard_dup = self._number_safeguard(
                            texts[i], kept_text, sim, item, kept,
                        )
                        if safeguard_dup:
                            if same_source:
                                is_dup = True
                                break
                            else:
                                if kept.url and cluster_url is None:
                                    cluster_url = kept.url
                        else:
                            if kept.url and cluster_url is None:
                                cluster_url = kept.url
                    elif sim > EMBEDDING_CLUSTER_THRESHOLD:
                        if kept.url and cluster_url is None:
                            cluster_url = kept.url
                            logger.info(
                                'Short-text batch event-cluster (cos=%.3f): '
                                '[%s]"%s" → related_to [%s]"%s"',
                                sim, item.source, item.title[:40],
                                kept.source, kept.title[:40],
                            )

            if is_dup:
                dropped += 1
                continue

            # 写入事件聚合标记
            if cluster_url is not None:
                item.related_to_url = cluster_url

            # 通过去重，加入索引和幸存者列表
            self._emb_index.append(_EmbeddingEntry(
                vector=vec,
                title=item.title,
                source=item.source,
                timestamp=now,
                url=getattr(item, "url", ""),
            ))
            survivors.append(item)

        return survivors, dropped

    def _dedup_short_text_fallback(self, items: list) -> tuple[list, int]:
        """Embedding API 不可用时的降级方案：SequenceMatcher 标题相似度去重。

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
        self, text_a: str, text_b: str, sim: float,
        item_a: object, item_b: object,
    ) -> bool:
        """灰色地带数值抗误杀：提取数值实体，数值不同则保留。

        返回 True 表示判定为重复，False 表示保留。
        """
        nums_a = self._extract_numbers(text_a)
        nums_b = self._extract_numbers(text_b)

        if nums_a and nums_b and nums_a != nums_b:
            # 都有数值但数值不同 → 同一事件的不同指标，保留
            logger.info(
                'Number safeguard KEPT (cos=%.3f, nums=%s vs %s): [%s]"%s" vs [%s]"%s"',
                sim, nums_a, nums_b,
                getattr(item_a, "source", "?"), getattr(item_a, "title", "?")[:40],
                getattr(item_b, "source", "?"), getattr(item_b, "title", "?")[:40],
            )
            return False

        # 无数值差异 → 判定重复
        logger.info(
            'Short-text gray-zone dup (cos=%.3f): [%s]"%s" ≈ [%s]"%s"',
            sim,
            getattr(item_a, "source", "?"), getattr(item_a, "title", "?")[:40],
            getattr(item_b, "source", "?"), getattr(item_b, "title", "?")[:40],
        )
        return True

    @staticmethod
    def _extract_numbers(text: str) -> set[str]:
        """从文本中提取金融数值实体，排除日期数字。

        示例：
          "美国12月新屋开工环比 6.2%，预期 1.1%。" → {"6.2%", "1.1%"}
          "新屋开工 140.4万户，预期 130.4万户。"     → {"140.4万户", "130.4万户"}
          "财联社2月18日电"                          → set()（日期被过滤）
        """
        # 先移除日期片段，避免"12月"中的"12"被误提取
        cleaned = _DATE_FILTER_RE.sub("", text)
        matches = _NUMBER_RE.findall(cleaned)
        # matches 是 [(数字, 单位), ...] 的列表
        result = set()
        for num, unit in matches:
            if unit:
                result.add(f"{num}{unit}")
            elif float(num) > 100:
                # 无单位但数值较大的独立数字（如 "140.4"）
                result.add(num)
        return result

    # ────────────────────────────────────────────
    # 长文本三层去重内部方法（完整保留）
    # ────────────────────────────────────────────

    def _find_duplicate(self, sh: Simhash, clean_title: str) -> _IndexEntry | None:
        """在索引中查找是否存在重复条目。

        第一层：SimHash 汉明距离 ≤ 5 → 直接判定重复
               P5: 同时检查 _index（24h Redis）和 _historical_index（7天 DB），扩展旧闻识别窗口
        第二层：SequenceMatcher 标题相似度 > 0.5 → 判定重复
               包含子串包含检测。对所有索引条目执行，不受汉明距离限制。
               为控制性能，仅对 2 小时内的近期条目做逐条标题比对。
        """
        recent_cutoff = time.time() - 2 * 3600  # 2 小时窗口
        title_candidates: list[_IndexEntry] = []

        # P5: 合并 Redis 索引 + DB 历史索引进行 L1 SimHash 比对
        all_entries = self._index + self._historical_index
        for entry in all_entries:
            dist = self._hamming(sh.value, entry.simhash_value)
            if dist <= SIMHASH_HAMMING_THRESHOLD:
                return entry

            # 收集近期条目用于 L2 标题相似度检查（不限汉明距离）
            if entry.timestamp >= recent_cutoff:
                title_candidates.append(entry)

        # L2: 对近期索引做标题相似度检查
        if clean_title:
            for entry in title_candidates:
                existing_clean = self._clean(entry.title)
                if not existing_clean:
                    continue
                if clean_title in existing_clean or existing_clean in clean_title:
                    return entry
                ratio = SequenceMatcher(None, clean_title, existing_clean).ratio()
                if ratio > SEQMATCH_RATIO_THRESHOLD:
                    return entry

        return None

    def _tfidf_dedup(self, items: list) -> tuple[list, int]:
        """第三层：对当前批次幸存条目做 TF-IDF 余弦相似度去重。

        构建方式：标题×3 + 正文前200字 → jieba 分词 → TF-IDF 向量化 → 余弦相似度矩阵。
        贪心策略保留先出现的条目（已按优先级排序）。
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
    # Redis 索引持久化
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
                logger.debug("Skipping malformed SimHash index entry: %s", e)

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

    async def _load_embedding_index(self) -> None:
        """从 Redis 加载 Embedding 索引，淘汰超过 30 分钟的过期条目。

        维度安全：若 Redis 中存储的向量维度与当前配置不一致
        （说明模型已切换），自动清空旧索引，避免跨维度比对。
        """
        r = get_redis()
        raw_entries = await r.hgetall(REDIS_EMBEDDING_KEY)
        cutoff = time.time() - SHORT_TEXT_TTL_SECONDS
        self._emb_index = []

        dim_mismatch_count = 0
        for key, value in raw_entries.items():
            try:
                data = json.loads(
                    value.decode() if isinstance(value, bytes) else value
                )
                ts = float(data["ts"])
                if ts < cutoff:
                    continue
                vec = data["vec"]
                # 维度安全检查：跳过与当前模型维度不匹配的条目
                if len(vec) != EMBEDDING_DIMENSIONS:
                    dim_mismatch_count += 1
                    continue
                title = key.decode() if isinstance(key, bytes) else key
                self._emb_index.append(_EmbeddingEntry(
                    vector=vec,
                    title=title,
                    source=data["src"],
                    timestamp=ts,
                    url=data.get("url", ""),
                ))
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                logger.debug("Skipping malformed Embedding index entry: %s", e)

        if dim_mismatch_count > 0:
            logger.warning(
                "Embedding model switched: discarded %d entries with mismatched dimensions "
                "(current model=%s, dim=%d)",
                dim_mismatch_count, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS,
            )

        logger.info(
            "Loaded Embedding index: %d entries (90min window, model=%s, dim=%d)",
            len(self._emb_index), EMBEDDING_MODEL, EMBEDDING_DIMENSIONS,
        )

    async def _save_embedding_index(self) -> None:
        """将 Embedding 索引持久化回 Redis（原子 RENAME 策略）。"""
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
                "vec": entry.vector,
                "src": entry.source,
                "ts": entry.timestamp,
                "url": entry.url,
            })
            pipe.hset(tmp_key, entry.title, data)
            count += 1

        if count == 0:
            pipe.delete(tmp_key)
            pipe.delete(REDIS_EMBEDDING_KEY)
            await pipe.execute()
            logger.info("Saved Embedding index: 0 entries (all expired)")
            return

        pipe.expire(tmp_key, SHORT_TEXT_TTL_SECONDS + 600)
        await pipe.execute()
        await r.rename(tmp_key, REDIS_EMBEDDING_KEY)
        logger.info("Saved Embedding index: %d entries (atomic RENAME)", count)

    # ────────────────────────────────────────────
    # 工具方法
    # ────────────────────────────────────────────

    @staticmethod
    def _get_clean_text(item: object) -> str:
        """获取清洗后的 标题+正文 文本，用于长度判断和向量化。"""
        title = getattr(item, "title", "")
        content = getattr(item, "content", "")
        text = title
        if content and content != title:
            text += content[:200]
        # 去掉括号标记和多余空白
        text = _BRACKET_RE.sub("", text)
        text = re.sub(r"\s+", "", text)
        return text

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
        """计算两个 64-bit 整数之间的汉明距离。"""
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
