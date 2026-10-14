"""世界线 P1-c-2：线画像滚动重算（core_entities + rollup 标题 + last_event_at）。

为什么需要这个模块
------------------
P1-c 归线器只在**建线时**写一次 title / core_entities / last_event_at，之后永不更新：

  - title         = 首章事件标题（thread_router.maybe_create_thread）
  - core_entities = 首章事件的前 N 个实体
  - last_event_at = 首章事件时间（后续挂章不同步 → R 从建线时刻起一路衰减）

后果是「线越长越失真」：第 1 章是「CECO Environmental 提交 8-K」，线名就永久
叫这个，哪怕后面挂进来 50 章别家公司的 8-K。同时加权 Jaccard 的分母冻结在
首章规模，长线持续吸事件——这正是「8-K 扎堆成一条线」的直接成因。

本模块把三者改为**随章节滚动重算**：
  1. core_entities = 线内所有章节实体的并集（权重取线内最大事件权重，同量纲）
  2. title         = 多章 rollup 出的机制化命名，不再冻结首章标题
  3. last_event_at = 线内最新章节时间，让 R 反映真实活跃度

★ 关键副产物：锚点（anchor）判定。
  「至少出现在 2 个章节」的实体才算锚点。一条线若一个锚点都没有，说明它的
  章节之间本就没有共同主体——它是一条**聚合错误**的线，应当被拆分。
  这个信号是识别污染线的依据，比人工看标题可靠得多，见 audit_threads()。

零 LLM：全部走 SQL 聚合 + 受控词表，与实体层「规范化零 LLM」的设计一致。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import text

from app.config import settings
from app.database import async_session
from app.utils.mechanism_vocab import mechanism_display

logger = logging.getLogger(__name__)

# 标题上限：threads.title 是 String(200)，留 10 字符余量给拼接
MAX_TITLE_LEN = 190

# 锚点判定：实体至少出现在多少个章节里才算「线的共同主体」
ANCHOR_MIN_CHAPTERS = 2


async def _load_chapter_entities(
    thread_id: uuid.UUID, session, limit: int
) -> list[tuple[str, int, int, int]]:
    """统计线内每个实体的章节覆盖度。

    Returns:
        [(canonical_name, chapter_cnt, weight, mention_count), ...]
        按 chapter_cnt → mention_count 倒序，即「越共有的实体越靠前」。

    weight 取线内该实体的最大事件权重（1 或 THREAD_CORE_ENTITY_WEIGHT），
    与 thread_router._load_event_entities 的事件侧保持同量纲——
    两边不同量纲会让 Jaccard 的 Σmin/Σmax 失真。
    """
    sql = text("""
        SELECT e.canonical_name,
               COUNT(DISTINCT te.event_id) AS chapter_cnt,
               MAX(CASE WHEN COALESCE(ee.weight, 1) >= :core
                        THEN :core ELSE COALESCE(ee.weight, 1) END) AS w,
               MAX(COALESCE(e.mention_count, 1)) AS mention_count
        FROM thread_events te
        JOIN event_entities ee ON ee.event_id = te.event_id
        JOIN entities e ON e.id = ee.entity_id
        WHERE te.thread_id = :tid
          AND COALESCE(e.is_generic, false) = false
        GROUP BY e.canonical_name
        ORDER BY chapter_cnt DESC, mention_count DESC, e.canonical_name
        LIMIT :lim
    """)
    rows = (await session.execute(sql, {
        "tid": thread_id,
        "core": settings.THREAD_CORE_ENTITY_WEIGHT,
        "lim": limit,
    })).all()
    return [(r[0], int(r[1]), int(r[2] or 1), int(r[3] or 1)) for r in rows if r[0]]


async def _load_dominant_mechanism(
    thread_id: uuid.UUID, session
) -> str | None:
    """取线内章节机制众数（出现章节数最多的机制）。

    用众数而非首章机制：首章可能是噪声，众数才代表这条线真正在讲什么。
    """
    sql = text("""
        SELECT m.mech, COUNT(DISTINCT te.id) AS cnt
        FROM thread_events te
        JOIN events e ON e.id = te.event_id
        CROSS JOIN LATERAL unnest(COALESCE(e.mechanism_hints, '{}'::varchar(32)[])) AS m(mech)
        WHERE te.thread_id = :tid
        GROUP BY m.mech
        ORDER BY cnt DESC, m.mech
        LIMIT 1
    """)
    return (await session.execute(sql, {"tid": thread_id})).scalar()


async def _load_last_event_at(thread_id: uuid.UUID, session):
    """线内最新章节时间。用于让 recency_bonus 反映真实活跃度。"""
    sql = text("""
        SELECT MAX(COALESCE(e.last_updated_at, e.created_at))
        FROM thread_events te
        JOIN events e ON e.id = te.event_id
        WHERE te.thread_id = :tid
    """)
    return (await session.execute(sql, {"tid": thread_id})).scalar()


def compose_rollup_title(
    anchors: list[str],
    mech_key: str | None,
    chapter_count: int,
) -> str | None:
    """由锚点实体 + 主导机制拼出机制化线名。

    Args:
        anchors:       锚点实体（至少出现 ANCHOR_MIN_CHAPTERS 个章节），已按覆盖度倒序
        mech_key:      线内章节机制众数
        chapter_count: 章节数（仅用于判定，不拼进标题——否则每挂一章标题都变）

    Returns:
        新标题；**None 表示不应改动标题**（无锚点 = 这条线本身聚合错了，
        改标题只会掩盖问题，交给 audit_threads 暴露给人工/脚本处理）。
    """
    if chapter_count < settings.THREAD_MIN_CHAPTERS_FOR_ROLLUP:
        # 1 章时首章标题就是最佳命名，rollup 没有输入
        return None
    if not anchors:
        # ★ 无锚点：章节之间没有共同主体，这是聚合错误的强信号。
        #   不动标题，避免用「XX相关进展」这种假名字掩盖问题。
        return None

    mech = mechanism_display(mech_key) if mech_key else ""
    if len(anchors) >= 2:
        head = "·".join(anchors[:2])
        title = f"{head}：{mech}进展" if mech else f"{head} 相关进展"
    else:
        title = f"{anchors[0]}{mech}线" if mech else f"{anchors[0]} 相关进展"
    return title[:MAX_TITLE_LEN]


async def _refresh(
    thread_id: uuid.UUID, session, force_title: bool = False
) -> dict:
    """在给定 session 内执行重算（调用方负责提交）。"""
    row = (await session.execute(
        text("SELECT title, pinned_fields, chapter_count FROM threads WHERE id = :t"),
        {"t": thread_id},
    )).mappings().first()
    if not row:
        return {"ok": False, "reason": "thread not found"}

    stats = await _load_chapter_entities(
        thread_id, session, settings.THREAD_MAX_CORE_ENTITIES
    )
    core = {name: w for name, _cnt, w, _mc in stats}
    anchors = [name for name, cnt, _w, _mc in stats if cnt >= ANCHOR_MIN_CHAPTERS]
    mech = await _load_dominant_mechanism(thread_id, session)
    last_at = await _load_last_event_at(thread_id, session)

    chapter_count = int(row["chapter_count"] or 0)
    new_title = compose_rollup_title(anchors, mech, chapter_count)
    title_changed = False

    # 标题锁：人工改过的线不再被自动 rollup 覆盖。
    # 复用 threads.pinned_fields（模型注释即「人工锁定的字段，归线算法不得覆盖」），
    # 不新增列：新增列要过生产迁移，而 pinned_fields 已存在且语义完全对口。
    # force_title 用于人工显式请求重算（POST /profile/retitle）。
    pinned = row["pinned_fields"] or {}
    title_locked = isinstance(pinned, dict) and bool(pinned.get("title"))
    if new_title and (not title_locked or force_title) and new_title != row["title"]:
        await session.execute(
            text("UPDATE threads SET title = :ti WHERE id = :t"),
            {"t": thread_id, "ti": new_title},
        )
        title_changed = True

    await session.execute(
        text("""
            UPDATE threads
            SET core_entities = CAST(:core AS jsonb),
                last_event_at = COALESCE(:last_at, last_event_at),
                updated_at = now()
            WHERE id = :t
        """),
        {"t": thread_id, "core": _json(core), "last_at": last_at},
    )

    return {
        "ok": True,
        "thread_id": str(thread_id),
        "chapter_count": chapter_count,
        "core_entities": core,
        "anchors": anchors,
        "mechanism": mech,
        "title_changed": title_changed,
        "new_title": new_title,
        # 无锚点且已多章 → 聚合错误，交给 audit / 拆分脚本处理
        "suspicious": chapter_count >= ANCHOR_MIN_CHAPTERS and not anchors,
    }


def _json(core: dict) -> str:
    import json
    return json.dumps(core, ensure_ascii=False)


async def refresh_thread_profile(
    thread_id: uuid.UUID, session=None, force_title: bool = False
) -> dict:
    """重算单条线的画像（core_entities / title / last_event_at）。

    Args:
        session:     传入则复用外部事务（挂线 + 重算必须同一事务）。
        force_title: 忽略 title_auto 保护强制重算（人工显式请求）。

    幂等：重复执行结果一致，可安全重跑。
    """
    if session is not None:
        return await _refresh(thread_id, session, force_title)
    async with async_session() as s:
        out = await _refresh(thread_id, s, force_title)
        await s.commit()
    return out


async def refresh_all_threads(limit: int = 0) -> dict:
    """批量重算全部非终态线的画像。

    用于批量回填后统一刷新——挂章时逐条重算在 800+ 事件下过于琐碎，
    回填场景统一在末尾跑一次即可。

    Returns:
        {"total": N, "changed_title": n, "suspicious": [thread_id, ...]}
    """
    sql = text("""
        SELECT id FROM threads
        WHERE status NOT IN ('merged', 'split')
        ORDER BY chapter_count DESC, created_at
    """)
    async with async_session() as session:
        ids = (await session.execute(sql)).scalars().all()
    if limit and limit > 0:
        ids = ids[:limit]

    changed = 0
    suspicious: list[str] = []
    for tid in ids:
        try:
            out = await refresh_thread_profile(tid)
        except Exception as exc:  # noqa: BLE001 — 单线失败不阻断整体
            logger.warning("refresh failed thread=%s: %s", tid, exc)
            continue
        if out.get("title_changed"):
            changed += 1
        if out.get("suspicious"):
            suspicious.append(out["thread_id"])

    logger.info(
        "thread profile refreshed: total=%d title_changed=%d suspicious=%d",
        len(ids), changed, len(suspicious),
    )
    return {"total": len(ids), "changed_title": changed, "suspicious": suspicious}


async def audit_threads(min_chapters: int = 3, limit: int = 50) -> list[dict]:
    """列出「聚合错误」的可疑线：多章但无任何跨章共性实体。

    判据：max(某实体出现的章节数) < ANCHOR_MIN_CHAPTERS 且 章节数 >= min_chapters。
    这类线就是 8-K 扎堆那种——章节之间只靠一个泛化实体串起来，
    没有真正的共同主体，必须拆分（见 scripts/rebuild_threads.py）。

    这是方案 3「洗数据」的识别依据：先看这份清单，再决定拆哪些。
    """
    sql = text("""
        WITH st AS (
            SELECT te.thread_id, e.canonical_name,
                   COUNT(DISTINCT te.event_id) AS chapter_cnt
            FROM thread_events te
            JOIN event_entities ee ON ee.event_id = te.event_id
            JOIN entities e ON e.id = ee.entity_id
            WHERE COALESCE(e.is_generic, false) = false
            GROUP BY te.thread_id, e.canonical_name
        ), agg AS (
            SELECT thread_id, MAX(chapter_cnt) AS max_chapter_cnt
            FROM st GROUP BY thread_id
        )
        SELECT t.id, t.title, t.status, t.chapter_count,
               COALESCE(a.max_chapter_cnt, 0) AS top_entity_chapters
        FROM threads t
        LEFT JOIN agg a ON a.thread_id = t.id
        WHERE t.status NOT IN ('merged', 'split')
          AND t.chapter_count >= :min_ch
          AND COALESCE(a.max_chapter_cnt, 0) < :anchor_min
        ORDER BY t.chapter_count DESC, t.created_at
        LIMIT :lim
    """)
    async with async_session() as session:
        rows = (await session.execute(sql, {
            "min_ch": min_chapters,
            "anchor_min": ANCHOR_MIN_CHAPTERS,
            "lim": limit,
        })).mappings().all()
    return [
        {
            "thread_id": str(r["id"]),
            "title": r["title"],
            "status": r["status"],
            "chapter_count": int(r["chapter_count"] or 0),
            "top_entity_chapters": int(r["top_entity_chapters"] or 0),
        }
        for r in rows
    ]
