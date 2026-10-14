"""Shared fixtures for AlphaReader tests.

Provides:
  - Async test support via pytest-asyncio
  - Isolated in-memory SQLite DB for API tests (with PG type adaptors)
  - Mocked Redis for tests that touch Redis
  - FastAPI TestClient via httpx
"""

from __future__ import annotations

# ══════════════ 测试库强制隔离（2026-10-14 事故后新增）══════════════
#
# 事故：在 alpha-web 生产容器内跑 pytest，容器由 docker-compose 的 env_file
# 注入了 POSTGRES_HOST=db / DATABASE_URL=@db:5432/alphareader，测试直连生产库，
# INSERT 打在真实表上（news_events 不存在、events.occurred_at 不存在、
# thread_operations 违反 CHECK），4 条 ERROR 计入巡检并触发企微告警。
# 所幸事务回滚、无脏数据落库——但生产库不该被测试触碰，一次例外就可能真写入。
#
# 策略：必须在 `from app.database import ...` 之前改写环境变量，
# 让 Settings（computed_field）与 os.getenv 两条通路都拿到测试库。
#   · 设 TEST_DATABASE_URL → 显式指定测试库（推荐，可指独立 PG 实例）
#   · 未设 → 降级本地 127.0.0.1 + alphareader_test，并清除 DATABASE_URL
#     （清除后 integration 标记的测试自动 skip，不会误连）
#   · 确需真连生产：ALPHAREADER_TEST_ALLOW_PROD_DB=1（须本人明确确认）
import os

_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def _enforce_test_db_isolation() -> None:
    """把测试会话的 DB 目标强制隔离到非生产库（import app 之前执行）。"""
    if os.getenv("ALPHAREADER_TEST_ALLOW_PROD_DB") == "1":
        print(
            "[conftest] ⚠️  ALPHAREADER_TEST_ALLOW_PROD_DB=1"
            " —— 本次测试将直连当前 DB，请确认不是生产！"
        )
        return

    host = (os.getenv("POSTGRES_HOST") or "").strip()
    if host in _LOCAL_HOSTS:
        return  # 本机开发库，无需干预

    test_url = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if test_url:
        from urllib.parse import urlparse

        p = urlparse(test_url)
        db_name = p.path.lstrip("/") if p.path else "?"
        if p.hostname:
            os.environ["POSTGRES_HOST"] = p.hostname
        if p.port:
            os.environ["POSTGRES_PORT"] = str(p.port)
        if db_name != "?":
            os.environ["POSTGRES_DB"] = db_name
        if p.username:
            os.environ["POSTGRES_USER"] = p.username
        if p.password:
            os.environ["POSTGRES_PASSWORD"] = p.password
        os.environ["DATABASE_URL"] = test_url
        print(f"[conftest] 测试库已隔离 → {p.hostname}/{db_name}（来自 TEST_DATABASE_URL）")
        return

    # 未显式配置：退到本地同名 test 库，并清掉 DATABASE_URL 让 integration 测试 skip
    os.environ["POSTGRES_HOST"] = "127.0.0.1"
    os.environ["POSTGRES_DB"] = os.getenv("POSTGRES_TEST_DB", "alphareader_test")
    os.environ.pop("DATABASE_URL", None)
    print(
        "[conftest] ⚠️  检测到非本地数据库（POSTGRES_HOST=%s），已强制隔离：\n"
        "              POSTGRES_HOST=127.0.0.1  POSTGRES_DB=%s  DATABASE_URL 已清除\n"
        "              integration 测试将自动 skip；指定测试库请设 TEST_DATABASE_URL。"
        % (host, os.environ["POSTGRES_DB"])
    )


_enforce_test_db_isolation()

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import String, TypeDecorator, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db


# ── SQLite ↔ PostgreSQL type adaptors ──
from sqlalchemy.dialects.postgresql import ARRAY, UUID, JSONB, TSVECTOR
from sqlalchemy.ext.compiler import compiles


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(TSVECTOR, "sqlite")
def _compile_tsvector_sqlite(type_, compiler, **kw):
    return "TEXT"


