"""Entity writer — 世界线（World Thread）P0 实体层落库服务。

职责：把 news.entities（LLM 抽取的**未规范化**实体名）落成规范实体卡，
并建立 events ↔ entities 的带角色关联。

设计约束（必须遵守）：
1. **零新增 LLM 调用**：规范化走别名表 + 规则，不用模型。
2. **永不删除实体卡**：mention_count / last_seen_at 只增不减，这是"永久"的含义。
   event_entities 是临时关联，随事件过期 CASCADE 删除，不影响实体卡。
3. **失败不影响主流程**：实体落库是增强功能，任何异常只记 log，
   绝不阻断新闻入库或事件合成。
4. **受 ENTITY_EXTRACTION_ENABLED 控制**：关闭时本模块整体 no-op。

调用点：事件合成后（event_synthesizer）或入库后异步任务。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entity import Entity, EventEntity

import logging

logger = logging.getLogger(__name__)

# ── 泛化实体黑名单 ──────────────────────────────────────────────
# 这些词不构成可追踪实体，会把无关事件串成一条线。
# P1 聚类时 is_generic=True 的实体不参与 Jaccard 主判定。
GENERIC_ENTITIES: frozenset[str] = frozenset({
    "市场", "行业", "全球", "整体", "股市", "美股", "A股", "港股",
    "投资者", "机构", "分析师", "消息人士", "知情人士", "官方",
    "美国", "中国", "欧洲", "日本", "全球市场", "国际市场",
    "资本市场", "金融市场", "经济", "政策", "监管",
})

# ── 规则归一化 ──────────────────────────────────────────────────
# 公司后缀 / 国家后缀 / 空白与大小写
_SUFFIX_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\s*\(.*?\)\s*$"), ""),          # 尾部括号注释：苹果公司(AAPL)
    (re.compile(r"[（(].*?[)）]\s*$"), ""),        # 全角括号
    (re.compile(r"\s+"), ""),                      # 去所有空白
    (re.compile(r"(集团|控股|股份|有限公司|有限责任公司)$"), ""),
    (re.compile(r"(Inc\.?|Corp\.?|Ltd\.?|Co\.?|PLC|LLC)$", re.I), ""),
    (re.compile(r"[，,。.、；;：:！!？?]+$"), ""),   # 尾部标点
]

# 别名表：逐步积累。key 为归一化后的别名，value 为规范名。
ALIAS_MAP: dict[str, str] = {
    # 也门 / 红海
    "胡塞": "胡塞武装",
    "胡塞武": "胡塞武装",
    "青年运动": "胡塞武装",
    "安拉拥护者": "胡塞武装",
    "houthi": "胡塞武装",
    "houthis": "胡塞武装",
    # 海峡
    "曼德海峽": "曼德海峡",
    "bab-el-mandeb": "曼德海峡",
    # 公司
    "苹果": "苹果公司",
    "apple": "苹果公司",
    "阿美": "沙特阿美",
    "aramco": "沙特阿美",
    "saudiaramco": "沙特阿美",
    "台积电": "台积电",
    "tsmc": "台积电",
    # 能源
    "布伦特": "布伦特原油",
    "brent": "布伦特原油",
    "wti": "WTI原油",
}


def _normalize(name: str) -> str:
    """规则归一化：去空白、去公司后缀、去尾部括号与标点。

    不做语义归并（那是 ALIAS_MAP 的职责）。纯字符串变换，零 LLM。
    """
    s = (name or "").strip()
    if not s:
        return ""
    for pattern, repl in _SUFFIX_PATTERNS:
        s = pattern.sub(repl, s).strip()
    return s


def canonicalize(name: str) -> tuple[str, bool]:
    """把 LLM 抽取的原始实体名映射到规范名。

    两步，均零 LLM：
    1. 规则归一化（去后缀/空白/括号）
    2. 别名表精确匹配（大小写不敏感）

    Returns:
        (canonical_name, is_generic)
    """
    raw = (name or "").strip()
    if not raw:
        return "", True

    if raw in GENERIC_ENTITIES:
        return raw, True

    norm = _normalize(raw)
    if not norm:
        return "", True

    # 归一化后再次判定泛化（"美国公司" → "美国"）
    if norm in GENERIC_ENTITIES:
        return norm, True

    # 别名表：大小写不敏感
    key = norm.lower()
    if key in ALIAS_MAP:
        return ALIAS_MAP[key], False

    if raw.lower() in ALIAS_MAP:
        return ALIAS_MAP[raw.lower()], False

    return norm, False


async def upsert_entities(
    session: AsyncSession,
    names: list[str],
    seen_at: datetime | None = None,
) -> dict[str, Entity]:
    """批量 upsert 实体卡，返回 {canonical_name: Entity}。

    只增不减：mention_count 累加，last_seen_at 取最大，first_seen_at 不覆盖。
    规范名唯一（canonical_name 上有 unique 约束），用 ON CONFLICT 累加。
    """
    if not names:
        return {}

    now = seen_at or datetime.now(timezone.utc)
    # 去重：同一批里可能有多个别名指向同一规范名
    canonical_map: dict[str, bool] = {}
    for n in names:
        canon, is_generic = canonicalize(n)
        if not canon:
            continue
        canonical_map[canon] = is_generic

    if not canonical_map:
        return {}

    rows = [
        {
            "canonical_name": canon,
            "is_generic": is_generic,
            "mention_count": 1,
            "first_seen_at": now,
            "last_seen_at": now,
            "aliases": [canon],
        }
        for canon, is_generic in canonical_map.items()
    ]

    stmt = pg_insert(Entity).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["canonical_name"],
        set_={
            "mention_count": Entity.__table__.c.mention_count + 1,
            "last_seen_at": now,
        },
    )
    await session.execute(stmt)

    # 回读拿到 id（含新插入的）
    result = await session.execute(
        select(Entity).where(Entity.canonical_name.in_(list(canonical_map)))
    )
    return {e.canonical_name: e for e in result.scalars().all()}


async def link_event_entities(
    session: AsyncSession,
    event_id: str,
    names: list[str],
    default_weight: int = 1,
) -> int:
    """建立 events ↔ entities 关联，返回成功关联条数。

    幂等：同一 (event_id, entity_id) 重复调用不会报错也不会重复插入。
    失败只记 log，不抛异常（实体是增强功能，不能阻断事件合成）。
    """
    if not names or not event_id:
        return 0

    try:
        entity_map = await upsert_entities(session, names)
        if not entity_map:
            return 0

        now = datetime.now(timezone.utc)
        rows = [
            {
                "event_id": event_id,
                "entity_id": ent.id,
                "weight": default_weight,
                "created_at": now,
            }
            for ent in entity_map.values()
        ]

        stmt = pg_insert(EventEntity).values(rows)
        # 同一事件+实体已存在则跳过（weight 不覆盖，保持首次判定）
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["event_id", "entity_id"],
        )
        await session.execute(stmt)
        return len(rows)

    except Exception as exc:  # noqa: BLE001 — 兜底，绝不阻断主流程
        logger.warning(
            "link_event_entities failed (event_id=%s): %s", event_id, exc,
            exc_info=False,
        )
        return 0


def enabled() -> bool:
    """实体抽取总开关。关闭时调用方应整体跳过本模块。"""
    return bool(getattr(settings, "ENTITY_EXTRACTION_ENABLED", True))
