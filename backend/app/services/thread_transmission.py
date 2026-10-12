"""世界线 P1-e：传导链 + 线级观察点。

两张表，两个视角：
  传导链（thread_transmissions）  回看：已发生的「A → B」因果边
  观察点（thread_watchpoints）    前瞻：下一步看到什么说明线在推进

★ 本模块最核心的一条约束 —— 传导链状态机的单调性：

    contradicted（已反驳）是单向门，禁止自动回退到 supported。
    只有人工仲裁（arbitrate_transmission）能逆转。

为什么：传导链存的是「推断」不是「事实」。自动流程基于新证据推翻
已有反驳，等于让算法自己给自己平反——链条上的每一步推断都可能错，
自动平反会让错误推断在 supported/contradicted 之间反复横跳，
最终没人知道这条边到底靠不靠得住。人工仲裁是唯一可信的逆转路径，
且必须留名（arbitrated_by），事后可追责。

对比：hypothesis → supported 和 hypothesis → contradicted 都是允许的，
因为假设本来就没有定论。只有「定论为假」之后才锁死。

★ 观察点与传导链的状态语义独立，不可互相推导：
  观察点被「命中」≠ 它验证的传导边被「证实」。
  命中只说明预期信号出现了，因果传导关系仍需独立证据支撑。
  这是两个不同强度的断言，混用会让弱证据冒充强证据。
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session

logger = logging.getLogger(__name__)

# 传导链三态
EVIDENCE_HYPOTHESIS = "hypothesis"
EVIDENCE_SUPPORTED = "supported"
EVIDENCE_CONTRADICTED = "contradicted"
EVIDENCE_STATUSES = (EVIDENCE_HYPOTHESIS, EVIDENCE_SUPPORTED, EVIDENCE_CONTRADICTED)

# 观察点四态
WP_OPEN = "open"
WP_HIT = "hit"
WP_MISSED = "missed"
WP_EXPIRED = "expired"
# hit/missed 是终态，但允许人工 reopen（可能误判或需重新观察）
WP_TERMINAL = (WP_HIT, WP_MISSED)


# ═══════════════════════ 传导链 ═══════════════════════

async def add_transmission(
    thread_id: uuid.UUID,
    from_chapter_id: uuid.UUID,
    to_chapter_id: uuid.UUID,
    mechanism: str,
    strength: float | None = None,
    evidence_status: str = EVIDENCE_HYPOTHESIS,
    evidence_event_id: uuid.UUID | None = None,
    evidence_note: str | None = None,
    db: AsyncSession | None = None,
) -> uuid.UUID | None:
    """新增一条传导边。

    ★ mechanism 必填且不可为空串。传导边存的是推断，如果连「为什么认为
      A 导致 B」都写不出来，这条边就是纯粹的模式噪音，不该入库。

    ★ 自环（from == to）直接拒绝——不抛异常，返回 None。
      调用方多为批量流程，抛异常会中断整批；但数据库层仍有
      ck_transmission_no_self 兜底，双保险。
    """
    if not (mechanism or "").strip():
        logger.warning("add_transmission: 空 mechanism，拒绝入库")
        return None
    if from_chapter_id == to_chapter_id:
        logger.warning("add_transmission: 自环边，拒绝")
        return None
    if evidence_status not in EVIDENCE_STATUSES:
        raise ValueError(f"invalid evidence_status: {evidence_status}")

    own = db is None
    if own:
        db = async_session()
    try:
        row = (await db.execute(text("""
            INSERT INTO thread_transmissions
                (thread_id, from_chapter_id, to_chapter_id, mechanism, strength,
                 evidence_status, evidence_event_id, evidence_note)
            VALUES (:t, :f, :to, :m, :s, :es, :ee, :en)
            ON CONFLICT (thread_id, from_chapter_id, to_chapter_id) DO NOTHING
            RETURNING id
        """), {
            "t": thread_id, "f": from_chapter_id, "to": to_chapter_id,
            "m": mechanism.strip(), "s": strength, "es": evidence_status,
            "ee": evidence_event_id, "en": evidence_note,
        })).scalar()
        if own:
            await db.commit()
        return row
    finally:
        if own:
            await db.close()


async def update_evidence(
    transmission_id: uuid.UUID,
    new_status: str,
    evidence_event_id: uuid.UUID | None = None,
    evidence_note: str | None = None,
    db: AsyncSession | None = None,
) -> bool:
    """更新传导边的证据状态（自动路径）。

    ★ 单调性规则的落点：
      - contradicted → 任何状态：一律拒绝（自动路径无权平反）
      - 其余跃迁：允许

    为什么不允许自动平反：见模块 docstring。简单说，让算法自己推翻
    自己的反驳结论，等于没有结论。

    ★ 状态确有新证据时才允许变更，故 evidence_event_id 强烈建议填写。
      留空的证据变动无法追溯，回放时是黑洞。
    """
    if new_status not in EVIDENCE_STATUSES:
        raise ValueError(f"invalid evidence_status: {new_status}")

    own = db is None
    if own:
        db = async_session()
    try:
        cur = (await db.execute(
            text("SELECT evidence_status FROM thread_transmissions WHERE id = :i"),
            {"i": transmission_id},
        )).scalar()
        if cur is None:
            return False
        if cur == EVIDENCE_CONTRADICTED and new_status != EVIDENCE_CONTRADICTED:
            logger.warning(
                "update_evidence: 拒绝自动平反 contradicted 边 %s（需人工仲裁）",
                transmission_id,
            )
            return False
        if cur == new_status:
            return True
        await db.execute(text("""
            UPDATE thread_transmissions
            SET evidence_status = :ns, evidence_event_id = COALESCE(:ee, evidence_event_id),
                evidence_note = COALESCE(:en, evidence_note),
                status_changed_at = now()
            WHERE id = :i
        """), {"i": transmission_id, "ns": new_status,
               "ee": evidence_event_id, "en": evidence_note})
        if own:
            await db.commit()
        return True
    finally:
        if own:
            await db.close()


async def arbitrate_transmission(
    transmission_id: uuid.UUID,
    new_status: str,
    arbitrated_by: str,
    evidence_note: str | None = None,
    db: AsyncSession | None = None,
) -> bool:
    """人工仲裁传导边——唯一能逆转 contradicted 的路径。

    ★ 与 update_evidence 的区别：本函数无单调性限制，任何跃迁都允许，
      但强制要求 arbitrated_by（留名可追责）。

    为什么允许人工平反而不允许自动平反：人工仲裁者承担判断责任且留名，
    事后可复核「当时为什么改」；自动流程无人负责，且会在两种状态间
    反复横跳，最终整张表失去可信度。
    """
    if new_status not in EVIDENCE_STATUSES:
        raise ValueError(f"invalid evidence_status: {new_status}")
    if not (arbitrated_by or "").strip():
        raise ValueError("arbitrated_by is required for arbitration")

    own = db is None
    if own:
        db = async_session()
    try:
        res = await db.execute(text("""
            UPDATE thread_transmissions
            SET evidence_status = :ns, evidence_note = COALESCE(:en, evidence_note),
                arbitrated_by = :who, status_changed_at = now()
            WHERE id = :i
        """), {"i": transmission_id, "ns": new_status,
               "en": evidence_note, "who": arbitrated_by.strip()})
        if own:
            await db.commit()
        return bool(res.rowcount)
    finally:
        if own:
            await db.close()


async def list_transmissions(
    thread_id: uuid.UUID,
    evidence_status: str | None = None,
    min_strength: float | None = None,
    db: AsyncSession | None = None,
) -> list[dict]:
    """查询某条线的传导链。默认按强度降序。"""
    where = ["thread_id = :t"]
    params = {"t": thread_id}
    if evidence_status:
        where.append("evidence_status = :es"); params["es"] = evidence_status
    if min_strength is not None:
        where.append("strength >= :ms"); params["ms"] = min_strength

    own = db is None
    if own:
        db = async_session()
    try:
        rows = (await db.execute(text(f"""
            SELECT id, from_chapter_id, to_chapter_id, mechanism, evidence_status,
                   evidence_event_id, evidence_note, strength, created_at,
                   status_changed_at, arbitrated_by
            FROM thread_transmissions
            WHERE {' AND '.join(where)}
            ORDER BY strength DESC NULLS LAST, created_at DESC
        """), params)).mappings().all()
        return [dict(r) for r in rows]
    finally:
        if own:
            await db.close()


# ═══════════════════════ 观察点 ═══════════════════════

async def add_watchpoint(
    thread_id: uuid.UUID,
    assertion: str,
    kind: str = "trigger",
    criteria: dict | None = None,
    expires_in_days: int | None = 30,
    created_by: str | None = None,
    db: AsyncSession | None = None,
) -> uuid.UUID | None:
    """新增线级观察点。

    ★ assertion 必须可证伪。「油价突破 100 美元」可证伪；
      「局势持续紧张」不可证伪——无论发生什么都能自圆其说，
      对决策毫无价值。代码层无法判断可证伪性（那是语义问题），
      只能挡住空串，真正的把关在人工创建时。

    ★ expires_in_days 默认 30 天而非永不过期。无期限的观察点等于
      永远不验证，会无限堆积成噪音，最终让整张表失去意义。
      传 None 显式表示不过期（少数长期结构型观察点用）。
    """
    import json

    if not (assertion or "").strip():
        logger.warning("add_watchpoint: 空断言，拒绝入库")
        return None
    if kind not in ("trigger", "signal", "guard", "invalidation"):
        raise ValueError(f"invalid kind: {kind}")

    expires_at = None
    if expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    own = db is None
    if own:
        db = async_session()
    try:
        row = (await db.execute(text("""
            INSERT INTO thread_watchpoints
                (thread_id, assertion, kind, criteria, expires_at, created_by)
            VALUES (:t, :a, :k, CAST(:c AS jsonb), :e, :cb)
            RETURNING id
        """), {
            "t": thread_id, "a": assertion.strip(), "k": kind,
            "c": json.dumps(criteria) if criteria else None,
            "e": expires_at, "cb": created_by,
        })).scalar()
        if own:
            await db.commit()
        return row
    finally:
        if own:
            await db.close()


async def resolve_watchpoint(
    watchpoint_id: uuid.UUID,
    status: str,
    resolved_event_id: uuid.UUID | None = None,
    resolution_note: str | None = None,
    db: AsyncSession | None = None,
) -> bool:
    """判定观察点：命中（hit）或判负（missed）。

    ★ 只允许 open → hit/missed。已终结的观察点不可再判定——
      重复判定会让「命中过」这个事实被覆盖，历史丢失。
      确需重新观察用 reopen_watchpoint（那是显式的新一轮判断）。
    """
    if status not in (WP_HIT, WP_MISSED):
        raise ValueError(f"resolve status must be hit/missed, got {status}")

    own = db is None
    if own:
        db = async_session()
    try:
        res = await db.execute(text("""
            UPDATE thread_watchpoints
            SET status = :s, resolved_event_id = :re, resolution_note = :rn,
                resolved_at = now()
            WHERE id = :i AND status = 'open'
        """), {"i": watchpoint_id, "s": status,
               "re": resolved_event_id, "rn": resolution_note})
        if own:
            await db.commit()
        return bool(res.rowcount)
    finally:
        if own:
            await db.close()


async def reopen_watchpoint(
    watchpoint_id: uuid.UUID,
    expires_in_days: int | None = 30,
    db: AsyncSession | None = None,
) -> bool:
    """重开观察点（人工路径）。

    ★ 与传导链不同，观察点允许人工重开。原因：观察点可能只是「判早了」
      而非「判错了」——信号延后出现是完全正常的。但传导链的 contradicted
      是「已反驳」，性质更重，故锁死。

    ★ 重开清空 resolved_* 字段。保留旧的判定痕迹又置 open，
      会造成「显示待观察但实际已命中过」的矛盾状态。
      历史判定已由 resolution_note 记录（如需保留，先读出再传入新记录）。
    """
    own = db is None
    if own:
        db = async_session()
    try:
        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        res = await db.execute(text("""
            UPDATE thread_watchpoints
            SET status = 'open', resolved_event_id = NULL, resolution_note = NULL,
                resolved_at = NULL, expires_at = :e
            WHERE id = :i AND status IN ('hit','missed','expired')
        """), {"i": watchpoint_id, "e": expires_at})
        if own:
            await db.commit()
        return bool(res.rowcount)
    finally:
        if own:
            await db.close()


async def expire_watchpoints(
    now: datetime | None = None, db: AsyncSession | None = None
) -> int:
    """批量过期超期未判定的观察点（定时任务用）。

    ★ 只处理 status='open' 的。已终结的观察点超越期也不能改状态——
      它会覆盖 hit/missed 的终态判定，历史丢失。

    超期判负体现「观察点必须有期限」的设计约束：到期没等到信号，
    本身就是一种信息（原假设可能不成立）。
    """
    now = now or datetime.now(timezone.utc)
    own = db is None
    if own:
        db = async_session()
    try:
        res = await db.execute(text("""
            UPDATE thread_watchpoints
            SET status = 'expired', resolved_at = now()
            WHERE status = 'open' AND expires_at IS NOT NULL AND expires_at < :now
        """), {"now": now})
        if own:
            await db.commit()
        return res.rowcount or 0
    finally:
        if own:
            await db.close()


async def list_watchpoints(
    thread_id: uuid.UUID,
    status: str | None = WP_OPEN,
    include_expired: bool = False,
    db: AsyncSession | None = None,
) -> list[dict]:
    """查询某条线的观察点。默认只看 open——已终结的是历史，不是待办。"""
    where = ["thread_id = :t"]
    params = {"t": thread_id}
    if status:
        where.append("status = :s"); params["s"] = status
    elif not include_expired:
        where.append("status = 'open'")

    own = db is None
    if own:
        db = async_session()
    try:
        rows = (await db.execute(text(f"""
            SELECT id, assertion, kind, criteria, status, expires_at,
                   resolved_event_id, resolution_note, created_by,
                   created_at, resolved_at
            FROM thread_watchpoints
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
        """), params)).mappings().all()
        return [dict(r) for r in rows]
    finally:
        if own:
            await db.close()
