"""世界线 P1-c：归线打分器（S = 0.55E + 0.30M + 0.15R）。

评分只做「事件该不该挂到某条线」的判定，不负责建线、不负责写线卡。
影子模式下（THREAD_ROUTING_SHADOW=True）只算分 + 留痕，不写 thread_events。

设计要点：
1. 三步走：eligible() 硬筛选 → 打分 → 阈值判定。
   硬筛选里 is_manually_excluded 排第一，因为人工摘除过的线不能再自动归回，
   否则治理失效（人工治理是权威，算法必须服从）。
2. E 用标准加权 Jaccard（Σmin/Σmax），不用覆盖率。
   覆盖率会让长线（实体多）天然吸走所有事件，正是要防的「强行归类」。
3. is_generic 实体一律排除在 E 之外。否则两条无关的线会因为都提到
   「市场」「美国」而被判相似。
4. mechanism_hints 为空数组 → 对所有线兼容（无约束），不是 unknown，
   也不是归到某条默认线。空 = 不参与门控。
5. R 用指数衰减（半衰期 72h），天然落在 (0,1]，不需要额外的 CAP。
   活跃线滚雪球的问题由衰减本身解决。
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.config import settings
from app.database import async_session

logger = logging.getLogger(__name__)

# 不参与归线的线状态（已合并/已拆分，保留重定向指针但不再接收新事件）
_INELIGIBLE_STATUS = {"merged", "split"}


def weighted_jaccard(
    ev_entities: dict[str, int],
    thread_entities: dict[str, int],
) -> float:
    """标准加权 Jaccard：Σmin(w) / Σmax(w)。

    不用「覆盖率」Σ(交集)/Σ(事件)，因为覆盖率会让实体多的长线天然吸走
    所有事件——那正是要防的强行归类。

    Args:
        ev_entities:      {实体规范名: 权重}，来自 event_entities（已排除 is_generic）
        thread_entities:  {实体规范名: 权重}，线的 core_entities

    Returns:
        0.0 ~ 1.0。两边都为空时返回 0.0（无实体可比对，不该给分）。
    """
    if not ev_entities and not thread_entities:
        return 0.0
    keys = set(ev_entities) | set(thread_entities)
    inter = sum(min(ev_entities.get(k, 0), thread_entities.get(k, 0)) for k in keys)
    union = sum(max(ev_entities.get(k, 0), thread_entities.get(k, 0)) for k in keys)
    if union <= 0:
        return 0.0
    return inter / union


def mechanism_score(
    ev_mechanisms: list[str] | None,
    thread_mechanism: str | None,
) -> float:
    """机制匹配分 M。

    三条规则，优先级从高到低：
    1. 事件机制为空数组 / None → 1.0（无约束，对所有线兼容）
    2. 线未设机制（None 或空串）→ 0.5（中性，不惩罚也不奖励）
    3. 两者都有 → 命中 1.0，未命中 0.0

    第 1 条是关键：mechanism_hints 为空表达「未识别到机制」，
    语义是「不参与门控」，绝不等于「归到某条默认线」。
    """
    if not ev_mechanisms:
        return 1.0
    if not thread_mechanism:
        return 0.5
    return 1.0 if thread_mechanism in ev_mechanisms else 0.0


def recency_bonus(last_event_at: datetime | None, now: datetime | None = None) -> float:
    """活跃度奖励 R = 0.5 ** (hours_since / half_life)，落在 (0, 1]。

    用指数衰减而非线性，避免「刚更新」和「3 天前更新」差距过小。
    天然有上界 1.0，不需要再设 CAP——这正是你担心的活跃线滚雪球的解法：
    越久远的线奖励越低，新线不会因为没有历史而被老线压制。
    """
    if last_event_at is None:
        return 1.0  # 全新的线，给满奖励（鼓励胚胎线成长）
    now = now or datetime.now(timezone.utc)
    if last_event_at.tzinfo is None:
        last_event_at = last_event_at.replace(tzinfo=timezone.utc)
    hours = (now - last_event_at).total_seconds() / 3600.0
    if hours <= 0:
        return 1.0
    half_life = max(settings.THREAD_RECENCY_HALF_LIFE_HOURS, 1e-6)
    return 0.5 ** (hours / half_life)


def compute_score(
    ev_entities: dict[str, int],
    thread_entities: dict[str, int],
    ev_mechanisms: list[str] | None,
    thread_mechanism: str | None,
    last_event_at: datetime | None,
    now: datetime | None = None,
) -> tuple[float, float, float, float]:
    """算 S 总分。返回 (S, E, M, R)——分项一并返回，影子期调权重要靠它。

    影子模式的核心产出就是这个四元组：没有分项，7 天后无法判断
    是 E 偏高还是 M 偏低导致的误判，权重就没法调。
    """
    e = weighted_jaccard(ev_entities, thread_entities)
    m = mechanism_score(ev_mechanisms, thread_mechanism)
    r = recency_bonus(last_event_at, now)
    s = (
        settings.THREAD_SCORE_W_ENTITY * e
        + settings.THREAD_SCORE_W_MECHANISM * m
        + settings.THREAD_SCORE_W_RECENCY * r
    )
    return s, e, m, r


async def _load_event_entities(event_id: uuid.UUID) -> dict[str, int]:
    """加载事件的实体权重表，已排除 is_generic。

    核心实体（weight >= THREAD_CORE_ENTITY_WEIGHT）放大 3 倍——
    这是你公式里「核心实体 3 倍加权」的落点。
    """
    sql = text("""
        SELECT e.canonical_name, ee.weight
        FROM event_entities ee
        JOIN entities e ON e.id = ee.entity_id
        WHERE ee.event_id = :eid
          AND COALESCE(e.is_generic, false) = false
    """)
    async with async_session() as session:
        rows = (await session.execute(sql, {"eid": event_id})).all()
    core = settings.THREAD_CORE_ENTITY_WEIGHT
    out: dict[str, int] = {}
    for name, w in rows:
        if not name:
            continue
        w = int(w or 1)
        # 同一规范名可能有多条关联（不同别名归并后），取最大权重
        out[name] = max(out.get(name, 0), core if w >= core else w)
    return out


async def _load_event_mechanisms(event_id: uuid.UUID) -> list[str] | None:
    """加载事件的机制列表。

    返回 None 表示「从未抽取」（区分于空数组「明确无机制」）。
    """
    sql = text("SELECT mechanism_hints FROM events WHERE id = :eid")
    async with async_session() as session:
        val = (await session.execute(sql, {"eid": event_id})).scalar()
    return list(val) if val is not None else None


async def _load_manual_exclusions(event_id: uuid.UUID) -> set[uuid.UUID]:
    """查询该事件被人工排除过的线集合。

    只认 'remove' 且未 'restore' 的记录。restore 是 remove 的撤销操作，
    两者配对——误摘后必须能恢复，否则治理不可逆。
    """
    sql = text("""
        SELECT DISTINCT thread_id FROM thread_operations o
        WHERE o.target_type = 'event'
          AND o.target_id = :eid
          AND o.operation = 'remove'
          AND o.thread_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM thread_operations r
              WHERE r.target_type = 'event'
                AND r.target_id = o.target_id
                AND r.thread_id = o.thread_id
                AND r.operation = 'restore'
                AND r.created_at > o.created_at
          )
    """)
    async with async_session() as session:
        rows = (await session.execute(sql, {"eid": event_id})).scalars().all()
    return {r for r in rows if r is not None}


async def _load_candidate_threads() -> list[dict]:
    """加载候选线（active/dormant/embryo，按最近更新倒序）。"""
    sql = text("""
        SELECT id, title, mechanism_key, core_entities, last_event_at, status
        FROM threads
        WHERE status NOT IN ('merged', 'split')
        ORDER BY last_event_at DESC NULLS LAST
        LIMIT :lim
    """)
    async with async_session() as session:
        rows = (await session.execute(
            sql, {"lim": settings.THREAD_CANDIDATE_LIMIT}
        )).mappings().all()
    return [dict(r) for r in rows]


def _thread_entity_weights(core_entities: object) -> dict[str, int]:
    """把 threads.core_entities（JSONB）转成 {名称: 权重}。

    兼容两种存法：
    - 对象式 {"胡塞武装": 3, "曼德海峡": 1}
    - 数组式 ["胡塞武装", "曼德海峡"]（默认权重 1）
    """
    if isinstance(core_entities, dict):
        return {str(k): int(v or 1) for k, v in core_entities.items()}
    if isinstance(core_entities, list):
        return {str(x): 1 for x in core_entities}
    return {}


async def route_event(event_id: uuid.UUID) -> list[dict]:
    """给单个事件归线。返回按 S 倒序的候选列表（含分项，供影子期调参）。

    影子模式（THREAD_ROUTING_SHADOW=True）：
      - 只算分 + 写 thread_operations 留痕（operation='route'，operator='auto'）
      - 不写 thread_events、不改 threads
    非影子模式：额外把命中的线写入 thread_events。

    Returns:
        [{thread_id, title, S, E, M, R, join: bool}, ...]
    """
    if not settings.THREAD_ROUTING_ENABLED:
        return []

    ev_ents = await _load_event_entities(event_id)
    ev_mechs = await _load_event_mechanisms(event_id)
    excluded = await _load_manual_exclusions(event_id)
    threads = await _load_candidate_threads()

    now = datetime.now(timezone.utc)
    scored: list[dict] = []
    for t in threads:
        tid = t["id"]
        # ① 硬筛选第一关：人工排除优先于一切。
        #    人工治理是权威——被摘除过的线绝不能再自动归回，否则治理失效。
        if tid in excluded:
            continue
        th_ents = _thread_entity_weights(t.get("core_entities"))
        s, e, m, r = compute_score(
            ev_ents, th_ents, ev_mechs, t.get("mechanism_key"),
            t.get("last_event_at"), now,
        )
        scored.append({
            "thread_id": tid,
            "title": t.get("title"),
            "S": round(s, 4),
            "E": round(e, 4),
            "M": round(m, 4),
            "R": round(r, 4),
            "join": s >= settings.THREAD_T_JOIN,
        })

    scored.sort(key=lambda x: x["S"], reverse=True)
    top = scored[: settings.THREAD_MAX_LINES_PER_EVENT]
    hits = [x for x in top if x["join"]]

    await _record_shadow(event_id, top)
    if not settings.THREAD_ROUTING_SHADOW:
        await _apply_routes(event_id, hits)
    return top


async def _record_shadow(event_id: uuid.UUID, scored: list[dict]) -> None:
    """影子期留痕：每对 (event, thread) 的 S/E/M/R 写入 thread_route_scores。

    这是影子期唯一的产出，7 天后靠它做分布分析调权重。
    分项必须落库——只有 S 而无 E/M/R，7 天后看到"归错了"却判断不出
    是 E 偏高还是 M 偏低，权重就没法调。

    写专用影子表而非 thread_operations：后者是人工治理审计表，
    混入算法观测数据会让 /history 被噪声淹没（详见模型注释）。
    """
    if not scored:
        return
    sql = text("""
        INSERT INTO thread_route_scores
            (event_id, thread_id, score, score_entity, score_mechanism,
             score_recency, joined, threshold, shadow)
        VALUES
            (:eid, :tid, :s, :e, :m, :r, :joined, :th, :shadow)
    """)
    shadow = settings.THREAD_ROUTING_SHADOW
    async with async_session() as session:
        for item in scored:
            await session.execute(sql, {
                "eid": event_id,
                "tid": item["thread_id"],
                "s": item["S"],
                "e": item["E"],
                "m": item["M"],
                "r": item["R"],
                "joined": item["join"],
                "th": settings.THREAD_T_JOIN,
                "shadow": shadow,
            })
        await session.commit()


async def _apply_routes(event_id: uuid.UUID, hits: list[dict]) -> None:
    """非影子模式：把命中的线写入 thread_events（幂等）。

    幂等靠 uq_thread_event 唯一约束 + ON CONFLICT DO NOTHING。
    chapter_no/chapter_seq 此处先置 NULL，由章节重排任务统一分配——
    归线只负责「挂不挂」，不负责「排第几」。
    """
    if not hits:
        return
    sql = text("""
        INSERT INTO thread_events
            (thread_id, event_id, membership_role, chapter_id,
             assigned_by, match_score, snapshot_title)
        SELECT :tid, :eid, 'core', gen_random_uuid(), 'auto', :score, e.title
        FROM events e
        WHERE e.id = :eid
        ON CONFLICT (thread_id, event_id) DO NOTHING
    """)
    async with async_session() as session:
        for h in hits:
            await session.execute(sql, {
                "tid": h["thread_id"], "eid": event_id, "score": h["S"],
            })
        await session.commit()
    logger.info("routed event %s -> %d threads", event_id, len(hits))
