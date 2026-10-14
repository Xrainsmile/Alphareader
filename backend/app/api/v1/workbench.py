"""世界线工作台 API — 面向「世界线工作台」前端的只读聚合层。

★ 与 threads.py（治理 API）的职责边界：

  threads.py      治理向：人工 pin / merge / split / remove，写操作留痕
  workbench.py    消费向：列表、雷达、实体监控、传导链、简报关联，纯只读

  两文件都读同一批表，但绝不互相调用——治理 API 的写语义会污染
  工作台的读语义（反之亦然）。重复一段 SQL 好过两个语义互相纠缠。

★ 三条贯穿全文件的数据现实（2026-10-13 实测生产库 303 线 / 832 章）：

  1. chapter_no / chapter_seq 已被回填（2026-10-14 实测 441/441 非空，
     此前文档记的「全 NULL」已过时）。章节排序**统一以 chapter_no 为准**，
     last_updated_at 只作回退——两者曾分叉，导致工作台与管理台章号对不上。
     ★ 2026-10-14 定：章节时间轴统一**倒序**（最新在前），与简报口径一致。
     ★ 本文件与 threads.py 的章节 ORDER BY 必须逐字保持一致，否则分叉复发。
  2. occurred_at 亦已回填（441/441 非空）。时间基准取它，回退 last_updated_at。
  3. thread_transmissions 为 0 条：传导链尚未生成，属「功能未启用」
     而非「数据为空」。前端必须区分这两种状态，不能一律显示空卡片。

  本文件不修数据，只如实反映并回退。修数据归 backfill 脚本，
  两件事分开做——API 层的隐式修补会让前端永远发现不了底层缺陷。

端点（8）：
  世界线追踪 2： list / detail(含章节+传导链+简报)
  异动雷达   1： radar（7/30/90 天）
  实体监控   2： entities / entity detail
  简报集成   2： digest link / thread digests
  元信息     1： meta（状态枚举与数据健康度）
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workbench", tags=["worldline-workbench"])

# 雷达窗口（天）→ 展示标签。90 天为上限：events 保留期 90 天
# （EVENT_MEMORY_LOOKBACK_DAYS=90），再宽的窗口只会命中同一批数据。
RADAR_WINDOWS = {7: "7 天", 30: "30 天", 90: "90 天"}

# 章节作用角色 → 中文标签。与 threads.py 的 MEMBERSHIP_ROLES 保持一致，
# 不共享常量：治理 API 改枚举不应连带改文案，反之亦然。
ROLE_LABELS = {
    "core": "核心进展",
    "trigger": "触发因素",
    "reaction": "应对反制",
    "signal": "指标变化",
    "context": "背景存档",
    "noise": "已排除",
}

# 传导链证据状态 → 中文标签
EVIDENCE_LABELS = {
    "hypothesis": "待验证",
    "supported": "已证实",
    "contradicted": "已反驳",
}

# 线状态 → 中文标签
STATUS_LABELS = {
    "embryo": "萌芽",
    "active": "进行中",
    "dormant": "休眠",
    "resolved": "已收束",
    "merged": "已合并",
    "split": "已拆分",
}


# ═══════════════════ 内部工具 ═══════════════════

def _window_days(days: int) -> int:
    """校验雷达窗口。非法值回退 30 而非 400。

    为什么不用 400：窗口是筛选维度不是输入错误，前端下拉已约束取值。
    传 15 天这种「设计外但合理」的值，回退到 30 比报错更符合使用预期。
    只有完全无法解释的值（负数/超上限）才需要拒绝。
    """
    if days in RADAR_WINDOWS:
        return days
    if days <= 0:
        raise HTTPException(400, f"invalid window_days: {days}")
    return 30 if days <= 30 else 90


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _json_list(v):
    """core_entities 可能是 dict（{"实体": 权重}）或 list，统一成 list[str]。"""
    if not v:
        return []
    if isinstance(v, dict):
        return list(v.keys())
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    return []


async def _chapter_rows(thread_id: uuid.UUID, db: AsyncSession, limit: int = 200) -> list[dict]:
    """取一条线的全部章节，按**倒序**呈现（最新章节排最前）。

    ★ 排序方向（2026-10-14 定）：时间轴纵向呈现走倒序，越近的章节越靠前——
      用户进线要看的是「现在走到哪了」，不是从第一章考古。
      这与 news_digests / history_digests 的倒序口径一致。

    ★ 排序键统一为 chapter_no（2026-10-14 二次修订）：
      初版按 events.last_updated_at 排，实测与治理端 threads.py 分叉——
      同线同章节两个页面给出不同章号（10+ 条线，最多 19 章错位）。
      根因：last_updated_at 只精确到日，同一天多条事件时间并列，
      chapter_no 当初分配时用了另一套次序。
      分叉的后果是「在管理台按章号摘章，摘到的不是工作台看到那条」，
      属误操作风险，故统一以 chapter_no 为权威展示序号。

      三级回退（与治理端 list_chapters 完全一致）：
        1) chapter_no DESC   —— 权威展示序号，当前 441/441 非空
        2) e.last_updated_at DESC —— chapter_no 为 NULL 时回退
        3) te.created_at DESC     —— 兜底，保证同值顺序稳定可复现
      三者顺序必须与 threads.py 保持一致，否则分叉会复发。

    ★ display_no 直接用 chapter_no：
      此前由查询顺序反推，是 chapter_no 全 NULL 时期的权宜之计。
      现在 chapter_no 已回填，反推值会与治理端打架，故改为直取。
      chapter_no 仍为 NULL 时（未来新写入且未重排）才回退到反推。

    ★ occurred_at 用 COALESCE 兜底到事件时间，确保前端永远有可用时间戳。

    ★ limit 语义：截的是**最新** 200 章，不是最早 200 章。
    """
    rows = (await db.execute(text("""
        SELECT te.chapter_id, te.event_id, te.role, te.match_score,
               te.chapter_no,
               COALESCE(te.snapshot_title, e.title) AS title,
               COALESCE(te.snapshot_summary, e.summary) AS summary,
               COALESCE(te.occurred_at, e.last_updated_at) AS occurred_at,
               e.status AS event_status, e.impact, e.novelty, e.urgency,
               e.confidence, e.relevance, e.why_important, e.latest_change,
               e.mechanism_hints, e.contested_assets
        FROM thread_events te
        LEFT JOIN events e ON e.id = te.event_id
        WHERE te.thread_id = :t
          AND COALESCE(te.role, 'core') <> 'noise'
        ORDER BY te.chapter_no DESC NULLS LAST,
                 e.last_updated_at DESC NULLS LAST,
                 te.created_at DESC
        LIMIT :lim
    """), {"t": thread_id, "lim": limit})).mappings().all()

    total = len(rows)
    out = []
    for i, r in enumerate(rows, start=1):
        d = dict(r)
        d["chapter_id"] = str(r["chapter_id"])
        d["event_id"] = str(r["event_id"])
        # 权威章号优先；chapter_no 缺失时按倒序位置反推（最早章 = #1）
        d["display_no"] = r["chapter_no"] if r["chapter_no"] is not None else total - i + 1
        d["no_is_fallback"] = r["chapter_no"] is None
        d["role_label"] = ROLE_LABELS.get(r["role"] or "core", r["role"] or "core")
        out.append(d)
    return out


async def _transmission_rows(thread_id: uuid.UUID, db: AsyncSession) -> list[dict]:
    """取一条线的传导链，并解析两端章节标题。

    ★ 章节标题靠 chapter_id 反查 thread_events，不靠事件外键：
      传导边引用的是章节身份，章节可能跨线迁移，只有 chapter_id 稳定。

    ★ 当前 thread_transmissions 为 0 条。返回空列表时调用方需自行判断
      是「未生成」还是「无数据」——本函数不编造占位数据。
    """
    rows = (await db.execute(text("""
        SELECT tr.id, tr.from_chapter_id, tr.to_chapter_id, tr.mechanism,
               tr.evidence_status, tr.evidence_note, tr.strength,
               tr.created_at, tr.status_changed_at, tr.arbitrated_by,
               tef.event_id AS from_event_id, tet.event_id AS to_event_id,
               COALESCE(tef.snapshot_title, ef.title) AS from_title,
               COALESCE(tet.snapshot_title, et.title) AS to_title
        FROM thread_transmissions tr
        LEFT JOIN thread_events tef ON tef.chapter_id = tr.from_chapter_id
        LEFT JOIN events ef ON ef.id = tef.event_id
        LEFT JOIN thread_events tet ON tet.chapter_id = tr.to_chapter_id
        LEFT JOIN events et ON et.id = tet.event_id
        WHERE tr.thread_id = :t
        ORDER BY tr.strength DESC NULLS LAST, tr.created_at DESC
    """), {"t": thread_id})).mappings().all()

    out = []
    for r in rows:
        d = dict(r)
        d["id"] = str(r["id"])
        d["from_chapter_id"] = str(r["from_chapter_id"])
        d["to_chapter_id"] = str(r["to_chapter_id"])
        d["evidence_label"] = EVIDENCE_LABELS.get(
            r["evidence_status"], r["evidence_status"]
        )
        d["from_event_id"] = str(r["from_event_id"]) if r["from_event_id"] else None
        d["to_event_id"] = str(r["to_event_id"]) if r["to_event_id"] else None
        out.append(d)
    return out


# ═══════════════════ 元信息 ═══════════════════

@router.get("/meta")
async def workbench_meta(db: AsyncSession = Depends(get_db)):
    """工作台元信息：枚举文案映射 + 数据健康度。

    ★ 为什么要单独一个端点：前端需要知道「传导链到底有没有启用」。
      若只返回空列表，前端无法区分「功能未启用」与「这条线恰好没有」，
      只能一律显示空态——那是错的：未启用应提示「尚未生成」，
      恰好没有应提示「暂无传导链」。两者对用户的意义完全不同。
    """
    cnt = (await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM threads) AS threads,
            (SELECT COUNT(*) FROM thread_events) AS chapters,
            (SELECT COUNT(*) FROM thread_transmissions) AS transmissions,
            (SELECT COUNT(*) FROM thread_watchpoints) AS watchpoints,
            (SELECT COUNT(*) FROM entities) AS entities,
            (SELECT COUNT(*) FROM event_entities) AS event_entities,
            (SELECT COUNT(*) FROM digest_event_links) AS digest_links,
            (SELECT COUNT(*) FROM thread_events WHERE occurred_at IS NOT NULL) AS chapters_with_time
    """))).mappings().first()
    c = dict(cnt)
    return {
        "role_labels": ROLE_LABELS,
        "evidence_labels": EVIDENCE_LABELS,
        "status_labels": STATUS_LABELS,
        "radar_windows": [{"days": k, "label": v} for k, v in RADAR_WINDOWS.items()],
        "data_health": {
            **c,
            # 章节序号缺失率：用于前端提示「时间轴按事件时间排序」
            "chapter_order_ready": c["chapters_with_time"] > 0,
            "transmission_enabled": c["transmissions"] > 0,
            "watchpoint_enabled": c["watchpoints"] > 0,
        },
    }


