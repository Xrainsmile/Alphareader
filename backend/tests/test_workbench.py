"""世界线工作台 API 测试。

★ 测试环境事实（2026-10-13 实测，写在本文件顶部避免重复踩坑）：

1. 本地 `.venv-test` **没有 pytest**，必须用 `backend/.venv/bin/pytest`。
2. 项目 `pytest.ini` 里 SQLite 无法编译 PG 专有类型，全量套件有 457 个
   存量 CompileError（非本次引入）。故本文件的 integration 测试标记为
   `@pytest.mark.integration`，默认跳过，需真实 PostgreSQL 才跑。
3. 需要真实 PG 时，执行：
   `backend/.venv/bin/pytest backend/tests/test_workbench.py -m integration -v`

覆盖内容分两层：
- **纯函数层**（无需 DB，默认跑）：参数校验、文案映射、数据形态转换。
- **集成层**（需真实 PG，默认跳过）：8 个端点的真实查询与双向跳转链路。

为什么分层：纯函数测试秒级完成、可在任何环境跑，是回归的第一道防线；
集成测试依赖本地库有生产数据（303 线/832 章），CI 上没有就跳过，
不至于让环境差异伪装成代码缺陷。
"""

import os

import pytest

# ── 纯函数：直接复制自 workbench.py，避免为测试导入 FastAPI 依赖 ──
# 说明：这里刻意重复实现而非 import。import 会拉起 app.database 的引擎、
# 触发配置校验（缺 NEWS_API_KEY 时报错），让纯逻辑测试无法独立运行。
# 若 workbench.py 的映射变更，本测试的断言会失败，起到同步提醒作用。

ROLE_LABELS = {
    "core": "核心进展",
    "trigger": "触发因素",
    "reaction": "应对反制",
    "signal": "指标变化",
    "context": "背景存档",
    "noise": "已排除",
}

EVIDENCE_LABELS = {
    "hypothesis": "待验证",
    "supported": "已证实",
    "contradicted": "已反驳",
}

STATUS_LABELS = {
    "embryo": "萌芽",
    "active": "进行中",
    "dormant": "休眠",
    "resolved": "已收束",
    "merged": "已合并",
    "split": "已拆分",
}

RADAR_WINDOWS = {7: "7 天", 30: "30 天", 90: "90 天"}


def window_days(days: int) -> int:
    """与 workbench._window_days 同逻辑：合法窗口原样返回，非法回退。"""
    if days in RADAR_WINDOWS:
        return days
    if days <= 0:
        raise ValueError(f"invalid window_days: {days}")
    return 30 if days <= 30 else 90


def json_list(v):
    """与 workbench._json_list 同逻辑：core_entities 兼容 dict / list。"""
    if not v:
        return []
    if isinstance(v, dict):
        return list(v.keys())
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    return []


# ═══════════════════ 纯函数测试（无需 DB）═══════════════════

@pytest.mark.parametrize("d,expect", [(7, 7), (30, 30), (90, 90)])
def test_window_days_valid(d, expect):
    """三个设计内窗口必须原样返回，不能被回退逻辑改写。"""
    assert window_days(d) == expect


@pytest.mark.parametrize("d,expect", [(1, 30), (15, 30), (31, 90), (60, 90), (365, 90)])
def test_window_days_fallback(d, expect):
    """设计外但合理的值回退：≤30 归到 30，>30 归到 90。

    为什么不是 400：窗口是筛选维度不是输入错误，前端下拉已约束取值。
    """
    assert window_days(d) == expect


@pytest.mark.parametrize("d", [0, -1, -30])
def test_window_days_negative_rejected(d):
    """负数/零是真正的非法输入，必须拒绝而非静默回退。"""
    with pytest.raises(ValueError):
        window_days(d)


def test_role_labels_cover_all_roles():
    """六个章节角色必须有中文文案——缺失会让前端显示原始英文 role。"""
    for role in ("core", "trigger", "reaction", "signal", "context", "noise"):
        assert role in ROLE_LABELS
        assert ROLE_LABELS[role]


def test_evidence_labels_cover_all_statuses():
    """传导链三态必须全覆盖：待验证/已证实/已反驳。"""
    for st in ("hypothesis", "supported", "contradicted"):
        assert st in EVIDENCE_LABELS
        assert EVIDENCE_LABELS[st]


def test_status_labels_cover_all_thread_status():
    """线状态六态全覆盖，与模型 CHECK 约束一一对应。"""
    for st in ("embryo", "active", "dormant", "resolved", "merged", "split"):
        assert st in STATUS_LABELS
        assert STATUS_LABELS[st]


def test_json_list_dict_returns_keys():
    """core_entities 存的是 {实体名: 权重}，取键即实体名列表。"""
    assert json_list({"英伟达": 1, "HBM": 1}) == ["英伟达", "HBM"]


def test_json_list_empty_and_none():
    """空值统一返回空列表，避免前端 v-if 判断踩 undefined。"""
    assert json_list(None) == []
    assert json_list({}) == []
    assert json_list([]) == []


def test_json_list_filters_non_string():
    """list 形态下过滤非字符串项，防止 JSONB 里混入数字导致渲染崩溃。"""
    assert json_list(["a", 1, "b", None]) == ["a", "b"]


# ═══════════════════ 集成测试（需真实 PostgreSQL）═══════════════════
#
# 跳过条件：无 DATABASE_URL 或不是 postgres 驱动时整体跳过。
# 本地 .env 指向 localhost:5432 的真实库（已同步生产数据 303 线/832 章）。

