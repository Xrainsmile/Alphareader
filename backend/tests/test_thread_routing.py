"""世界线归线回归测试：评分门控 / 幂等 / 并发。

三组测试各自对应一个已发生的真实故障，防止回归：

1. 评分门控 —— 机制缺失时 M=1.0 且新线 R=1.0，S=0.45 恰好过阈值，
   实体零重合的无关事件被错误合并
2. 幂等 —— 建线不挂线（thread_events 长期为 0 的根因）
3. 并发 —— 同主题事件各自独立建线，裂成 N 条单章孤岛

分层说明：
  - 纯函数测试（默认跑）：不依赖 DB，覆盖评分门控、权重解析、并发常量
  - integration 测试（需真实 PostgreSQL，默认跳过）：
    建线即挂载、重复挂载幂等。因为 _attach_event / _sync_chapter_count
    用的是 PG 专有语法（ON CONFLICT ... RETURNING、UPDATE ... FROM），
    而 conftest 提供的是 SQLite 内存库，语法不兼容。
    跑法：pytest -m integration --pg-url=postgresql://...
"""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sqlalchemy import text

from app.services import thread_router
from app.services.thread_router import (
    _thread_entity_weights,
    compute_score,
    entity_gate,
    mechanism_score,
    recency_bonus,
    route_event,
    shared_entity_count,
    weighted_jaccard,
)

# ───────────────────────── 评分门控 ─────────────────────────

def test_mechanism_score_missing_is_neutral():
    """机制缺失返回中性分（0.5），不再白送满分。

    ★ 回归：此处原断言 == 1.0。1.0 在加分制下等于无条件发放 0.30 权重，
    叠加新线 R=1.0 的 0.15 使 S 恒 >= 0.45，无论实体重不重合都过阈值，
    是 8-K 扎堆成一条线的成因之一。
    """
    assert mechanism_score(None, "supply_shock") == 0.5
    assert mechanism_score([], "supply_shock") == 0.5


def test_recency_bonus_new_thread_gives_full_marks():
    """新线 last_event_at=None 返回 1.0 —— R 分被"免费拿满"的源头。"""
    assert recency_bonus(None) == 1.0


def test_zero_entity_overlap_reaches_threshold_naively():
    """E=0 时裸 S 仍可达 0.30 —— 所以必须保留显式门控。

    M 中性化后：0.55*0 + 0.30*0.5 + 0.15*1.0 = 0.30。
    低于 T_JOIN(0.40)，但 **依赖 R=1.0**：若线是活跃的（R 高）且 E 极小
    但仍 > 0（如 0.02），S 会重新逼近阈值。故门控不可省。
    """
    e = weighted_jaccard({"英伟达": 3}, {"胡塞武装": 3})
    assert e == 0.0, "零重合时 Jaccard 必须为 0"

    m = mechanism_score(None, "supply_shock")
    r = recency_bonus(None)
    assert m == 0.5, "空机制必须是中性分，不再是满分"
    assert r == 1.0

    s = 0.55 * e + 0.30 * m + 0.15 * r
    assert 0.29 < s < 0.31, f"中性化后裸 S 应为 0.30，实得 {s}"


def test_entity_gate_blocks_weak_overlap():
    """回归：E 过低或共现数不足都必须一票否决，不论 S 多高。"""
    # E 低于下限 → 否决
    ok, why = entity_gate(0.05, 3)
    assert ok is False and "E=" in why

    # E 达标但只共享 1 个实体 → 否决（8-K 场景：靠单个泛化实体硬串）
    ok, why = entity_gate(0.60, 1)
    assert ok is False and "shared=" in why

    # 两项达标 → 放行
    ok, why = entity_gate(0.30, 2)
    assert ok is True and why == ""


def test_shared_entity_count_ignores_weight():
    """共现只看实体是否存在，不看 weight。

    ★ 回归：全库 event_entities.weight 恒为 1（link_event_entities 唯一
    调用点用默认 default_weight=1），若门控按 weight>=3 的「核心实体」
    判定，会否决 100% 候选、归线彻底停摆。故共现数必须与权重解耦。
    """
    assert shared_entity_count({"A": 1, "B": 1}, {"A": 1, "C": 1}) == 1
    assert shared_entity_count({"A": 1, "B": 1}, {"A": 1, "B": 1}) == 2
    assert shared_entity_count({"A": 1}, {"B": 1}) == 0


