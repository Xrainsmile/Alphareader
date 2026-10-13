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
from datetime import datetime, timedelta, timezone

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
    # SEC 披露表格（文件类型，非事件主体）：8-K 当期报告、10-K 年报、10-Q 季报、S-1 招股书
    "8-K", "10-K", "10-Q", "S-1", "6-K", "20-F",
})

# ── 信源名黑名单（运行时）────────────────────────────────────
# 由 settings.ENTITY_SOURCE_BLOCKLIST（静态）与 DB 近期 news.source（动态）合并而成。
# _SOURCE_BLOCKLIST_LOADED 标记是否已加载，避免每批重复查库。
_SOURCE_BLOCKLIST: set[str] = set()
_SOURCE_BLOCKLIST_LOADED: bool = False


def _norm_key(name: str) -> str:
    """黑名单比对键：去空白、去常见媒体后缀、全小写。"""
    s = (name or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    # 剥离信源常见的频道后缀，使 "OpenAI Blog" → "openai"、"Yahoo Finance" → "yahoo"。
    # 注意：不剥离 "ai" —— 会误伤 OpenAI / xAI / DeepMind 等真实主体名。
    # 且仅在剩余部分仍是合理主体（≥3 字符）时才剥离，避免 "FT" 被剥成空。
    for suffix in ("blog", "news", "finance", "media", "press", "wire", "report"):
        if s.endswith(suffix) and len(s) - len(suffix) >= 3:
            s = s[: -len(suffix)]
            break
    return s


async def _load_source_blocklist(session: AsyncSession | None = None) -> set[str]:
    """合并静态黑名单与 DB 近期信源，返回归一化的比对键集合。

    失败时退化到纯静态表，绝不抛异常（实体属增强功能）。
    """
    global _SOURCE_BLOCKLIST, _SOURCE_BLOCKLIST_LOADED

    if _SOURCE_BLOCKLIST_LOADED:
        return _SOURCE_BLOCKLIST

    keys = {_norm_key(n) for n in settings.ENTITY_SOURCE_BLOCKLIST}
    # 豁免名单：既是信源又是真实主体的机构，不进黑名单
    allow = {_norm_key(n) for n in settings.ENTITY_SOURCE_ALLOWLIST}
    keys -= allow

    days = int(getattr(settings, "ENTITY_SOURCE_BLOCKLIST_FROM_DB_DAYS", 30) or 0)
    if days > 0:
        try:
            from app.models.news import News

            owns_session = session is None
            if owns_session:
                from app.database import async_session as _session_factory

                session = _session_factory()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                rows = (
                    await session.execute(
                        select(News.source).where(
                            News.source.isnot(None), News.created_at >= cutoff
                        ).distinct()
                    )
                ).scalars().all()
                for s in rows:
                    k = _norm_key(s)
                    if k and k not in allow:
                        keys.add(k)
            finally:
                if owns_session:
                    await session.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("source blocklist DB load failed, using static only: %s", exc)

    _SOURCE_BLOCKLIST = keys
    _SOURCE_BLOCKLIST_LOADED = True
    logger.info("Entity source blocklist loaded: %d keys", len(keys))
    return _SOURCE_BLOCKLIST


def is_source_name(name: str, blocklist: set[str] | None = None) -> bool:
    """判断实体名是否为发文媒体（信源）而非事件主体。"""
    if not name:
        return False
    keys = blocklist if blocklist is not None else _SOURCE_BLOCKLIST
    return _norm_key(name) in keys


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

# 挂载离线实体种子别名表（清洗后 806 条）。
# 必须在 ALIAS_MAP 定义之后，种子别名以线上已有规范名为准，避免老实体被架空。
try:
    from app.services.entity_aliases_seed import SEED_ALIAS_MAP

    ALIAS_MAP.update(SEED_ALIAS_MAP)
except Exception as _seed_exc:  # noqa: BLE001
    logger.warning("SEED_ALIAS_MAP not loaded: %s", _seed_exc)


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

    # 信源名过滤：发文媒体不构成事件主体，标记为 generic 以排除出归线 Jaccard。
    # 注意 allowlist 优先——OpenAI/Anthropic 这类既是信源又是真实主体的机构要保留。
    # 黑名单未加载时（_SOURCE_BLOCKLIST 空）跳过，避免误杀全部实体。
    if _SOURCE_BLOCKLIST and is_source_name(norm):
        _norm = _norm_key(norm)
        allow = {_norm_key(n) for n in settings.ENTITY_SOURCE_ALLOWLIST}
        if _norm not in allow:
            logger.debug("entity dropped as source name: %r", raw)
            return norm, True

    # 别名表：大小写不敏感
    # 命中别名后仍需判定 is_generic——种子里"美国/中国/欧洲/日本/全球/市场"
    # 是刻意保留的泛化实体，必须标 generic 才能被归线排除。
    key = norm.lower()
    if key in ALIAS_MAP:
        canonical = ALIAS_MAP[key]
        return canonical, canonical in GENERIC_ENTITIES

    if raw.lower() in ALIAS_MAP:
        canonical = ALIAS_MAP[raw.lower()]
        return canonical, canonical in GENERIC_ENTITIES

    return norm, False


async def upsert_entities(
    session: AsyncSession,
    names: list[str],
    seen_at: datetime | None = None,
    type_map: dict[str, str] | None = None,
) -> dict[str, Entity]:
    """批量 upsert 实体卡，返回 {canonical_name: Entity}。

    只增不减：mention_count 累加，last_seen_at 取最大，first_seen_at 不覆盖。
    规范名唯一（canonical_name 上有 unique 约束），用 ON CONFLICT 累加。

    Args:
        names: LLM 抽取的**原始**实体名（未规范化）
        seen_at: 提及时间
        type_map: {原始实体名: entity_type}，由调用方从 news.entity_types 聚合而来。
            未命中的实体 entity_type 为 None——规格要求"未知就是 None，不强行填"。
            已存在的实体卡**不覆盖**已有类型（首次判定优先，避免类型抖动）。
    """
    if not names:
        return {}

    # 首次调用时加载信源黑名单（静态配置 + DB 近期信源）
    await _load_source_blocklist(session)

    now = seen_at or datetime.now(timezone.utc)
    type_map = type_map or {}
    # 去重：同一批里可能有多个别名指向同一规范名。
    # 类型用原始名查（canonicalize 会改写名字），同一规范名取首个非空类型。
    canonical_map: dict[str, bool] = {}
    canonical_types: dict[str, str | None] = {}
    for n in names:
        canon, is_generic = canonicalize(n)
        if not canon:
            continue
        if canon not in canonical_map:
            canonical_map[canon] = is_generic
            canonical_types[canon] = type_map.get(n)
        elif canonical_types.get(canon) is None:
            canonical_types[canon] = type_map.get(n)

    if not canonical_map:
        return {}

    rows = [
        {
            "canonical_name": canon,
            "entity_type": canonical_types.get(canon),
            "is_generic": is_generic,
            "mention_count": 1,
            "first_seen_at": now,
            "last_seen_at": now,
            "aliases": [canon],
        }
        for canon, is_generic in canonical_map.items()
    ]

    stmt = pg_insert(Entity).values(rows)
    # 已存在的实体卡：只累加 mention_count 与 last_seen_at。
    # entity_type 不覆盖（首次判定优先，防止同一实体在多事件中类型抖动）。
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
    type_map: dict[str, str] | None = None,
) -> int:
    """建立 events ↔ entities 关联，返回成功关联条数。

    幂等：同一 (event_id, entity_id) 重复调用不会报错也不会重复插入。
    失败只记 log，不抛异常（实体是增强功能，不能阻断事件合成）。
    """
    if not names or not event_id:
        return 0

    try:
        entity_map = await upsert_entities(session, names, type_map=type_map)
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
