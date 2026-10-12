"""世界线治理 API — 13 个端点。

★ 贯穿全文件的三条铁律：

1. **写操作必须留痕**：每一个会改变线/章节状态的操作都往 thread_operations
   插一条记录，带 operator + reason。理由是 P1-c 归线算法的 eligible() 依赖
   本表做人工排除判断——「人工治理是权威，被摘除的线绝不能再自动归回」。
   漏写一条留痕 = 归线算法看不见这次人工干预 = 下次自动归回，治理直接失效。

2. **危险操作默认需要 reason**：merge / split / remove / 状态跃迁 强制要求
   reason（人工路径）。原因见各端点注释。reason 缺失的排除/合并无法回溯，
   将来回放调参时这条数据就是黑洞。

3. **审计表只追加**：thread_operations 永不 UPDATE / DELETE。
   人工纠错靠「追加反向操作」（restore 撤销 remove），不靠改历史。
   改写历史会让「当时为什么这么判」永久丢失。

端点清单（13）：
  查询类 5： list / detail / chapters / history / stats
  线级操作 5： pin / unpin / merge / split / status
  事件级 3：   remove / restore / move
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/threads", tags=["world-threads"])

# 合法状态与角色，与模型 CHECK 约束保持一致（在此集中定义，避免散落魔法串）
THREAD_STATUSES = {"embryo", "active", "dormant", "resolved", "merged", "split"}
MEMBERSHIP_ROLES = {"core", "trigger", "reaction", "signal", "context", "noise"}
# merge/split 是终态：之后不再接收新事件，只保留重定向指针
TERMINAL_STATUSES = {"merged", "split"}


# ─────────────────────────── Schemas ───────────────────────────

class ThreadCreate(BaseModel):
    title: str = Field(..., max_length=200)
    contested_asset: str | None = Field(None, max_length=200)
    mechanism_key: str | None = Field(None, max_length=128)
    status: str = Field("embryo")


class ThreadPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    contested_asset: str | None = Field(None, max_length=200)
    mechanism_key: str | None = Field(None, max_length=128)
    pinned_fields: dict | None = None


class OpBody(BaseModel):
    """通用操作体。operator 默认 'human'，reason 按需强制。"""
    operator: str = Field("human", max_length=64)
    reason: str | None = None


class PinBody(OpBody):
    pinned_fields: dict | None = None


class MergeBody(OpBody):
    source_thread_id: uuid.UUID
    target_thread_id: uuid.UUID


class SplitBody(OpBody):
    new_title: str = Field(..., max_length=200)
    chapter_ids: list[uuid.UUID] = Field(..., min_length=1)


class StatusBody(OpBody):
    status: str


class EventOpBody(OpBody):
    event_id: uuid.UUID


class MoveBody(OpBody):
    event_id: uuid.UUID
    from_thread_id: uuid.UUID
    to_thread_id: uuid.UUID


# ─────────────────────────── 内部工具 ───────────────────────────

async def _get_thread(db: AsyncSession, thread_id: uuid.UUID) -> dict | None:
    row = (await db.execute(
        text("SELECT id, title, status, merged_into_id, pinned, chapter_count "
             "FROM threads WHERE id = :t"),
        {"t": thread_id},
    )).mappings().first()
    return dict(row) if row else None


async def _require_thread(db: AsyncSession, thread_id: uuid.UUID) -> dict:
    t = await _get_thread(db, thread_id)
    if not t:
        raise HTTPException(404, f"thread {thread_id} not found")
    return t


def _require_reason(reason: str | None, action: str) -> str:
    """危险操作强制 reason。

    merge/split/remove 都是不可逆或半不可逆的语义操作。没有 reason，
    三个月后回放调参时只能看到「某线被合并了」，看不到「为什么」，
    这条记录就是黑洞——无法判断当时判断是否正确，也就无法改进算法。
    """
    if not (reason or "").strip():
        raise HTTPException(400, f"reason is required for {action}")
    return reason.strip()


async def _audit(
    db: AsyncSession,
    thread_id: uuid.UUID | None,
    operation: str,
    target_type: str,
    target_id: uuid.UUID | None,
    operator: str,
    reason: str | None,
    payload: dict | None = None,
) -> None:
    """写审计留痕。★ 全文件所有写操作都必须经过这里。

    不写留痕的后果不是「少一条日志」——eligible() 查不到这次人工干预，
    下次归线会把人工摘除的线又自动挂回去，治理当场失效。
    """
    import json
    await db.execute(
        text("""
            INSERT INTO thread_operations
                (thread_id, operation, target_type, target_id, operator, reason, payload)
            VALUES
                (:tid, :op, :tt, :ti, :who, :why, CAST(:payload AS jsonb))
        """),
        {
            "tid": thread_id, "op": operation, "tt": target_type,
            "ti": target_id, "who": (operator or "human")[:64],
            "why": reason, "payload": json.dumps(payload) if payload else None,
        },
    )


def _row_to_thread(r) -> dict:
    return {
        "id": str(r["id"]),
        "title": r["title"],
        "contested_asset": r.get("contested_asset"),
        "mechanism_key": r.get("mechanism_key"),
        "status": r.get("status"),
        "pinned": bool(r.get("pinned")),
        "chapter_count": r.get("chapter_count") or 0,
        "last_event_at": r.get("last_event_at"),
        "updated_at": r.get("updated_at"),
    }


# ═══════════════════════ 查询类 5 个 ═══════════════════════

@router.get("")
async def list_threads(
    status: str | None = Query(None),
    mechanism: str | None = Query(None),
    pinned: bool | None = Query(None),
    q: str | None = Query(None, description="标题/标的模糊搜索"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """世界线列表。默认按最近更新倒序，钉住的线排最前。"""
    where, params = ["1=1"], {"lim": limit, "off": offset}
    if status:
        where.append("status = :status"); params["status"] = status
    if mechanism:
        where.append("mechanism_key = :mech"); params["mech"] = mechanism
    if pinned is not None:
        where.append("pinned = :pinned"); params["pinned"] = pinned
    if q:
        where.append("(title ILIKE :q OR contested_asset ILIKE :q)")
        params["q"] = f"%{q}%"

    rows = (await db.execute(text(f"""
        SELECT id, title, contested_asset, mechanism_key, status, pinned,
               chapter_count, last_event_at, updated_at
        FROM threads
        WHERE {' AND '.join(where)}
        ORDER BY pinned DESC, last_event_at DESC NULLS LAST
        LIMIT :lim OFFSET :off
    """), params)).mappings().all()
    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM threads WHERE {' AND '.join(where)}"), params
    )).scalar()
    return {"total": total, "items": [_row_to_thread(r) for r in rows]}


@router.get("/{thread_id}")
async def get_thread(thread_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """线详情。

    ★ 已合并/拆分的线返回 409 + merged_into_id 重定向指针，而不是 404。
    用 404 会让调用方以为「这条线不存在」，实际它是「被合并了」——
    语义完全不同。调用方需要能顺着指针找到新线。
    """
    r = (await db.execute(text("""
        SELECT id, title, contested_asset, mechanism_key, status, pinned,
               pinned_fields, merged_into_id, rollup, rollup_updated_at,
               core_entities, chapter_count, last_event_at, created_at, updated_at
        FROM threads WHERE id = :t
    """), {"t": thread_id})).mappings().first()
    if not r:
        raise HTTPException(404, f"thread {thread_id} not found")
    d = _row_to_thread(r)
    d.update({
        "pinned_fields": r.get("pinned_fields"),
        "rollup": r.get("rollup"),
        "rollup_updated_at": r.get("rollup_updated_at"),
        "core_entities": r.get("core_entities"),
        "created_at": r.get("created_at"),
    })
    if r.get("status") in TERMINAL_STATUSES and r.get("merged_into_id"):
        d["merged_into_id"] = str(r["merged_into_id"])
        d["redirect_hint"] = "this thread was merged; follow merged_into_id"
    return d


@router.get("/{thread_id}/chapters")
async def list_chapters(
    thread_id: uuid.UUID,
    role: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """章节列表（按展示序号 chapter_no 正序，即线的时间轴）。

    noise 章节默认排除——它是人工判定的「挂错了」，不该出现在线的时间轴上。
    这一点和 chapter_seq「context/noise 置 NULL 不计入」是同一个意图。
    """
    await _require_thread(db, thread_id)
    where = ["te.thread_id = :t"]
    params = {"t": thread_id, "lim": limit, "off": offset}
    if role:
        if role not in MEMBERSHIP_ROLES:
            raise HTTPException(400, f"invalid role: {role}")
        where.append("te.role = :role"); params["role"] = role
    else:
        where.append("COALESCE(te.role,'core') <> 'noise'")

    rows = (await db.execute(text(f"""
        SELECT te.chapter_id, te.event_id, te.role, te.chapter_no, te.chapter_seq,
               te.assigned_by, te.match_score, te.snapshot_title,
               te.snapshot_summary, te.occurred_at
        FROM thread_events te
        WHERE {' AND '.join(where)}
        ORDER BY te.chapter_no NULLS LAST, te.chapter_seq
        LIMIT :lim OFFSET :off
    """), params)).mappings().all()
    return {"total": len(rows), "items": [
        {
            "chapter_id": str(r["chapter_id"]),
            "event_id": str(r["event_id"]) if r["event_id"] else None,
            "role": r["role"],
            "chapter_no": r["chapter_no"],
            "chapter_seq": r["chapter_seq"],
            "assigned_by": r["assigned_by"],
            "match_score": r["match_score"],
            "title": r["snapshot_title"],
            "summary": r["snapshot_summary"],
            "occurred_at": r["occurred_at"],
        } for r in rows
    ]}


@router.get("/{thread_id}/history")
async def get_history(
    thread_id: uuid.UUID,
    operation: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """治理历史（人工操作审计）。人工路径为主，故默认过滤掉 auto: 前缀。"""
    await _require_thread(db, thread_id)
    where = ["thread_id = :t"]
    params = {"t": thread_id, "lim": limit, "off": offset}
    if operation:
        where.append("operation = :op"); params["op"] = operation
    else:
        where.append("COALESCE(operator,'') NOT LIKE 'auto:%'")
    rows = (await db.execute(text(f"""
        SELECT id, operation, target_type, target_id, operator, reason,
               payload, created_at
        FROM thread_operations
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT :lim OFFSET :off
    """), params)).mappings().all()
    return {"total": len(rows), "items": [
        {
            "id": str(r["id"]), "operation": r["operation"],
            "target_type": r["target_type"],
            "target_id": str(r["target_id"]) if r["target_id"] else None,
            "operator": r["operator"], "reason": r["reason"],
            "payload": r["payload"], "created_at": r["created_at"],
        } for r in rows
    ]}


@router.get("/{thread_id}/stats")
async def get_stats(thread_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """线统计：章节构成 + 传导链证据分布 + 治理活跃度。

    这个端点是影子期的驾驶舱——归线质量好不好，主要看 role='noise' 的占比
    和 evidence_status 的分布。noise 占比高说明归线太松，需要提高 T_JOIN。
    """
    await _require_thread(db, thread_id)
    roles = (await db.execute(text("""
        SELECT role, COUNT(*) FROM thread_events
        WHERE thread_id = :t GROUP BY role
    """), {"t": thread_id})).all()
    ev = (await db.execute(text("""
        SELECT evidence_status, COUNT(*) FROM thread_transmissions
        WHERE thread_id = :t GROUP BY evidence_status
    """), {"t": thread_id})).all()
    ops = (await db.execute(text("""
        SELECT COUNT(*) FROM thread_operations
        WHERE thread_id = :t AND COALESCE(operator,'') NOT LIKE 'auto:%'
    """), {"t": thread_id})).scalar()
    total_ch = sum(c for _, c in roles) or 0
    noise = next((c for r, c in roles if r == "noise"), 0)
    return {
        "chapter_count": total_ch,
        "by_role": {r: c for r, c in roles},
        "noise_ratio": round(noise / total_ch, 4) if total_ch else 0.0,
        "transmissions_by_evidence": {r: c for r, c in ev},
        "manual_operations": ops,
    }


# ═══════════════════════ 线级操作 5 个 ═══════════════════════

@router.post("/{thread_id}/pin")
async def pin_thread(
    thread_id: uuid.UUID, body: PinBody, db: AsyncSession = Depends(get_db),
):
    """钉住线：走高质量模型 + 提高摘要频次，并可锁定字段不被算法覆盖。

    pinned_fields 是「人工锁」——算法检测到后不得覆盖这些字段。
    这是人工对算法的否决权，锁了 mechanism_key 算法就不能改。
    """
    await _require_thread(db, thread_id)
    await db.execute(
        text("UPDATE threads SET pinned = true, pinned_fields = "
             "COALESCE(CAST(:pf AS jsonb), pinned_fields), updated_at = now() "
             "WHERE id = :t"),
        {"t": thread_id,
         "pf": _json(body.pinned_fields) if body.pinned_fields else None},
    )
    await _audit(db, thread_id, "pin", "thread", thread_id,
                 body.operator, body.reason, {"pinned_fields": body.pinned_fields})
    await db.commit()
    return {"ok": True, "pinned": True}


@router.post("/{thread_id}/unpin")
async def unpin_thread(
    thread_id: uuid.UUID, body: OpBody, db: AsyncSession = Depends(get_db),
):
    """取消钉住，并清空字段锁。

    ★ 解钉即解锁：pinned_fields 置 NULL。保留锁而无 pinned 标记会造成
    「看不见但生效」的隐形约束——UI 上显示未钉住，算法却被锁着，极难排查。
    """
    await _require_thread(db, thread_id)
    await db.execute(
        text("UPDATE threads SET pinned = false, pinned_fields = NULL, "
             "updated_at = now() WHERE id = :t"),
        {"t": thread_id},
    )
    await _audit(db, thread_id, "unpin", "thread", thread_id,
                 body.operator, body.reason)
    await db.commit()
    return {"ok": True, "pinned": False}


@router.post("/merge")
async def merge_threads(body: MergeBody, db: AsyncSession = Depends(get_db)):
    """合并两条线：源线的章节迁到目标线，源线置 merged 并留重定向指针。

    ★ 三个关键设计：
    1. chapter_id 迁移时保持不变。传导链/观察点都按 chapter_id 引用章节，
       重新生成会让所有外部引用失效。chapter_id 是章节的永久身份。
    2. 源线保留为 merged 终态而非删除。删除会让 merged_into_id 指针悬空，
       旧链接全部 404。保留 + 重定向是唯一安全做法。
    3. 章节冲突（同一事件已在目标线）用 DO NOTHING 跳过，不覆盖目标线
       已有的人工判定（assigned_by='manual' 的章节优先）。
    """
    _require_reason(body.reason, "merge")
    if body.source_thread_id == body.target_thread_id:
        raise HTTPException(400, "cannot merge a thread into itself")
    src = await _require_thread(db, body.source_thread_id)
    dst = await _require_thread(db, body.target_thread_id)
    if src["status"] in TERMINAL_STATUSES:
        raise HTTPException(409, f"source thread already {src['status']}")

    moved = (await db.execute(text("""
        INSERT INTO thread_events
            (thread_id, event_id, role, chapter_id, chapter_no, chapter_seq,
             assigned_by, match_score, snapshot_title, snapshot_summary, occurred_at)
        SELECT :dst, te.event_id, te.role, te.chapter_id, NULL, NULL,
               te.assigned_by, te.match_score, te.snapshot_title,
               te.snapshot_summary, te.occurred_at
        FROM thread_events te
        WHERE te.thread_id = :src
        ON CONFLICT (thread_id, event_id) DO NOTHING
    """), {"dst": body.target_thread_id, "src": body.source_thread_id})).rowcount

    await db.execute(text("""
        UPDATE threads SET status = 'merged', merged_into_id = :dst,
               updated_at = now() WHERE id = :src
    """), {"src": body.source_thread_id, "dst": body.target_thread_id})
    await db.execute(text("""
        UPDATE threads SET chapter_count = chapter_count + :n, updated_at = now()
        WHERE id = :dst
    """), {"dst": body.target_thread_id, "n": moved or 0})

    await _audit(db, body.source_thread_id, "merge", "thread",
                 body.target_thread_id, body.operator, body.reason,
                 {"moved_chapters": moved or 0, "target_title": dst["title"]})
    await _audit(db, body.target_thread_id, "merge", "thread",
                 body.source_thread_id, body.operator, body.reason,
                 {"received_chapters": moved or 0, "source_title": src["title"]})
    await db.commit()
    return {"ok": True, "moved_chapters": moved or 0,
            "merged_into_id": str(body.target_thread_id)}


@router.post("/{thread_id}/split")
async def split_thread(
    thread_id: uuid.UUID, body: SplitBody, db: AsyncSession = Depends(get_db),
):
    """拆分线：把指定章节迁到新建的子线。

    ★ 原线保持 active，不置终态。拆分是「一分为二」，原线仍有自己的
      剩余章节，置终态会让原线的剩余章节失去载体。
      这与 merge 不同——merge 是源线消失，split 是源线瘦身。

    chapter_id 迁移时保持不变（理由同 merge）。
    """
    _require_reason(body.reason, "split")
    parent = await _require_thread(db, thread_id)
    if parent["status"] in TERMINAL_STATUSES:
        raise HTTPException(409, f"thread already {parent['status']}")

    new_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO threads (id, title, contested_asset, mechanism_key, status)
        SELECT :nid, :title, contested_asset, mechanism_key, 'active'
        FROM threads WHERE id = :src
    """), {"nid": new_id, "title": body.new_title, "src": thread_id})

    ids = [str(c) for c in body.chapter_ids]
    moved = (await db.execute(text("""
        INSERT INTO thread_events
            (thread_id, event_id, role, chapter_id, assigned_by, match_score,
             snapshot_title, snapshot_summary, occurred_at)
        SELECT :nid, te.event_id, te.role, te.chapter_id, te.assigned_by,
               te.match_score, te.snapshot_title, te.snapshot_summary, te.occurred_at
        FROM thread_events te
        WHERE te.thread_id = :src AND te.chapter_id = ANY(:ids)
        ON CONFLICT (thread_id, event_id) DO NOTHING
    """), {"nid": new_id, "src": thread_id, "ids": ids})).rowcount

    await db.execute(text("""
        DELETE FROM thread_events
        WHERE thread_id = :src AND chapter_id = ANY(:ids)
    """), {"src": thread_id, "ids": ids})
    await db.execute(
        text("UPDATE threads SET chapter_count = GREATEST(chapter_count - :n, 0), "
             "updated_at = now() WHERE id = :src"),
        {"src": thread_id, "n": moved or 0},
    )
    await db.execute(
        text("UPDATE threads SET chapter_count = :n WHERE id = :nid"),
        {"nid": new_id, "n": moved or 0},
    )
    await _audit(db, thread_id, "split", "thread", new_id,
                 body.operator, body.reason,
                 {"new_title": body.new_title, "moved_chapters": moved or 0,
                  "chapter_ids": ids})
    await db.commit()
    return {"ok": True, "new_thread_id": str(new_id), "moved_chapters": moved or 0}