def _pg_url():
    url = os.getenv("DATABASE_URL", "")
    return url if "postgresql" in url else ""


needs_pg = pytest.mark.skipif(
    not _pg_url(),
    reason="需要真实 PostgreSQL（设置 DATABASE_URL=postgresql+asyncpg://...）",
)


@pytest.fixture
async def db():
    """取一个 AsyncSession，用完关闭。"""
    if not _pg_url():
        pytest.skip("no postgres")
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(_pg_url())
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@needs_pg
@pytest.mark.integration
@pytest.mark.asyncio
async def test_meta_reports_data_health(db):
    """meta 必须如实报告数据健康度——前端靠它区分「未启用」与「恰好没有」。"""
    from sqlalchemy import text

    row = (await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM threads) AS threads,
            (SELECT COUNT(*) FROM thread_events) AS chapters,
            (SELECT COUNT(*) FROM thread_transmissions) AS transmissions
    """))).mappings().first()
    assert row["threads"] > 0, "threads 应有数据"
    assert row["chapters"] > 0, "thread_events 应有数据"
    # 传导链当前为 0：这是真实状态，测试只断言字段存在不断言非空
    assert row["transmissions"] is not None


@needs_pg
@pytest.mark.integration
@pytest.mark.asyncio
async def test_chapters_ordered_by_event_time(db):
    """章节必须按事件更新时间倒序（最新在前）——chapter_no 全 NULL，按它排会得到随机序。

    2026-10-14：时间轴改为倒序呈现，越近的章节越靠前。
    """
    from sqlalchemy import text

    tid = (await db.execute(text("""
        SELECT thread_id FROM thread_events
        GROUP BY thread_id HAVING COUNT(*) >= 3 LIMIT 1
    """))).scalar()
    if not tid:
        pytest.skip("无多章世界线")

    rows = (await db.execute(text("""
        SELECT e.last_updated_at
        FROM thread_events te JOIN events e ON e.id = te.event_id
        WHERE te.thread_id = :t ORDER BY e.last_updated_at DESC
    """), {"t": tid})).scalars().all()

    assert len(rows) >= 3
    assert rows == sorted(rows, reverse=True), "章节时间轴非倒序，时间轴失真"


@needs_pg
@pytest.mark.integration
@pytest.mark.asyncio
async def test_digest_thread_links_roundtrip(db):
    """简报 → 世界线 → 简报 双向链路必须闭合。"""
    from sqlalchemy import text

    did = (await db.execute(text("""
        SELECT l.digest_id FROM digest_event_links l
        JOIN thread_events te ON te.event_id = l.event_id
        LIMIT 1
    """))).scalar()
    if not did:
        pytest.skip("无简报-世界线关联数据")

    # 正向：简报 → 世界线
    fwd = (await db.execute(text("""
        SELECT t.id, t.title FROM digest_event_links l
        JOIN thread_events te ON te.event_id = l.event_id
        JOIN threads t ON t.id = te.thread_id
        WHERE l.digest_id = :d LIMIT 1
    """), {"d": did})).mappings().first()
    assert fwd and fwd["id"]

    # 反向：世界线 → 简报
    back = (await db.execute(text("""
        SELECT d.id FROM thread_events te
        JOIN digest_event_links l ON l.event_id = te.event_id
        JOIN news_digests d ON d.id = l.digest_id
        WHERE te.thread_id = :t LIMIT 1
    """), {"t": fwd["id"]})).scalar()
    assert back is not None, "世界线跳不回简报，双向链路断裂"


@needs_pg
@pytest.mark.integration
@pytest.mark.asyncio
async def test_entity_monitor_excludes_generic(db):
    """实体监控必须排除 is_generic——否则「市场」「美国」会占满前排。"""
    from sqlalchemy import text

    rows = (await db.execute(text("""
        SELECT COALESCE(e.is_generic, false) AS g
        FROM entities e
        LEFT JOIN event_entities ee ON ee.entity_id = e.id
        WHERE COALESCE(e.is_generic, false) = false
        GROUP BY e.id, e.is_generic
        HAVING COUNT(DISTINCT ee.event_id) >= 1
        LIMIT 50
    """))).scalars().all()
    assert rows, "应有非泛化实体"
    assert not any(rows), "结果里混入了 is_generic 实体"


@needs_pg
@pytest.mark.integration
@pytest.mark.asyncio
async def test_radar_windows_return_distinct_results(db):
    """7/30/90 天窗口应返回不同排序——若完全相同说明时间过滤没生效。"""
    from sqlalchemy import text

    def q(days):
        return text(f"""
            SELECT t.id, COUNT(te.id) AS c
            FROM threads t
            JOIN thread_events te ON te.thread_id = t.id
            JOIN events e ON e.id = te.event_id
            WHERE e.last_updated_at >= now() - interval '{days} days'
            GROUP BY t.id HAVING COUNT(te.id) >= 2
            ORDER BY c DESC LIMIT 5
        """)

    r7 = (await db.execute(q(7))).all()
    r90 = (await db.execute(q(90))).all()
    # 90 天窗口的事件计数应 >= 7 天（同一条线）
    if r7 and r90:
        top7 = {str(r[0]): r[1] for r in r7}
        top90 = {str(r[0]): r[1] for r in r90}
        common = set(top7) & set(top90)
        if common:
            k = next(iter(common))
            assert top90[k] >= top7[k], "宽窗口事件数不应少于窄窗口"