# ── 类型编译器补丁（2026-10-13 修复 13 个存量 CompileError）──
#
# 为什么需要：`@compiles(ARRAY, "sqlite")` 只注册了 DDL 编译器，而
# SQLiteTypeCompiler 渲染列规格时走类型编译器通路，找 visit_ARRAY，
# 没有就抛 "can't render element of type ARRAY"，导致 conftest 一
# create_all 就在 entities.aliases 列炸掉、13 个 API 测试 setup 全 ERROR。
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"
if not hasattr(SQLiteTypeCompiler, "visit_TSVECTOR"):
    SQLiteTypeCompiler.visit_TSVECTOR = lambda self, type_, **kw: "TEXT"
if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
    SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"


# ── UUID 值处理：SQLite 存 CHAR(36)，需 str 化 ──
_orig_uuid_bind = UUID.bind_processor


def _uuid_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            return None if value is None else str(value)
        return process
    if _orig_uuid_bind:
        return _orig_uuid_bind(self, dialect)
    return None


UUID.bind_processor = _uuid_bind_processor


# ═══════════════════ 后台线程退出机制（2026-10-13 根治）═══════════════════
#
# 问题：aiosqlite core.py:90 创建连接工作线程时未设 daemon=True，
# 测试跑完后线程仍阻塞事务队列，解释器停在 threading._shutdown 永久等待，
# 表现为「结果已输出但进程不退出」。
#
# 双保险：daemon 补丁保证绝不再卡死；atexit 钩子给线程优雅收尾机会。
import atexit
import threading

_stop_event = threading.Event()
_patched_threads: list = []
_orig_thread_cls = threading.Thread


class _DaemonThread(_orig_thread_cls):
    """强制 daemon 的线程包装，专用于第三方库（aiosqlite）后台工作线程。"""

    def __init__(self, *args, **kwargs):
        kwargs["daemon"] = True
        super().__init__(*args, **kwargs)


def _patch_aiosqlite_daemon_threads():
    """把 aiosqlite.core 的 Thread 替换为 daemon 版本（不动全局）。"""
    try:
        import aiosqlite.core as _core
    except Exception:
        return
    if getattr(_core, "_ar_daemon_patched", False):
        return
    _core.Thread = _DaemonThread
    _core._ar_daemon_patched = True
    _patched_threads.extend(
        t for t in threading.enumerate()
        if getattr(t, "_target", None) is not None
        and "aiosqlite" in str(getattr(t._target, "__module__", ""))
    )


def _atexit_cleanup():
    """退出兜底：置 stop 信号，join(timeout=5)，超时由 daemon 兜住。"""
    _stop_event.set()
    for t in list(_patched_threads):
        if t.is_alive() and t is not threading.current_thread():
            t.join(timeout=5)


_patch_aiosqlite_daemon_threads()
atexit.register(_atexit_cleanup)


# Patch ARRAY so SQLite can bind/result-process list ↔ JSON string
_orig_array_bind = ARRAY.bind_processor
_orig_array_result = ARRAY.result_processor


def _array_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return None
            return json.dumps(value)
        return process
    if _orig_array_bind:
        return _orig_array_bind(self, dialect)
    return None


def _array_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return None
            return json.loads(value)
        return process
    if _orig_array_result:
        return _orig_array_result(self, dialect, coltype)
    return None


ARRAY.bind_processor = _array_bind_processor
ARRAY.result_processor = _array_result_processor


# ── In-memory SQLite async engine for isolation ──
# StaticPool 保证同一连接复用，避免每个测试新建连接导致 aiosqlite 线程堆积。
from sqlalchemy.pool import StaticPool

_test_engine = create_async_engine(
    "sqlite+aiosqlite:///",  # in-memory
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)