async def test_route_event_filters_zero_entity_candidates():
    """回归：候选线 E=0 时必须 join=False，即使 S 够高。"""
    thread = {
        "id": uuid.uuid4(),
        "title": "胡塞袭击油轮",
        "mechanism_key": "supply_shock",
        "core_entities": {"胡塞武装": 3},
        "last_event_at": None,  # 新线 → R=1.0
        "status": "embryo",
    }

    originals = (
        thread_router._load_event_entities,
        thread_router._load_event_mechanisms,
        thread_router._load_manual_exclusions,
        thread_router._load_candidate_threads,
        thread_router._record_shadow,
    )

    async def _no_shadow(_eid, _scored):
        return None

    async def _ents(_eid):
        return {"英伟达": 3}

    async def _mechs(_eid):
        return None  # → M 中性 0.5

    async def _excl(_eid):
        return set()

    async def _cands():
        return [thread]

    thread_router._load_event_entities = _ents
    thread_router._load_event_mechanisms = _mechs
    thread_router._load_manual_exclusions = _excl
    thread_router._load_candidate_threads = _cands
    thread_router._record_shadow = _no_shadow
    try:
        top = await route_event(uuid.uuid4())
        assert len(top) == 1
        assert top[0]["E"] == 0.0
        assert top[0]["join"] is False, "E=0 必须一票否决"
    finally:
        (
            thread_router._load_event_entities,
            thread_router._load_event_mechanisms,
            thread_router._load_manual_exclusions,
            thread_router._load_candidate_threads,
            thread_router._record_shadow,
        ) = originals


def test_single_shared_entity_blocked_despite_high_score():
    """回归 8-K 扎堆：S 高达 0.85 但只共享 1 个实体，必须否决。

    这是本次修复的核心场景。8-K 是 SEC 披露表单编号（文件类型，非事件主体），
    所有「提交 8-K」的事件都共享它 → 无关公司被串成一条线。
    E=1.0、S=0.85 都救不了它，唯有共现数门控能拦住。
    """
    ev = {"8-K": 1}
    th = {"8-K": 1}

    e = weighted_jaccard(ev, th)
    m = mechanism_score(None, "regulation")
    r = recency_bonus(None)
    s = 0.55 * e + 0.30 * m + 0.15 * r

    assert e == 1.0 and s > 0.8, "本场景裸分确实极高，单靠阈值挡不住"

    ok, why = entity_gate(e, shared_entity_count(ev, th))
    assert ok is False and "shared=" in why, "只共享 1 个实体必须否决"


def test_real_same_thread_passes_gate():
    """回归：真正的同线事件必须仍能被放行，门控不能误杀。

    门控收紧后最常见的翻车是「一刀切把归线全掐死」，
    这条测试守住下界：共享 3 个实体的正常事件必须过。
    """
    ev = {"A": 1, "B": 1, "C": 1, "D": 1}
    th = {"A": 1, "B": 1, "C": 1, "E": 1}

    e = weighted_jaccard(ev, th)
    ok, why = entity_gate(e, shared_entity_count(ev, th))
    assert ok is True and why == "", f"正常同线事件被误杀：{why}"


def test_entity_gate_disable_restores_legacy_behavior():
    """回归：THREAD_ENTITY_GATE_ENABLED=false 时必须退回收紧前行为。

    ★ 这是生产的应急回退路径。服务器 THREAD_ROUTING_SHADOW=false（真实写入），
    门控误杀会直接污染数据；且机制命中的线 M=1.0 使 S 恒 >= 0.45，
    T_JOIN 对它们失效、门控是唯一防线。开关必须真能一键退回，
    否则出事只能改代码发版。
    """
    from app.config import settings

    orig = settings.THREAD_ENTITY_GATE_ENABLED
    try:
        settings.THREAD_ENTITY_GATE_ENABLED = False

        # 只共享 1 个实体：收紧时否决，回退后放行（收紧前行为）
        ok, _ = entity_gate(1.0, 1)
        assert ok is True, "回退后不再按共现数否决"

        # E=0 仍必须否决 —— 回退不能退回「零重合也归线」
        ok, why = entity_gate(0.0, 0)
        assert ok is False, "E=0 一票否决在任何模式下都要保留"

        # E 低于下限但 > 0：回退后放行
        ok, _ = entity_gate(0.05, 2)
        assert ok is True, "回退后不再按 E 下限否决"
    finally:
        settings.THREAD_ENTITY_GATE_ENABLED = orig