# ═══════════════════ 世界线连续追踪 ═══════════════════

@router.get("/threads")
async def list_workbench_threads(
    status: str | None = Query(None),
    q: str | None = Query(None, description="标题/标的/核心实体模糊搜索"),
    min_chapters: int = Query(1, ge=1, description="最少章节数，过滤单章孤岛"),
    sort: str = Query("recent", description="recent | chapters | heat"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """工作台世界线列表。

    ★ 与 threads.py 的 list_threads 差异：
      - 默认过滤单章线（min_chapters=1 可关）：303 线里 136 条是单章孤岛，
        对「连续追踪」没有意义，展示出来只会稀释真正的多章线。
      - 支持按热度排序（heat）：结合章节数与最近活跃度。
      - 返回 core_entities 与前 3 章预览，供列表直接展示「最新章节」。
    """
    where = ["t.chapter_count >= :mc"]
    params = {"mc": min_chapters, "lim": limit, "off": offset}
    if status:
        where.append("t.status = :st"); params["st"] = status
    if q:
        where.append("(t.title ILIKE :q OR t.contested_asset ILIKE :q "
                     "OR t.core_entities::text ILIKE :q)")
        params["q"] = f"%{q}%"

    order = {
        "chapters": "t.chapter_count DESC, t.last_event_at DESC NULLS LAST",
        "heat": "(t.chapter_count * 2 + COALESCE("
                "EXTRACT(EPOCH FROM (now() - t.last_event_at)) / 86400 < 7)::int * 5"
                ") DESC, t.last_event_at DESC NULLS LAST",
    }.get(sort, "COALESCE(t.last_event_at, t.updated_at) DESC NULLS LAST")

    rows = (await db.execute(text(f"""
        SELECT t.id, t.title, t.contested_asset, t.mechanism_key, t.status,
               t.chapter_count, t.core_entities, t.last_event_at, t.updated_at,
               t.pinned,
               (SELECT COUNT(*) FROM thread_transmissions tr WHERE tr.thread_id = t.id)
                   AS transmission_count
        FROM threads t
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT :lim OFFSET :off
    """), params)).mappings().all()

    # 总数：同样过滤条件，不含分页
    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM threads t WHERE {' AND '.join(where)}"), params
    )).scalar()

    items = []
    tid_list = [r["id"] for r in rows]
    # 批量取每条线最近 3 章，避免 N+1
    preview_map: dict[str, list[dict]] = {}
    if tid_list:
        pv = (await db.execute(text("""
            SELECT DISTINCT ON (te.thread_id, te.event_id)
                   te.thread_id, te.event_id, te.chapter_no,
                   COALESCE(te.snapshot_title, e.title) AS title,
                   COALESCE(te.occurred_at, e.last_updated_at) AS occurred_at
            FROM thread_events te
            LEFT JOIN events e ON e.id = te.event_id
            WHERE te.thread_id = ANY(:tids)
              AND COALESCE(te.role,'core') <> 'noise'
            ORDER BY te.thread_id, te.event_id, te.chapter_no DESC NULLS LAST
        """), {"tids": tid_list})).mappings().all()
        for r in pv:
            k = str(r["thread_id"])
            preview_map.setdefault(k, []).append({
                "event_id": str(r["event_id"]),
                "title": r["title"],
                "occurred_at": r["occurred_at"],
                "chapter_no": r["chapter_no"],
            })
        # 每条线只留最近 3 章。排序键与 _chapter_rows 一致（chapter_no 优先）：
        #   列表预览与详情时间轴若不同源，会出现「列表说最新是 A，进去看到 B」。
        for k in preview_map:
            preview_map[k] = sorted(
                preview_map[k],
                key=lambda x: (
                    x["chapter_no"] if x["chapter_no"] is not None else -1,
                    x["occurred_at"] or datetime.min.replace(tzinfo=timezone.utc),
                ),
                reverse=True,
            )[:3]

    for r in rows:
        tid = str(r["id"])
        items.append({
            "id": tid,
            "title": r["title"],
            "contested_asset": r["contested_asset"],
            "mechanism_key": r["mechanism_key"],
            "status": r["status"],
            "status_label": STATUS_LABELS.get(r["status"], r["status"]),
            "chapter_count": r["chapter_count"] or 0,
            "core_entities": _json_list(r["core_entities"])[:8],
            "last_event_at": r["last_event_at"],
            "pinned": bool(r["pinned"]),
            "transmission_count": r["transmission_count"] or 0,
            "latest_chapters": preview_map.get(tid, []),
        })

    return {"total": total, "items": items}


