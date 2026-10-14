"""世界线 P3-1：线语义原型（threads.embedding）的滚动重算。

为什么需要这个模块
------------------
方向二的诊断结论（441 事件，LOO 口径，三个脚本实测）：

    实体型线（4 条）   召回 83.3%
    主题型线（25 条）  召回 57.0%     ← 差 26.3pp
    主题型漏归 84% 卡在 entity_gate

根因：实体 Jaccard 要求线内存在**稳定共现主体**。「英伟达算力」有英伟达
（线内覆盖 56%）作锚，实体特征有效；「全球长端利率与主权债供给」的 top
实体是 美国 25% / 美债 17% / 德国 17% ——根本没有锚点，Jaccard 结构性失效。

解法：给每条线算一个**语义原型向量** = 线内已挂章事件 embedding 的 L2
归一化质心，用 cos(事件向量, 原型) 排序取 Top-1。实测：

    R   纯规则        召回 57.1%  精确 58.5%  F1 0.578
    S   纯语义 Top-1  召回 76.6%  精确 76.6%  F1 0.766   ← 最优
    R+S 并集          召回 84.8%  精确 58.9%  F1 0.695
    R>S 规则优先      召回 82.3%  精确 60.8%  F1 0.699

★ 三条关键实测约束，改动前必读：

1. 只有**相对排序**有效，绝对阈值无效。
   bge-m3 的 cos 被压在 0.3~0.6 窄带，T=0.70 时 F1 仅 0.562。
   因此默认 THREAD_SEMANTIC_MIN_SIM=0（不设阈值），判定只看 rank。

2. 规则并进来是**负收益**。实体门控的误判会被并集完整继承，
   精确率掉 18pp。所以语义路独立判定，不与规则取并集。

3. 人工基线每事件恰好归 1 条线（441/441 实测），
   Top-1 口径与业务定义天然吻合，不需要多标签。

取数口径
--------
threads.embedding 字段早已存在但从未启用（上线时 0/34 全空）。
原型来源：thread_events → news.event_embedding。
★ news 表同一 event_id 有多行（实测 311 行重复 / 1159 总行），
  必须按 event_id 去重，否则长章节多的线会被重复计入、质心偏斜。

零 LLM：纯向量算术，与实体层「规范化零 LLM」的设计一致。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import text

from app.config import settings
from app.database import async_session

logger = logging.getLogger(__name__)

# 事件级 embedding 的维度（siliconflow/BAAI/bge-m3）
EMBED_DIM = 1024


async def load_event_embeddings(
    thread_id: uuid.UUID, session
) -> list[tuple[str, np.ndarray]]:
    """取线内已挂章事件的 embedding（按 event_id 去重）。

    Returns:
        [(event_id, vec_float32), ...]  向量未归一化，由调用方处理。

    ★ 去重必要性：news 表内同一 event_id 存在多行（历史写入产生的重复），
      不去重会让多章节的事件被重复计入质心。
    """
    sql = text("""
        SELECT DISTINCT ON (te.event_id)
               te.event_id::text, n.event_embedding
        FROM thread_events te
        JOIN news n
          ON n.event_id = te.event_id
         AND n.event_embedding IS NOT NULL
        WHERE te.thread_id = :tid
        ORDER BY te.event_id, n.event_last_updated_at DESC NULLS LAST
    """)
    rows = (await session.execute(sql, {"tid": thread_id})).all()

    out: list[tuple[str, np.ndarray]] = []
    for eid, emb in rows:
        if emb is None:
            continue
        v = np.asarray(emb, dtype=np.float32)
        if v.shape != (EMBED_DIM,):
            # 维度不符 = 换过 embedding 模型或脏数据，跳过而非让质心失真
            logger.warning(
                "thread %s event %s: embedding dim %s != %d, skipped",
                thread_id, eid[:8], v.shape, EMBED_DIM,
            )
            continue
        out.append((eid, v))
    return out


def mean_pooling(vectors: list[np.ndarray]) -> np.ndarray:
    """对一组向量做「先各自 L2 归一化、再取均值、最后再归一化」。

    ★ 顺序不能反：
      先归一化再平均 = 每条章节等权（长度不同的向量不会因模长主导质心）
      最后再归一化   = 质心落在单位球上，后续 cos 直接点积即可

    实测这条顺序下的 Top-1 = 76.6%；反过来（先平均后归一化）会让
    长文本事件主导质心，判别力下降。
    """
    if not vectors:
        raise ValueError("mean_pooling 需要至少一个向量")
    M = np.stack(vectors)
    M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    c = M.mean(axis=0)
    return c / (np.linalg.norm(c) + 1e-9)


async def build_prototype(thread_id: uuid.UUID, session) -> np.ndarray | None:
    """算出一条线的语义原型向量。成员不足返回 None。"""
    pairs = await load_event_embeddings(thread_id, session)
    if len(pairs) < settings.THREAD_SEMANTIC_MIN_SUPPORT:
        return None
    return mean_pooling([v for _, v in pairs])


async def refresh_thread_prototype(
    thread_id: uuid.UUID, session=None
) -> bool:
    """重算并写回 threads.embedding。

    Returns:
        True  = 写入成功（threads.embedding 已更新）
        False = 成员不足 / 无有效 embedding / 未启用——调用方不应视为错误

    session 可传入以复用外层事务；None 则自建会话（独立提交）。
    """
    if not settings.THREAD_SEMANTIC_ENABLED:
        return False

    own = session is None
    if own:
        from app.database import async_session as _sess
        ctx = _sess()
        session = await ctx.__aenter__()
    try:
        proto = await build_prototype(thread_id, session)
        if proto is None:
            return False
        await session.execute(
            text("UPDATE threads SET embedding = :e WHERE id = :tid"),
            {"e": [float(x) for x in proto], "tid": thread_id},
        )
        await session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — 兜底，绝不阻断挂章
        logger.warning("refresh prototype failed (thread=%s): %s", thread_id, exc)
        if own:
            await session.rollback()
        return False
    finally:
        if own:
            await ctx.__aexit__(None, None, None)


async def refresh_all_prototypes(batch_commit: bool = True) -> dict:
    """全量回填所有线的原型。供存量迁移与定时任务调用。

    Returns:
        {"total": 总线数, "ok": 成功数, "skip": 跳过数（成员不足/无向量）}
    """
    if not settings.THREAD_SEMANTIC_ENABLED:
        logger.warning("THREAD_SEMANTIC_ENABLED=False，跳过原型回填")
        return {"total": 0, "ok": 0, "skip": 0}

    total = ok = skip = 0
    async with async_session() as session:
        rows = (await session.execute(text(
            "SELECT id FROM threads WHERE status NOT IN ('merged','split')"
        ))).all()
        ids = [r[0] for r in rows]
        total = len(ids)

        for tid in ids:
            try:
                pairs = await load_event_embeddings(tid, session)
                if len(pairs) < settings.THREAD_SEMANTIC_MIN_SUPPORT:
                    skip += 1
                    continue
                proto = mean_pooling([v for _, v in pairs])
                await session.execute(
                    text("UPDATE threads SET embedding = :e WHERE id = :tid"),
                    {"e": [float(x) for x in proto], "tid": tid},
                )
                ok += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("backfill prototype failed (thread=%s): %s", tid, exc)
                skip += 1
            if batch_commit and ok % 20 == 0:
                await session.commit()
        await session.commit()

    logger.info("prototype backfill done: total=%d ok=%d skip=%d", total, ok, skip)
    return {"total": total, "ok": ok, "skip": skip}


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """两个向量的余弦相似度。输入应已归一化；此处再兜底一次归一化。"""
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(a @ b / (na * nb))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
