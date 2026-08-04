"""事件记忆 (event_memory.py)
==============================
方案B：给事件合成加一层「跨周期语义召回」。

现有的 event_versions + DigestEventLink 只解决**同一事件**在相邻时段的对比，
无法回答「这类事件历史上通常怎么演进」。本模块补上这一层：

  1. 事件合成成功后，把事件包（title + summary）向量化存入 news.event_embedding；
  2. 下次合成时，用当前簇的语义向量召回近 N 天 top-k 相似的**历史事件**，
     以「背景参照」注入 prompt，帮助 LLM 写出更有依据的 why_important / watch_next。

工程取舍：
  - 不引入 pgvector / Qdrant。候选量级为「近 90 天的事件根」（千级），
    每轮 pipeline 只加载一次、做一次 numpy 矩阵乘法，耗时 <10ms，内存 <20MB。
  - 向量存 REAL[]，配合 event_embedding_model 标签（provider/model/dim）。
    切换 EMBEDDING_PROVIDER 或维度后，旧向量因标签不匹配自动被忽略并逐步覆盖，
    不需要数据迁移，也不会出现维度不一致的脏比对。
  - Embedding API 复用去重器的 `_call_embedding`，每轮 pipeline 仅新增 2 次批量调用
    （召回 query 一次 + 回写事件包一次），token 成本可忽略。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import REAL, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

from app.config import settings
from app.database import async_session
from app.utils.deduplicator import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    _call_embedding,
)

logger = logging.getLogger("alphareader.event_memory")

# 送去向量化的文本上限（Embedding API 按 token 计费，事件包本身也就百余字）
_EMBED_TEXT_CHARS = 400


def embedding_tag() -> str:
    """当前 Embedding 配置指纹。写入向量时一并落库，比对时用于过滤异构向量。"""
    return f"{EMBEDDING_PROVIDER}/{EMBEDDING_MODEL}/{EMBEDDING_DIMENSIONS}"[:64]


def event_doc_text(title: str | None, summary: str | None) -> str:
    """事件包语义文本：标题 + 摘要。用于生成存档向量。"""
    return f"{(title or '').strip()}。{(summary or '').strip()}"[:_EMBED_TEXT_CHARS].strip("。")


def cluster_query_text(cluster: dict) -> str:
    """召回用的 query 文本。

    已合成过的事件用事件包（语义更准）；首次合成的簇退化为根报道标题 + 摘要。
    """
    if cluster.get("event_title"):
        return event_doc_text(cluster.get("event_title"), cluster.get("event_summary"))
    return event_doc_text(cluster.get("title"), cluster.get("ai_summary"))


@dataclass(frozen=True)
class MemoryHit:
    """一条被召回的历史事件。"""

    event_id: str
    title: str
    summary: str
    status: str
    version: int
    seen_at: datetime | None
    similarity: float


class EventMemoryIndex:
    """近 N 天历史事件的内存向量索引（每轮 pipeline 构建一次，用完即弃）。"""

    __slots__ = ("_meta", "_matrix")

    def __init__(self, meta: list[dict], matrix: np.ndarray) -> None:
        self._meta = meta
        self._matrix = matrix  # (N, D)，已按行 L2 归一化

    def __len__(self) -> int:
        return len(self._meta)

    def recall(self, query: list[float], exclude_ids: set[str]) -> list[MemoryHit]:
        """余弦 top-k 召回。

        过滤规则：
          - 排除 exclude_ids（本轮正在合成的簇自身，否则会「自己参照自己」）；
          - sim >= MIN_SIM 才算同类事件；
          - sim >= MAX_SIM 视为同一事件的不同表述（不是历史参照），排除，
            避免把去重器漏掉的重复事件当成「历史规律」误导 LLM。
        """
        if not self._meta or not query:
            return []
        q = np.asarray(query, dtype=np.float32)
        if q.shape[0] != self._matrix.shape[1]:
            return []
        norm = float(np.linalg.norm(q))
        if norm == 0.0:
            return []
        sims = self._matrix @ (q / norm)

        lo, hi = settings.EVENT_MEMORY_MIN_SIM, settings.EVENT_MEMORY_MAX_SIM
        top_k = settings.EVENT_MEMORY_TOP_K
        # 先按相似度降序取候选（多取一些，给 exclude / 上界过滤留余量）
        order = np.argsort(-sims)[: top_k + len(exclude_ids) + 5]

        hits: list[MemoryHit] = []
        for idx in order:
            sim = float(sims[idx])
            if sim < lo:
                break  # 已降序，后面只会更低
            if sim >= hi:
                continue
            m = self._meta[idx]
            if m["event_id"] in exclude_ids:
                continue
            hits.append(MemoryHit(
                event_id=m["event_id"],
                title=m["title"],
                summary=m["summary"],
                status=m["status"],
                version=m["version"],
                seen_at=m["seen_at"],
                similarity=sim,
            ))
            if len(hits) >= top_k:
                break
        return hits


_LOAD_INDEX_SQL = text("""
    SELECT id, event_title, event_summary, event_status, event_version,
           COALESCE(event_first_seen_at, created_at) AS seen_at,
           event_embedding
    FROM news
    WHERE related_to_id IS NULL
      AND event_embedding IS NOT NULL
      AND event_embedding_model = :tag
      AND created_at >= :cutoff
    ORDER BY created_at DESC
    LIMIT :limit