# ───────────────────────── reference_at（回填偏差） ─────────────────────────

def test_compute_score_reference_at_changes_recency():
    """回归：批量回填必须传 reference_at，否则历史事件 R 恒为 0。"""
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    old = datetime(2026, 8, 4, tzinfo=timezone.utc)

    *_, r_now = compute_score({"A": 1}, {"A": 1}, None, None, old, now)
    *_, r_ref = compute_score(
        {"A": 1}, {"A": 1}, None, None, old, old + timedelta(hours=1)
    )

    assert r_now < 0.01, "历史事件按 now 算 R 会归零"
    assert r_ref > 0.4, "传 reference_at 后 R 应显著恢复"


# ───────────────────────── 并发（串行化保证） ─────────────────────────

def test_backfill_runs_serially():
    """回归：回填必须串行。

    并发下 N 个事件同时加载候选线、都发现无匹配、各自建线，
    同一主题会裂成 N 条单章孤岛而非一条多章线。
    """
    script = Path(__file__).resolve().parents[1] / "scripts" / "backfill_threads.py"
    spec = importlib.util.spec_from_file_location("bft", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.MAX_CONCURRENCY == 1, "冷启动回填必须串行"


# ───────────────────────── 权重解析容错 ─────────────────────────

def test_thread_entity_weights_accepts_both_shapes():
    assert _thread_entity_weights({"A": 3, "B": 1}) == {"A": 3, "B": 1}
    assert _thread_entity_weights(["A", "B"]) == {"A": 1, "B": 1}
    assert _thread_entity_weights(None) == {}


# ───────────────────────── 需真实 PostgreSQL ─────────────────────────

@pytest.mark.integration
async def test_created_thread_has_chapter_one():
    """回归：建线后必须立即挂载触发它的事件。

    此前建线不挂线，新线零章，最终全是孤岛。
    需要真实 PG：_attach_event 用 ON CONFLICT ... RETURNING。
    """
    from app.database import async_session
    from app.services.thread_router import maybe_create_thread

    async with async_session() as s:
        eid = await s.scalar(
            text("""
                SELECT ee.event_id FROM event_entities ee
                JOIN entities e ON e.id = ee.entity_id
                WHERE COALESCE(e.is_generic, false) = false
                LIMIT 1
            """)
        )
    if eid is None:
        pytest.skip("无可用事件")

    tid = await maybe_create_thread(eid)
    if tid is None:
        pytest.skip("该事件未达建线门槛")

    async with async_session() as s:
        cnt = await s.scalar(
            text("SELECT COUNT(*) FROM thread_events WHERE thread_id=:t"), {"t": tid}
        )
        cc = await s.scalar(
            text("SELECT chapter_count FROM threads WHERE id=:t"), {"t": tid}
        )
    assert cnt >= 1, "新建线必须包含触发它的事件"
    assert cc >= 1, "chapter_count 必须反映实际挂载数"


@pytest.mark.integration
async def test_attach_event_is_idempotent():
    """回归：同一 (thread, event) 重复挂载不报错、不产生重复行。"""
    from app.database import async_session
    from app.services.thread_router import _attach_event

    async with async_session() as s:
        row = await s.execute(
            text("SELECT thread_id, event_id FROM thread_events LIMIT 1")
        )
        got = row.first()
    if got is None:
        pytest.skip("无现有关联")

    tid, eid = got
    first = await _attach_event(tid, eid, 0.9)
    second = await _attach_event(tid, eid, 0.9)
    assert second is False, "重复挂载必须幂等跳过"

    async with async_session() as s:
        cnt = await s.scalar(
            text("SELECT COUNT(*) FROM thread_events WHERE thread_id=:t AND event_id=:e"),
            {"t": tid, "e": eid},
        )
    assert cnt == 1