@router.get("/threads/{thread_id}")
async def get_workbench_thread(
    thread_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    """世界线详情：主卡 + 章节时间轴 + 传导链 + 关联简报。

    ★ history_digests 是「收录过本章节的简报」，用于工作台跳回简报。
      关联路径：thread_events.event_id → digest_event_links.event_id。
      简报本身按生成时快照存储（news_digests.structured_content），
      故跳回看到的是当时的判断，不是现在的——这正是需求要的「事实快照」。
    """
    t = (await db.execute(text("""
        SELECT id, title, contested_asset, mechanism_key, status, pinned,
               core_entities, chapter_count, last_event_at, created_at, updated_at
        FROM threads WHERE id = :t
    """), {"t": thread_id})).mappings().first()
    if not t:
        raise HTTPException(404, f"thread {thread_id} not found")

    chapters = await _chapter_rows(thread_id, db)
    transmissions = await _transmission_rows(thread_id, db)

    # 关联简报：按章节事件反查，去重后按简报日期倒序
    digests = (await db.execute(text("""
        SELECT d.id, d.digest_date, d.period_label,
               COUNT(DISTINCT l.event_id) AS linked_events,
               MIN(l.section) AS sample_section
        FROM thread_events te
        JOIN digest_event_links l ON l.event_id = te.event_id
        JOIN news_digests d ON d.id = l.digest_id
        WHERE te.thread_id = :t
        GROUP BY d.id, d.digest_date, d.period_label
        ORDER BY d.digest_date DESC
        LIMIT 20
    """), {"t": thread_id})).mappings().all()

    ch_event_ids = [c["event_id"] for c in chapters]
    entity_rows = []
    if ch_event_ids:
        entity_rows = (await db.execute(text("""
            SELECT e.id, e.canonical_name, e.entity_type, e.mention_count,
                   COUNT(*) AS mentions_in_thread
            FROM event_entities ee
            JOIN entities e ON e.id = ee.entity_id
            WHERE ee.event_id = ANY(:eids)
              AND COALESCE(e.is_generic, false) = false
            GROUP BY e.id, e.canonical_name, e.entity_type, e.mention_count
            ORDER BY mentions_in_thread DESC, e.mention_count DESC
            LIMIT 12
        """), {"eids": ch_event_ids})).mappings().all()

    return {
        "id": str(t["id"]),
        "title": t["title"],
        "contested_asset": t["contested_asset"],
        "mechanism_key": t["mechanism_key"],
        "status": t["status"],
        "status_label": STATUS_LABELS.get(t["status"], t["status"]),
        "pinned": bool(t["pinned"]),
        "core_entities": _json_list(t["core_entities"]),
        "chapter_count": t["chapter_count"] or 0,
        "last_event_at": t["last_event_at"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        # 真实章节数取自关联表，冗余字段 chapter_count 可能漂移
        "real_chapter_count": len(chapters),
        "chapters": chapters,
        "transmissions": transmissions,
        "transmission_ready": len(transmissions) > 0,
        "related_entities": [
            {
                "id": str(r["id"]),
                "name": r["canonical_name"],
                "entity_type": r["entity_type"],
                "mention_count": r["mention_count"] or 0,
                "mentions_in_thread": r["mentions_in_thread"],
            }
            for r in entity_rows
        ],
        "history_digests": [
            {
                "id": r["id"],
                "digest_date": r["digest_date"],
                "period_label": r["period_label"],
                "linked_events": r["linked_events"],
                "sample_section": r["sample_section"],
            }
            for r in digests
        ],
    }


# ═══════════════════ 世界线异动雷达 ═══════════════════

@router.get("/radar")
async def thread_radar(
    window_days: int = Query(30, description="7 | 30 | 90"),
    min_chapters: int = Query(2, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """异动雷达：按窗口内的「事件变化量 × 质量信号」排序世界线。

    ★ 评分为什么不只用事件数：
      只看新增章节数会让「每天灌一条的低质线」长期霸榜。
      质量信号取该线窗口内事件的 impact/novelty/urgency 均值，
      与事件量相乘——高冲击的少量变化 > 低冲击的大量噪声。

    ★ window_days 用 events.last_updated_at 过滤而非 occurred_at：
      后者全 NULL（见模块 docstring）。这是回退不是设计，
      字段补齐后应切回 occurred_at 并在 CHANGELOG 注明。

    ★ 未归线事件不计入雷达：雷达的对象是「世界线的异动」，
      散落事件由简报页承载，两者不混——混了会出现「线没动但雷达在跳」。
    """
    wd = _window_days(window_days)
    since = _since(wd)

    rows = (await db.execute(text("""
        SELECT t.id, t.title, t.mechanism_key, t.status, t.chapter_count,
               t.core_entities, t.last_event_at,
               COUNT(te.id) AS window_events,
               COALESCE(AVG(e.impact), 0) AS avg_impact,
               COALESCE(AVG(e.novelty), 0) AS avg_novelty,
               COALESCE(AVG(e.urgency), 0) AS avg_urgency,
               COALESCE(AVG(e.confidence), 0) AS avg_confidence,
               MAX(e.last_updated_at) AS latest_at
        FROM threads t
        JOIN thread_events te ON te.thread_id = t.id
        JOIN events e ON e.id = te.event_id
        WHERE e.last_updated_at >= :since
          AND COALESCE(te.role, 'core') <> 'noise'
        GROUP BY t.id, t.title, t.mechanism_key, t.status, t.chapter_count,
                 t.core_entities, t.last_event_at
        HAVING COUNT(te.id) >= :mc
        ORDER BY (COUNT(te.id) * (1 + COALESCE(AVG(e.impact), 0) / 10.0
                                    + COALESCE(AVG(e.novelty), 0) / 10.0)) DESC,
                 MAX(e.last_updated_at) DESC
        LIMIT :lim
    """), {"since": since, "mc": min_chapters, "lim": limit})).mappings().all()

    items = []
    for i, r in enumerate(rows, start=1):
        # 质量信号归一到 0~10，便于前端画条
        quality = round(
            (float(r["avg_impact"]) + float(r["avg_novelty"])
             + float(r["avg_urgency"])) / 3.0, 2
        )
        items.append({
            "rank": i,
            "id": str(r["id"]),
            "title": r["title"],
            "mechanism_key": r["mechanism_key"],
            "status": r["status"],
            "status_label": STATUS_LABELS.get(r["status"], r["status"]),
            "chapter_count": r["chapter_count"] or 0,
            "core_entities": _json_list(r["core_entities"])[:6],
            "window_events": r["window_events"],
            "quality_score": quality,
            "avg_impact": round(float(r["avg_impact"]), 2),
            "avg_novelty": round(float(r["avg_novelty"]), 2),
            "avg_urgency": round(float(r["avg_urgency"]), 2),
            "avg_confidence": round(float(r["avg_confidence"]), 2),
            "latest_at": r["latest_at"],
        })

    return {
        "window_days": wd,
        "window_label": RADAR_WINDOWS.get(wd, f"{wd} 天"),
        "since": since,
        "total": len(items),
        "items": items,
    }


# ═══════════════════ 关键实体监控 ═══════════════════

@router.get("/entities")
async def list_monitored_entities(
    q: str | None = Query(None),
    entity_type: str | None = Query(None),
    min_mentions: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """关键实体列表：按提及热度排序，附带关联世界线数。

    ★ 排除 is_generic：泛化实体（「市场」「美国」）提及数最高但无监控价值，
      不排除会占满前排——这是实体层清洗的核心结论。
    """
    where = ["COALESCE(e.is_generic, false) = false"]
    params = {"lim": limit, "off": offset, "mm": min_mentions}
    if q:
        where.append("e.canonical_name ILIKE :q"); params["q"] = f"%{q}%"
    if entity_type:
        where.append("e.entity_type = :et"); params["et"] = entity_type

    rows = (await db.execute(text(f"""
        SELECT e.id, e.canonical_name, e.entity_type, e.mention_count,
               e.last_seen_at,
               COUNT(DISTINCT ee.event_id) AS event_count,
               COUNT(DISTINCT te.thread_id) AS thread_count
        FROM entities e
        LEFT JOIN event_entities ee ON ee.entity_id = e.id
        LEFT JOIN thread_events te ON te.event_id = ee.event_id
        WHERE {' AND '.join(where)}
        GROUP BY e.id, e.canonical_name, e.entity_type, e.mention_count, e.last_seen_at
        HAVING COUNT(DISTINCT ee.event_id) >= :mm
        ORDER BY COUNT(DISTINCT ee.event_id) DESC, e.mention_count DESC
        LIMIT :lim OFFSET :off
    """), params)).mappings().all()

    total = (await db.execute(text(f"""
        SELECT COUNT(*) FROM (
            SELECT e.id FROM entities e
            LEFT JOIN event_entities ee ON ee.entity_id = e.id
            WHERE {' AND '.join(where)}
            GROUP BY e.id
            HAVING COUNT(DISTINCT ee.event_id) >= :mm
        ) x
    """), params)).scalar()

    return {
        "total": total,
        "items": [
            {
                "id": str(r["id"]),
                "name": r["canonical_name"],
                "entity_type": r["entity_type"],
                "mention_count": r["mention_count"] or 0,
                "event_count": r["event_count"] or 0,
                "thread_count": r["thread_count"] or 0,
                "last_seen_at": r["last_seen_at"],
            }
            for r in rows
        ],
    }


@router.get("/entities/{entity_id}")
async def get_entity_monitor(
    entity_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    """实体详情：角色、提及趋势、关联世界线。

    ★ 提及趋势按天聚合，只取有提及的日期（不补零）：
      补零会让「连续 30 天无提及」与「30 天前提过一次」看起来一样，
      前者才是真正的冷却信号。缺失即无提及，前端按稀疏点渲染。
    """
    e = (await db.execute(text("""
        SELECT id, canonical_name, entity_type, aliases, mention_count,
               is_generic, first_seen_at, last_seen_at
        FROM entities WHERE id = :i
    """), {"i": entity_id})).mappings().first()
    if not e:
        raise HTTPException(404, f"entity {entity_id} not found")

    # 角色分布：该实体在事件中扮演的角色（event_entities.role）
    roles = (await db.execute(text("""
        SELECT COALESCE(NULLIF(ee.role,''), 'unspecified') AS role,
               COUNT(*) AS cnt
        FROM event_entities ee
        WHERE ee.entity_id = :i
        GROUP BY 1 ORDER BY cnt DESC
    """), {"i": entity_id})).mappings().all()

    # 提及趋势：按事件更新时间的天聚合
    trend = (await db.execute(text("""
        SELECT date_trunc('day', ev.last_updated_at) AS d,
               COUNT(DISTINCT ee.event_id) AS cnt
        FROM event_entities ee
        JOIN events ev ON ev.id = ee.event_id
        WHERE ee.entity_id = :i
        GROUP BY 1 ORDER BY 1 ASC
    """), {"i": entity_id})).mappings().all()

    # 关联世界线
    threads = (await db.execute(text("""
        SELECT t.id, t.title, t.status, t.chapter_count,
               COUNT(DISTINCT te.event_id) AS events_in_thread
        FROM thread_events te
        JOIN threads t ON t.id = te.thread_id
        WHERE te.event_id IN (
            SELECT ee.event_id FROM event_entities ee WHERE ee.entity_id = :i
        )
        GROUP BY t.id, t.title, t.status, t.chapter_count
        ORDER BY events_in_thread DESC, t.chapter_count DESC
        LIMIT 20
    """), {"i": entity_id})).mappings().all()

    recent_events = (await db.execute(text("""
        SELECT ev.id, ev.title, ev.status, ev.impact, ev.last_updated_at
        FROM event_entities ee
        JOIN events ev ON ev.id = ee.event_id
        WHERE ee.entity_id = :i
        ORDER BY ev.last_updated_at DESC
        LIMIT 20
    """), {"i": entity_id})).mappings().all()

    return {
        "id": str(e["id"]),
        "name": e["canonical_name"],
        "entity_type": e["entity_type"],
        "aliases": list(e["aliases"] or []),
        "mention_count": e["mention_count"] or 0,
        "is_generic": bool(e["is_generic"]),
        "first_seen_at": e["first_seen_at"],
        "last_seen_at": e["last_seen_at"],
        "roles": [{"role": r["role"], "count": r["cnt"]} for r in roles],
        "trend": [
            {"date": r["d"].strftime("%Y-%m-%d"), "count": r["cnt"]}
            for r in trend
        ],
        "threads": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "status": r["status"],
                "status_label": STATUS_LABELS.get(r["status"], r["status"]),
                "chapter_count": r["chapter_count"] or 0,
                "events_in_thread": r["events_in_thread"],
            }
            for r in threads
        ],
        "recent_events": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "status": r["status"],
                "impact": r["impact"],
                "last_updated_at": r["last_updated_at"],
            }
            for r in recent_events
        ],
    }


# ═══════════════════ 简报集成 ═══════════════════

@router.get("/digests/{digest_id}/thread-links")
async def digest_thread_links(
    digest_id: int, db: AsyncSession = Depends(get_db)
):
    """简报 → 世界线：返回该简报每个条目所属的世界线。

    ★ 为什么运行时关联而不冗余存储：
      需求要求「历史简报必须保留生成时的事实和判断快照」。
      若把 thread_id 写死进简报，后续归线修正（章节从 A 线移到 B 线）
      会让历史简报指向错误——快照的意义是「当时的文本判断不变」，
      而不是「当时的归属关系永不出错」。归属是活数据，应实时关联。

    ★ 返回结构按 section 分组，键为 event_id：前端拿它给条目挂入口。
    """
    rows = (await db.execute(text("""
        SELECT l.event_id, l.section, l.rank,
               t.id AS thread_id, t.title AS thread_title, t.status AS thread_status,
               te.chapter_id
        FROM digest_event_links l
        JOIN thread_events te ON te.event_id = l.event_id
        JOIN threads t ON t.id = te.thread_id
        WHERE l.digest_id = :d
        ORDER BY l.section, l.rank
    """), {"d": digest_id})).mappings().all()

    links: dict[str, list[dict]] = {}
    for r in rows:
        k = str(r["event_id"])
        links.setdefault(k, []).append({
            "thread_id": str(r["thread_id"]),
            "thread_title": r["thread_title"],
            "thread_status": r["thread_status"],
            "thread_status_label": STATUS_LABELS.get(
                r["thread_status"], r["thread_status"]
            ),
            "chapter_id": str(r["chapter_id"]),
            "section": r["section"],
        })
    return {"digest_id": digest_id, "links": links}


@router.get("/threads/{thread_id}/digests")
async def thread_digests(
    thread_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """世界线 → 简报：收录过本线章节的历史简报。

    与详情端点里的 history_digests 同源，独立成端点供「跳回简报」
    单独调用（详情页一次拿全，跳转页按需重试）。
    """
    rows = (await db.execute(text("""
        SELECT d.id, d.digest_date, d.period_label,
               COUNT(DISTINCT l.event_id) AS linked_events,
               array_agg(DISTINCT l.section) AS sections
        FROM thread_events te
        JOIN digest_event_links l ON l.event_id = te.event_id
        JOIN news_digests d ON d.id = l.digest_id
        WHERE te.thread_id = :t
        GROUP BY d.id, d.digest_date, d.period_label
        ORDER BY d.digest_date DESC
        LIMIT :lim
    """), {"t": thread_id, "lim": limit})).mappings().all()

    return {
        "thread_id": str(thread_id),
        "total": len(rows),
        "items": [
            {
                "id": r["id"],
                "digest_date": r["digest_date"],
                "period_label": r["period_label"],
                "linked_events": r["linked_events"],
                "sections": [s for s in (r["sections"] or []) if s],
            }
            for r in rows
        ],
    }
