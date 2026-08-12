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
    # 结果记忆：让 LLM 判断"通常多久落地/是否常被证伪"时有真实结局依据
    outcome_type: str | None = None
    final_outcome: str | None = None
    watch_result: str | None = None
    resolved_at: datetime | None = None
    duration_hours: int | None = None


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
                outcome_type=m.get("outcome_type"),
                final_outcome=m.get("final_outcome"),
                watch_result=m.get("watch_result"),
                resolved_at=m.get("resolved_at"),
                duration_hours=m.get("duration_hours"),
            ))
            if len(hits) >= top_k:
                break
        return hits


# 长期方案 P4：事件记忆索引从 events 表加载（替代旧 news.event_* 列）。
# events 表仅含事件根，无需 related_to_id IS NULL 过滤。
_LOAD_INDEX_SQL = text("""
    SELECT id, title, summary, status, version,
           COALESCE(first_seen_at, created_at) AS seen_at,
           embedding,
           outcome_type, final_outcome, watch_result,
           resolved_at, duration_hours
    FROM events
    WHERE embedding IS NOT NULL
      AND embedding_model = :tag
      AND status IN :statuses
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
            "statuses": tuple(settings.EVENT_MEMORY_RECALL_STATUSES),
            "cutoff": cutoff,
            "limit": settings.EVENT_MEMORY_MAX_CANDIDATES,
        })
        rows = result.mappings().all()

    meta: list[dict] = []
    vectors: list[list[float]] = []
    dim = EMBEDDING_DIMENSIONS
    for r in rows:
        vec = r["embedding"]
        # 防御：标签一致但长度异常（历史脏数据）直接跳过，避免 np.asarray 变成 object 数组
        if not vec or len(vec) != dim:
            continue
        meta.append({
            "event_id": str(r["id"]),
            "title": r["title"] or "",
            "summary": r["summary"] or "",
            "status": r["status"] or "",
            "version": int(r["version"] or 1),
            "seen_at": r["seen_at"],
            "outcome_type": r["outcome_type"],
            "final_outcome": r["final_outcome"],
            "watch_result": r["watch_result"],
            "resolved_at": r["resolved_at"],
            "duration_hours": r["duration_hours"],
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

# 长期方案 P3：事件向量主表改为 events（与 news 双写，P4 翻 reader 后 P5 去 news 镜像）
_PERSIST_EVENT_SQL = text("""
    UPDATE events
    SET embedding = :vec,
        embedding_model = :tag
    WHERE id = :id
""").bindparams(bindparam("vec", type_=ARRAY(REAL)))


async def persist_embeddings(pairs: list[tuple[str, list[float]]]) -> int:
    """把事件包向量写回聚合根。返回成功写入条数。

    长期方案 P3 起双写 events.embedding 与 news.event_embedding（后者为 P4 翻 reader 前的过渡镜像）。
    """
    if not pairs:
        return 0
    tag = embedding_tag()
    rows = [{"id": eid, "vec": vec, "tag": tag} for eid, vec in pairs if vec]
    if not rows:
        return 0
    async with async_session() as session:
        for row in rows:
            await session.execute(_PERSIST_SQL, row)
            await session.execute(_PERSIST_EVENT_SQL, row)
        await session.commit()
    return len(rows)


_OUTCOME_LABELS = {
    "confirmed": "已确认/落地",
    "reversed": "被证伪/反转",
    "delayed": "延期",
    "cancelled": "取消/搁置",
    "unknown": "结局未记录",
}


def _format_outcome(m: MemoryHit) -> str:
    """把单条命中的结局字段渲染成一行可读文本；无信息返回空串。"""
    label = _OUTCOME_LABELS.get(m.outcome_type or "unknown", "结局未记录")
    parts = [label]
    if m.resolved_at:
        parts.append(f"结束于 {m.resolved_at.strftime('%Y-%m-%d')}")
    if m.duration_hours is not None:
        parts.append(f"持续约 {m.duration_hours}h")
    extra = []
    if m.final_outcome:
        extra.append(m.final_outcome)
    if m.watch_result:
        extra.append(f"观察点: {m.watch_result}")
    s = " | ".join(parts)
    if extra:
        s += "；" + "；".join(extra)
    return s


def summarize_pattern_evidence(hits: list[MemoryHit]) -> dict:
    """统计召回事件的结局方向，判断是否足以支撑"通常/规律"类归纳。

    仅把非 unknown 的 outcome_type 计入；当某方向出现次数 ≥ EVENT_MEMORY_MIN_PATTERN_COUNT
    时认为"方向一致、可归纳"。用于 prompt 护栏，杜绝单样本或方向分散时臆断规律。
    """
    counts: dict[str, int] = {}
    for h in hits:
        t = h.outcome_type or "unknown"
        counts[t] = counts.get(t, 0) + 1
    known = {k: v for k, v in counts.items() if k != "unknown"}
    consistent = max(known, key=known.get) if known else None
    has_pattern = bool(consistent and known[consistent] >= settings.EVENT_MEMORY_MIN_PATTERN_COUNT)
    return {
        "counts": counts,
        "consistent_outcome": consistent,
        "has_pattern": has_pattern,
    }


def format_memory_block(hits: list[MemoryHit]) -> str:
    """把召回结果渲染成 prompt 片段。空结果返回空串（调用方不注入该段）。

    渲染原则：
      - 声明这是背景参照，严禁当作新事实写进标题/摘要/变化（对齐合成 Prompt 硬约束）；
      - 展示首次出现时间、状态、版本与「结局」（outcome_type/最终结果/观察点兑现/持续时长），
        让模型判断"这类事件通常如何演进"时有真实结果依据；
      - 当结局方向不足以支撑归纳时，显式提醒"逐条引用、勿写通常"，封堵单样本臆断；
      - 摘要截断到 EVENT_MEMORY_SUMMARY_CHARS，避免污染主事件输入 token。
    """
    if not hits:
        return ""
    chars = settings.EVENT_MEMORY_SUMMARY_CHARS
    ev = summarize_pattern_evidence(hits)
    lines = [
        "【历史同类事件（仅作背景参照，不是本次报道内容）】",
    ]
    if ev["has_pattern"]:
        label = _OUTCOME_LABELS.get(ev["consistent_outcome"], ev["consistent_outcome"])
        n = ev["counts"].get(ev["consistent_outcome"], 0)
        lines.append(
            f"（已召回 {len(hits)} 个，其中 {n} 个结局「{label}」方向一致，"
            f"可据此归纳该类事件的典型走向；仍须以本次报道事实为准。）"
        )
    else:
        lines.append(
            f"（已召回 {len(hits)} 个历史同类事件，但结局方向不一致或不足 "
            f"{settings.EVENT_MEMORY_MIN_PATTERN_COUNT} 个一致，请逐条引用、勿臆断“通常/往往”规律。）"
        )
    for i, h in enumerate(hits, 1):
        when = h.seen_at.strftime("%Y-%m-%d") if h.seen_at else "时间未知"
        summary = (h.summary or "").replace("\n", " ")[:chars]
        lines.append(
            f"{i}. [{when}｜{h.status or 'unknown'}｜v{h.version}] {h.title}"
            + (f"　{summary}…" if summary else "")
        )
        outcome = _format_outcome(h)
        if outcome:
            lines.append(f"   结局: {outcome}")
    return "\n".join(lines)