@router.patch("/{thread_id}/status")
async def update_status(
    thread_id: uuid.UUID, body: StatusBody, db: AsyncSession = Depends(get_db),
):
    """状态跃迁。

    ★ 禁止从 merged/split 跃迁回其他状态。合并/拆分是单向不可逆的——
    章节已经迁走，源线只剩重定向指针。允许回退会产生「有指针但声称活跃」
    的矛盾状态，归线算法可能又把事件挂回来。
    """
    if body.status not in THREAD_STATUSES:
        raise HTTPException(400, f"invalid status: {body.status}")
    t = await _require_thread(db, thread_id)
    if t["status"] in TERMINAL_STATUSES:
        raise HTTPException(
            409, f"thread is {t['status']}, terminal state cannot be reversed",
        )
    if body.status in TERMINAL_STATUSES:
        _require_reason(body.reason, f"status -> {body.status}")
    await db.execute(
        text("UPDATE threads SET status = :s, updated_at = now() WHERE id = :t"),
        {"t": thread_id, "s": body.status},
    )
    await _audit(db, thread_id, "move", "thread", thread_id,
                 body.operator, body.reason,
                 {"from": t["status"], "to": body.status})
    await db.commit()
    return {"ok": True, "status": body.status}


# ═══════════════════════ 事件级操作 3 个 ═══════════════════════