""")


async def load_index() -> EventMemoryIndex | None:
    """加载近 EVENT_MEMORY_LOOKBACK_DAYS 天的历史事件向量索引。空索引返回 None。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.EVENT_MEMORY_LOOKBACK_DAYS)
    async with async_session() as session:
        result = await session.execute(_LOAD_INDEX_SQL, {
            "tag": embedding_tag(),
            "cutoff": cutoff,
            "limit": settings.EVENT_MEMORY_MAX_CANDIDATES,
        })
        rows = result.mappings().all()

    meta: list[dict] = []
    vectors: list[list[float]] = []
    dim = EMBEDDING_DIMENSIONS
    for r in rows:
        vec = r["event_embedding"]
        # 防御：标签一致但长度异常（历史脏数据）直接跳过，避免 np.asarray 变成 object 数组
        if not vec or len(vec) != dim:
            continue
        meta.append({
            "event_id": str(r["id"]),
            "title": r["event_title"] or "",
            "summary": r["event_summary"] or "",
            "status": r["event_status"] or "",
            "version": int(r["event_version"] or 1),
            "seen_at": r["seen_at"],
        })
        vectors.append(vec)

    if not vectors:
        return None

    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    matrix /= norms
    logger.debug("Event memory index loaded: %d events (%d-dim)", len(meta), dim)
    return EventMemoryIndex(meta, matrix)


async def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """批量向量化（失败时整批返回 None 占位，调用方按「无记忆」降级）。"""
    if not texts:
        return []
    vectors = await _call_embedding(texts)
    if not vectors or len(vectors) != len(texts):
        if vectors:
            logger.warning(
                "Event memory: embedding count mismatch (%d texts → %d vectors)",
                len(texts), len(vectors),
            )
        return [None] * len(texts)
    return list(vectors)


_PERSIST_SQL = text("""
    UPDATE news
    SET event_embedding = :vec,
        event_embedding_model = :tag
    WHERE id = :id
""").bindparams(bindparam("vec", type_=ARRAY(REAL)))


async def persist_embeddings(pairs: list[tuple[str, list[float]]]) -> int:
    """把事件包向量写回聚合根。返回成功写入条数。"""
    if not pairs:
        return 0
    tag = embedding_tag()
    rows = [{"id": eid, "vec": vec, "tag": tag} for eid, vec in pairs if vec]
    if not rows:
        return 0
    async with async_session() as session:
        for row in rows:
            await session.execute(_PERSIST_SQL, row)
        await session.commit()
    return len(rows)


def format_memory_block(hits: list[MemoryHit]) -> str:
    """把召回结果渲染成 prompt 片段。空结果返回空串（调用方不注入该段）。"""
    if not hits:
        return ""
    chars = settings.EVENT_MEMORY_SUMMARY_CHARS
    lines = [
        "【历史同类事件（仅作背景参照，不是本次报道内容）】",
    ]
    for i, h in enumerate(hits, 1):
        when = h.seen_at.strftime("%Y-%m-%d") if h.seen_at else "时间未知"
        summary = (h.summary or "").replace("\n", " ")[:chars]
        lines.append(
            f"{i}. [{when}｜{h.status or 'unknown'}｜v{h.version}] {h.title}"
            + (f"　{summary}…" if summary else "")
        )
    return "\n".join(lines)