# ── SQLite 兼容函数注册（2026-10-13 修复）──
# 模型 CHECK 约束直接写了 PG 函数：length(btrim(assertion)) > 0。
# SQLite 无 btrim，create_all 时报 "no such function: btrim"，
# 导致 13 个 API 测试 setup 全挂。这里注册同名兼容函数，仅影响测试内存库。
def _register_sqlite_compat_functions(dbapi_conn, _record):
    try:
        dbapi_conn.create_function("btrim", 1, lambda s: None if s is None else s.strip())
        dbapi_conn.create_function("btrim", 2, lambda s, c: None if s is None else s.strip(c))
    except Exception:
        pass


event.listens_for(_test_engine.sync_engine, "connect")(
    _register_sqlite_compat_functions
)


@pytest.fixture(scope="session", autouse=True)
async def _setup_db():
    """会话级建表一次，结束后销毁并释放连接。

    为什么从 per-test 改为 session 级（2026-10-13 修复）：
    原 autouse 每个测试都 create_all + drop_all（40+ 张表），且每次建连
    拉起 aiosqlite 后台线程、结束时不 join，导致进程跑完用例后卡在
    threading._shutdown 不退出。会话级建表 + 显式 dispose 解决。
    """
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


@pytest.fixture(autouse=True)
async def _skip_integration_without_pg(request):
    """integration 标记的测试在无真实 PostgreSQL 时自动跳过。

    为什么需要（2026-10-13 修复）：`@pytest.mark.integration` 只是标记，
    本身不产生跳过行为。这些测试直接 `from app.database import async_session`
    用 asyncpg 连真实库（SQL 里是 PG 的 `$1` 占位符），在 SQLite 内存库上
    必然报错。此前它们依赖环境恰好有 DATABASE_URL 才能跑，
    换台机器就变成"莫名其妙的失败"。

    统一在这里按标记 + 环境变量判断，让"没配 PG"表现为 skip 而非 failed，
    失败只留给真正的问题。
    """
    if "integration" in request.keywords:
        import os

        url = os.getenv("DATABASE_URL", "")
        if "postgresql" not in url:
            pytest.skip("integration 测试需要真实 PostgreSQL（设置 DATABASE_URL）")


@pytest.fixture(autouse=True)
async def _clean_tables():
    """每个测试后清数据保证隔离（用 DELETE 而非 DDL，避免反复建连）。"""
    yield
    async with _test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    # 清理全局 asyncpg 引擎（2026-10-13 修复）：
    # app.database.engine 是模块级单例、绑 asyncpg 连接池。pytest-asyncio
    # 每个用例用不同事件循环，前一个借出的连接仍绑在已关闭循环上，下一个
    # 复用时报 "Event loop is closed" / "attached to a different loop"。
    from app import database as _db

    eng = getattr(_db, "engine", None)
    if eng is not None:
        try:
            await eng.dispose()
        except Exception:
            pass


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an isolated async DB session for direct DB tests."""
    async with _TestSession() as session:
        yield session


@pytest.fixture
def mock_redis():
    """Return an AsyncMock that mimics a Redis client."""
    r = AsyncMock()
    r.ping.return_value = True
    r.hgetall.return_value = {}
    r.sadd.return_value = 1
    r.sismember.return_value = False
    r.smembers.return_value = set()
    r.delete.return_value = 1
    r.pipeline.return_value = AsyncMock()
    return r


@pytest.fixture
async def client(mock_redis) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client hitting the real FastAPI app with test DB + mock Redis."""
    from app.main import app
    from app.config import settings

    # Override dependencies
    async def _override_get_db():
        async with _TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    # Disable API key auth in tests (avoid depending on local .env)
    original_api_key = settings.NEWS_API_KEY
    settings.NEWS_API_KEY = ""

    # Patch redis at module level
    import app.redis as redis_mod
    original_pool = redis_mod.redis_pool
    redis_mod.redis_pool = mock_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    # Restore
    settings.NEWS_API_KEY = original_api_key
    redis_mod.redis_pool = original_pool
    app.dependency_overrides.clear()