@router.post("/{thread_id}/events/remove")
async def remove_event(
    thread_id: uuid.UUID, body: EventOpBody, db: AsyncSession = Depends(get_db),
):
    """人工摘除挂错的事件。

    ★ 这是全 API 最关键的一个端点，因为是 eligible() 的数据来源。
    只写 remove 留痕而不删 thread_events 行是不够的吗？——不，两者都要：
      1. 删行：让线的时间轴立刻正确（noise 章节不该展示）
      2. 留痕：让 eligible() 能查到，防止下次自动归回
    只做其一都会出问题：只留痕，时间轴仍脏；只删行，下次自动归回。
    """
    _require_reason(body.reason, "remove")
    await _require_thread(db, thread_id)
    res = await db.execute(
        text("DELETE FROM thread_events WHERE thread_id = :t AND event_id = :e"),
        {"t": thread_id, "e": body.event_id},
    )
    if not res.rowcount:
        raise HTTPException(404, "event not in this thread")
    await _audit(db, thread_id, "remove", "event", body.event_id,
                 body.operator, body.reason)
    await db.commit()
    return {"ok": True, "removed": True}


@router.post("/{thread_id}/events/restore")
async def restore_event(
    thread_id: uuid.UUID, body: EventOpBody, db: AsyncSession = Depends(get_db),
):
    """撤销摘除（remove 的反向操作），把事件挂回线。

    ★ 用追加 restore 记录的方式撤销，而不是删掉那条 remove 记录。
    审计表只追加——删掉 remove 会让「曾经误摘过」这件事永久丢失，
    而这件事恰恰是评估归线质量的 ground truth（人工改判记录）。
    eligible() 用 NOT EXISTS(更晚的 restore) 判定，天然支持这种撤销。
    """
    await _require_thread(db, thread_id)
    existed = (await db.execute(text("""
        SELECT 1 FROM thread_operations
        WHERE thread_id = :t AND target_type = 'event' AND target_id = :e
          AND operation = 'remove'
          AND NOT EXISTS (
              SELECT 1 FROM thread_operations r
              WHERE r.thread_id = :t AND r.target_type = 'event'
                AND r.target_id = :e AND r.operation = 'restore'
                AND r.created_at > thread_operations.created_at)
    """), {"t": thread_id, "e": body.event_id})).scalar()
    if not existed:
        raise HTTPException(400, "no active remove to restore")

    await db.execute(text("""
        INSERT INTO thread_events
            (thread_id, event_id, role, chapter_id, assigned_by, snapshot_title,
             snapshot_summary, occurred_at)
        SELECT :t, e.id, 'core', gen_random_uuid(), 'manual', e.title,
               e.summary, e.last_updated_at
        FROM events e WHERE e.id = :e
        ON CONFLICT (thread_id, event_id) DO NOTHING
    """), {"t": thread_id, "e": body.event_id})
    await _audit(db, thread_id, "restore", "event", body.event_id,
                 body.operator, body.reason)
    await db.commit()
    return {"ok": True, "restored": True}


@router.post("/events/move")
async def move_event(body: MoveBody, db: AsyncSession = Depends(get_db)):
    """把事件从一条线移到另一条线。

    ★ 必须同时写两条留痕（源线的 remove + 目标线的 remove-target），
    否则会出现「事件从 A 消失但 A 的审计里查不到为什么」的空洞。

    ★ 同时对源线写 remove 排除标记，防止归线立刻把它挂回原线——
    人工移动表达的是「这条线不该有它」，不写排除标记等于移动无效。
    """
    await _require_thread(db, body.from_thread_id)
    await _require_thread(db, body.to_thread_id)
    if body.from_thread_id == body.to_thread_id:
        raise HTTPException(400, "source and target must differ")

    res = await db.execute(
        text("DELETE FROM thread_events WHERE thread_id = :f AND event_id = :e"),
        {"f": body.from_thread_id, "e": body.event_id},
    )
    if not res.rowcount:
        raise HTTPException(404, "event not in source thread")

    await db.execute(text("""
        INSERT INTO thread_events
            (thread_id, event_id, role, chapter_id, assigned_by, snapshot_title,
             snapshot_summary, occurred_at)
        SELECT :t, e.id, 'core', gen_random_uuid(), 'manual', e.title,
               e.summary, e.last_updated_at
        FROM events e WHERE e.id = :e
        ON CONFLICT (thread_id, event_id) DO NOTHING
    """), {"t": body.to_thread_id, "e": body.event_id})

    await _audit(db, body.from_thread_id, "remove", "event", body.event_id,
                 body.operator, body.reason or "moved out",
                 {"moved_to": str(body.to_thread_id)})
    await _audit(db, body.to_thread_id, "move", "event", body.event_id,
                 body.operator, body.reason,
                 {"moved_from": str(body.from_thread_id)})
    await db.commit()
    return {"ok": True, "moved": True}


def _json(v) -> str:
    import json
    return json.dumps(v)
