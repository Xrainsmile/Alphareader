"""Stock data & RS Rating API endpoints."""

from __future__ import annotations

import asyncio
import logging
import math
import traceback
from datetime import date, datetime
from enum import Enum

import numpy as np
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.indicators import compute_and_save_rs_rating, load_rs_rating, backfill_rs_rating
from app.services.data_fetcher import incremental_update_quotes, backfill_quotes

logger = logging.getLogger("alphareader.api.stocks")
router = APIRouter(prefix="/stocks", tags=["stocks"])


# ── Task State (in-memory, single worker) ──

class TaskStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class _TaskState:
    status: TaskStatus = TaskStatus.IDLE
    started_at: datetime | None = None
    finished_at: datetime | None = None
    count: int = 0
    error: str | None = None

    def reset(self):
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()
        self.finished_at = None
        self.count = 0
        self.error = None

    def complete(self, count: int):
        self.status = TaskStatus.COMPLETED
        self.finished_at = datetime.now()
        self.count = count
        self.error = None

    def fail(self, error: str):
        self.status = TaskStatus.FAILED
        self.finished_at = datetime.now()
        self.error = error


_task = _TaskState()


# ── Response Schemas ──

class RSRatingItem(BaseModel):
    ts_code: str
    name: str
    trade_date: date
    p3: float | None = None
    p6: float | None = None
    p9: float | None = None
    p12: float | None = None
    score: float | None = None
    rs_rating: int
    close: float | None = None
    pct_change: float | None = None
    change: float | None = None


class RSRatingResponse(BaseModel):
    count: int
    date: date
    items: list[RSRatingItem]


class StockSearchResponse(BaseModel):
    count: int
    date: date
    items: list[RSRatingItem]
    message: str | None = None


# ── Pinyin Initial Helper (zero-dependency) ──

# GB2312 一级汉字按拼音排序的声母分界点
_PINYIN_TABLE = (
    ("\u5416", "A"), ("\u82ad", "B"), ("\u64e6", "C"), ("\u6491", "D"),
    ("\u86fe", "E"), ("\u53d1", "F"), ("\u5676", "G"), ("\u54c8", "H"),
    ("\u4e0c", "J"), ("\u5494", "K"), ("\u5783", "L"), ("\u5988", "M"),
    ("\u62ff", "N"), ("\u5662", "O"), ("\u5991", "P"), ("\u671f", "Q"),
    ("\u7652", "R"), ("\u6492", "S"), ("\u584c", "T"), ("\u5140", "W"),
    ("\u5915", "X"), ("\u538b", "Y"), ("\u531d", "Z"),
)

def _pinyin_initial(ch: str) -> str:
    """Return the uppercase pinyin initial of a single Chinese character."""
    if "\u4e00" <= ch <= "\u9fff":
        for boundary, letter in reversed(_PINYIN_TABLE):
            if ch >= boundary:
                return letter
        return "A"
    if ch.isascii() and ch.isalpha():
        return ch.upper()
    return ""


def _name_to_initials(name: str) -> str:
    """Convert a stock name to its pinyin initials string. e.g. '贵州茅台' -> 'GZMT'"""
    return "".join(_pinyin_initial(c) for c in name)


# ── Endpoints ──

@router.get("/rs_rating", response_model=RSRatingResponse)
async def get_rs_rating(
    target_date: date | None = Query(None, description="查询日期，默认今天"),
    top_n: int = Query(100, ge=1, le=5000, description="返回前 N 名"),
    min_rating: int | None = Query(None, ge=1, le=99, description="最低 RS Rating"),
):
    """查询 RS Rating 排行榜。"""
    query_date = target_date or date.today()

    df = await load_rs_rating(
        target_date=query_date,
        top_n=top_n,
        min_rating=min_rating,
    )

    # NaN/inf → None，防止 JSON 序列化报错
    if not df.empty:
        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})

    items = [RSRatingItem(**row) for row in df.to_dict("records")] if not df.empty else []

    # 使用实际数据日期（可能回退到最近交易日）
    actual_date = items[0].trade_date if items else query_date

    return RSRatingResponse(
        count=len(items),
        date=actual_date,
        items=items,
    )


@router.get("/rs_rating/status")
async def get_compute_status():
    """查询后台计算任务的状态。"""
    result: dict = {
        "status": _task.status.value,
        "started_at": _task.started_at.isoformat() if _task.started_at else None,
        "finished_at": _task.finished_at.isoformat() if _task.finished_at else None,
    }
    if _task.status == TaskStatus.COMPLETED:
        result["count"] = _task.count
        result["message"] = f"RS Rating 计算完成，共 {_task.count} 只股票"
    elif _task.status == TaskStatus.FAILED:
        result["error"] = _task.error
    elif _task.status == TaskStatus.RUNNING:
        elapsed = (datetime.now() - _task.started_at).total_seconds() if _task.started_at else 0
        result["elapsed_seconds"] = round(elapsed, 1)
        result["message"] = "计算进行中，请稍后查询"
    return result


async def _run_compute(force: bool):
    """后台执行 RS Rating 计算（先增量更新行情数据）。"""
    try:
        _task.reset()
        # Step 1: 增量更新行情
        try:
            updated = await incremental_update_quotes(days=10)
            logger.info("行情增量更新完成: %d 条记录", updated)
        except Exception as e:
            logger.warning("行情增量更新失败（继续用已有数据计算）: %s", e)

        # Step 2: 计算 RS Rating
        logger.info("后台任务开始: RS Rating 计算 (force=%s)", force)
        df = await compute_and_save_rs_rating(force_refresh=force)
        _task.complete(len(df))
        logger.info("后台任务完成: RS Rating 计算，共 %d 只股票", len(df))
    except Exception as e:
        _task.fail(str(e))
        logger.error("后台任务失败: RS Rating 计算\n%s", traceback.format_exc())


@router.post("/rs_rating/compute")
async def trigger_rs_rating_compute(
    force: bool = Query(False, description="强制重新计算"),
):
    """手动触发 RS Rating 计算（后台任务，立即返回 202）。"""
    if _task.status == TaskStatus.RUNNING:
        return JSONResponse(
            status_code=409,
            content={
                "status": "conflict",
                "message": "已有计算任务在运行中，请通过 GET /rs_rating/status 查看进度",
                "started_at": _task.started_at.isoformat() if _task.started_at else None,
            },
        )

    logger.info("手动触发 RS Rating 计算 (force=%s)", force)
    asyncio.create_task(_run_compute(force))

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": "RS Rating 计算已在后台启动，请通过 GET /api/v1/stocks/rs_rating/status 查看进度",
        },
    )


@router.post("/update_quotes")
async def trigger_update_quotes(
    days: int = Query(10, ge=1, le=320, description="回溯天数"),
):
    """手动触发行情增量更新（后台任务）。"""
    async def _update():
        try:
            count = await incremental_update_quotes(days=days)
            logger.info("手动行情增量更新完成: %d 条", count)
        except Exception as e:
            logger.error("手动行情增量更新失败: %s", e)

    asyncio.create_task(_update())
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": f"行情增量更新已在后台启动（回溯 {days} 天）",
        },
    )


@router.get("/search", response_model=StockSearchResponse)
async def search_stocks(
    q: str = Query(..., min_length=1, max_length=20, description="搜索关键词（代码/名称/拼音首字母）"),
    target_date: date | None = Query(None, description="查询日期，默认今天"),
):
    """搜索股票 — 支持代码、名称、拼音首字母。

    在 RS Rating >= 80 的股票中搜索。
    若无结果，返回提示信息。
    """
    query_date = target_date or date.today()
    keyword = q.strip().upper()

    # 加载全量数据（无 min_rating 限制）以判断是否存在
    df_all = await load_rs_rating(target_date=query_date, top_n=5000)

    if df_all.empty:
        return StockSearchResponse(count=0, date=query_date, items=[], message=None)

    # NaN/inf → None，防止 JSON 序列化报错
    df_all = df_all.replace({np.nan: None, np.inf: None, -np.inf: None})

    actual_date = df_all["trade_date"].iloc[0]

    # 先在全量数据中搜索匹配项
    def _match(row) -> bool:
        code = str(row.get("ts_code", "")).upper()
        name = str(row.get("name", ""))
        initials = _name_to_initials(name)
        return (
            keyword in code
            or keyword in name.upper()
            or keyword in initials
        )

    records = df_all.to_dict("records")
    matched_all = [r for r in records if _match(r)]

    # 在匹配中筛选 RS >= 80
    matched_rs80 = [r for r in matched_all if (r.get("rs_rating") or 0) >= 80]

    if matched_rs80:
        # 排序：rs_rating DESC, pct_change DESC, close DESC
        matched_rs80.sort(
            key=lambda r: (
                r.get("rs_rating") or 0,
                r.get("pct_change") or -9999,
                r.get("close") or -9999,
            ),
            reverse=True,
        )
        items = [RSRatingItem(**r) for r in matched_rs80]
        return StockSearchResponse(count=len(items), date=actual_date, items=items)

    # 有匹配但都不在 RS >= 80 内
    if matched_all:
        return StockSearchResponse(
            count=0,
            date=actual_date,
            items=[],
            message=f"您搜索的标的 RS Rating ≤80",
        )

    # 完全无匹配
    return StockSearchResponse(
        count=0,
        date=actual_date,
        items=[],
        message=f"未找到匹配「{q.strip()}」的股票",
    )


@router.post("/rs_rating/backfill")
async def trigger_backfill(
    start_date: date = Query(..., description="起始日期"),
    end_date: date = Query(..., description="结束日期"),
    skip_existing: bool = Query(True, description="跳过已有数据的日期"),
):
    """回填指定日期范围的 RS Rating（后台任务）。

    对于非交易日，复制上一个最近交易日的数据。
    """
    if _task.status == TaskStatus.RUNNING:
        return JSONResponse(
            status_code=409,
            content={"status": "conflict", "message": "已有任务在运行中"},
        )

    async def _run():
        try:
            _task.reset()
            result = await backfill_rs_rating(start_date, end_date, skip_existing)
            total = result["computed"] + result["copied"]
            _task.complete(total)
            logger.info("回填完成: %s", result)
        except Exception as e:
            _task.fail(str(e))
            logger.error("回填失败: %s\n%s", e, traceback.format_exc())

    asyncio.create_task(_run())
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": f"RS Rating 回填已启动: {start_date} ~ {end_date}",
        },
    )


@router.post("/quotes/backfill")
async def trigger_quotes_backfill(
    start_date: str = Query(..., description="起始日期 YYYYMMDD"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD"),
):
    """回填指定日期范围的历史行情数据（后台任务，使用 akshare）。

    耗时较长（每只股票约 0.5~1 秒，5000+ 只约 1~2 小时）。
    """
    if _task.status == TaskStatus.RUNNING:
        return JSONResponse(
            status_code=409,
            content={"status": "conflict", "message": "已有任务在运行中"},
        )

    async def _run():
        try:
            _task.reset()
            result = await backfill_quotes(start_date, end_date)
            _task.complete(result["total_stocks"])
            logger.info("行情回填完成: %s", result)
        except Exception as e:
            _task.fail(str(e))
            logger.error("行情回填失败: %s\n%s", e, traceback.format_exc())

    asyncio.create_task(_run())
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": f"历史行情回填已启动: {start_date} ~ {end_date}",
        },
    )


# ── VCP 策略白名单 ──

class VCPWatchlistItem(BaseModel):
    """VCP 白名单单条记录。"""
    ts_code: str
    name: str | None = None
    current_price: float | None = None
    vcp_score: float | None = None
    eps_growth: float | None = None
    revenue_yoy: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    ema120: float | None = None
    industry: str | None = None
    concepts: str | None = None
    main_business: str | None = None
    fund_flow_net: float | None = None
    futu_url: str | None = None


class VCPWatchlistResponse(BaseModel):
    """VCP 白名单响应。"""
    count: int
    date: date
    items: list[VCPWatchlistItem]


def _generate_futu_url(ts_code: str) -> str:
    """根据 A 股代码生成富途牛牛网页版报价链接。

    格式: https://www.futunn.com/stock/{code}-{market}
    沪市(6开头) → -SH, 深市(0/3开头) → -SZ
    """
    code = ts_code.replace(".SZ", "").replace(".SH", "").strip()
    market = "SH" if code.startswith("6") else "SZ"
    return f"https://www.futunn.com/stock/{code}-{market}"


class VCPFilterOptions(BaseModel):
    """VCP 白名单可用的行业和概念枚举值。"""
    industries: list[str]
    concepts: list[str]


@router.get("/vcp_watchlist/filters", response_model=VCPFilterOptions)
async def get_vcp_filter_options(
    target_date: date | None = Query(None, description="查询日期，默认最新"),
):
    """获取 VCP 白名单中可用的行业和概念板块枚举值（用于前端筛选器）。"""
    from sqlalchemy import select, func as sa_func

    from app.database import async_session
    from app.models.screener import WatchlistDaily

    async with async_session() as session:
        if target_date:
            query_date = target_date
        else:
            max_date_q = await session.execute(
                select(sa_func.max(WatchlistDaily.run_date))
            )
            query_date = max_date_q.scalar()
            if not query_date:
                return VCPFilterOptions(industries=[], concepts=[])

        # 查询所有行业（去重去空排序）
        ind_stmt = (
            select(sa_func.distinct(WatchlistDaily.industry))
            .where(WatchlistDaily.run_date == query_date)
            .where(WatchlistDaily.industry.isnot(None))
            .where(WatchlistDaily.industry != "")
            .order_by(WatchlistDaily.industry)
        )
        ind_result = await session.execute(ind_stmt)
        industries = [r[0] for r in ind_result.all()]

        # 查询所有概念（拆分逗号分隔值，去重排序）
        con_stmt = (
            select(WatchlistDaily.concepts)
            .where(WatchlistDaily.run_date == query_date)
            .where(WatchlistDaily.concepts.isnot(None))
            .where(WatchlistDaily.concepts != "")
        )
        con_result = await session.execute(con_stmt)
        concept_set: set[str] = set()
        for (raw,) in con_result.all():
            for c in raw.split(","):
                c = c.strip()
                if c:
                    concept_set.add(c)
        concepts = sorted(concept_set)

    return VCPFilterOptions(industries=industries, concepts=concepts)


@router.get("/vcp_watchlist", response_model=VCPWatchlistResponse)
async def get_vcp_watchlist(
    target_date: date | None = Query(None, description="查询日期，默认最新"),
    industry: str | None = Query(None, description="行业筛选，多个用逗号分隔"),
    concepts: str | None = Query(None, description="概念板块筛选，多个用逗号分隔（包含任一即匹配）"),
):
    """查询 VCP 策略白名单。

    返回最新一期（或指定日期）的 Screener 白名单，
    含技术面指标、基本面指标、行业题材、资金流向等维度。
    支持按行业和概念板块筛选。
    """
    from sqlalchemy import select, func as sa_func, or_

    from app.database import async_session
    from app.models.screener import WatchlistDaily

    async with async_session() as session:
        # 确定查询日期：用户指定或取最新
        if target_date:
            query_date = target_date
        else:
            max_date_q = await session.execute(
                select(sa_func.max(WatchlistDaily.run_date))
            )
            query_date = max_date_q.scalar()
            if not query_date:
                return VCPWatchlistResponse(count=0, date=date.today(), items=[])

        # 查询白名单（兜底排除 ST 股票）
        stmt = (
            select(WatchlistDaily)
            .where(WatchlistDaily.run_date == query_date)
            .where(
                ~WatchlistDaily.name.like("%ST%")
                | WatchlistDaily.name.is_(None)
            )
        )

        # 行业筛选
        if industry:
            ind_list = [i.strip() for i in industry.split(",") if i.strip()]
            if ind_list:
                stmt = stmt.where(WatchlistDaily.industry.in_(ind_list))

        # 概念板块筛选（包含任一即匹配）
        if concepts:
            con_list = [c.strip() for c in concepts.split(",") if c.strip()]
            if con_list:
                concept_conditions = [
                    WatchlistDaily.concepts.like(f"%{c}%") for c in con_list
                ]
                stmt = stmt.where(or_(*concept_conditions))

        stmt = stmt.order_by(WatchlistDaily.vcp_score.desc().nulls_last())
        result = await session.execute(stmt)
        rows = result.scalars().all()

    items = []
    for row in rows:
        item = VCPWatchlistItem(
            ts_code=row.ts_code,
            name=row.name,
            current_price=row.current_price,
            vcp_score=row.vcp_score,
            eps_growth=row.eps_growth,
            revenue_yoy=row.revenue_yoy,
            ema20=row.ema20,
            ema50=row.ema50,
            ema120=row.ema120,
            industry=row.industry,
            concepts=row.concepts,
            main_business=row.main_business,
            fund_flow_net=row.fund_flow_net,
            futu_url=_generate_futu_url(row.ts_code),
        )
        items.append(item)

    return VCPWatchlistResponse(
        count=len(items),
        date=query_date,
        items=items,
    )


# ── 价投策略白名单 ──

class ValueStockItem(BaseModel):
    """价投白名单单条记录。"""
    id: int
    ts_code: str
    name: str | None = None
    status: str  # watching / holding
    reason: str | None = None
    industry: str | None = None
    concepts: str | None = None
    current_price: float | None = None
    futu_url: str | None = None
    added_at: str | None = None


class ValueWatchlistResponse(BaseModel):
    """价投白名单响应。"""
    count: int
    items: list[ValueStockItem]


@router.get("/value_watchlist", response_model=ValueWatchlistResponse)
async def get_value_watchlist():
    """查询价投策略白名单。

    返回所有 strategy='value' 且未退出的观察池股票，
    附带行业、概念板块（从最新 WatchlistDaily 或行情表获取）。
    """
    from sqlalchemy import select, desc as sa_desc

    from app.database import async_session
    from app.models.sandbox import SandboxStock
    from app.models.screener import WatchlistDaily
    from app.models.stock import StockDailyQuote

    async with async_session() as session:
        # 查询所有价投策略标的（排除已退出）
        stmt = (
            select(SandboxStock)
            .where(SandboxStock.strategy == "value")
            .where(SandboxStock.status != "exited")
            .order_by(sa_desc(SandboxStock.updated_at))
        )
        result = await session.execute(stmt)
        stocks = result.scalars().all()

        if not stocks:
            return ValueWatchlistResponse(count=0, items=[])

        ts_codes = [s.ts_code for s in stocks]

        # 尝试从最新 WatchlistDaily 获取行业和概念信息
        from sqlalchemy import func as sa_func
        max_date_q = await session.execute(
            select(sa_func.max(WatchlistDaily.run_date))
        )
        latest_date = max_date_q.scalar()

        watchlist_map: dict[str, dict] = {}
        if latest_date:
            wl_result = await session.execute(
                select(WatchlistDaily)
                .where(WatchlistDaily.run_date == latest_date)
                .where(WatchlistDaily.ts_code.in_(ts_codes))
            )
            for wl in wl_result.scalars().all():
                watchlist_map[wl.ts_code] = {
                    "industry": wl.industry,
                    "concepts": wl.concepts,
                    "current_price": wl.current_price,
                }

        # 对于 WatchlistDaily 中没有的标的，从行情表获取最新收盘价
        missing_codes = [c for c in ts_codes if c not in watchlist_map]
        quote_map: dict[str, float] = {}
        if missing_codes:
            for code in missing_codes:
                q_result = await session.execute(
                    select(StockDailyQuote.close)
                    .where(StockDailyQuote.ts_code == code)
                    .order_by(sa_desc(StockDailyQuote.trade_date))
                    .limit(1)
                )
                price = q_result.scalar()
                if price is not None:
                    quote_map[code] = float(price)

    items = []
    for s in stocks:
        wl_info = watchlist_map.get(s.ts_code, {})
        price = wl_info.get("current_price")
        if price is None:
            price = quote_map.get(s.ts_code)

        items.append(ValueStockItem(
            id=s.id,
            ts_code=s.ts_code,
            name=s.name,
            status=s.status,
            reason=s.reason,
            industry=wl_info.get("industry"),
            concepts=wl_info.get("concepts"),
            current_price=price,
            futu_url=_generate_futu_url(s.ts_code),
            added_at=s.added_at.isoformat() if s.added_at else None,
        ))

    return ValueWatchlistResponse(count=len(items), items=items)


# ── 价投标的管理（密码保护） ──

class ValueStockAddRequest(BaseModel):
    """添加价投标的请求。"""
    ts_code: str
    name: str = ""
    reason: str | None = None
    password: str  # 使用 Sandbox 密码验证


class ValueStockDeleteRequest(BaseModel):
    """删除价投标的请求。"""
    password: str


@router.post("/value_watchlist/add")
async def add_value_stock(body: ValueStockAddRequest):
    """添加价投策略标的。需要 Sandbox 访问密码。"""
    import hmac

    from sqlalchemy import select

    from app.config import settings
    from app.database import async_session
    from app.models.sandbox import SandboxStock

    # 密码验证
    expected = settings.SANDBOX_PASSWORD
    if expected and not hmac.compare_digest(body.password.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="密码错误")

    async with async_session() as session:
        # 检查重复（包含已退出的，允许重新添加）
        existing = await session.execute(
            select(SandboxStock).where(
                SandboxStock.ts_code == body.ts_code,
                SandboxStock.strategy == "value",
                SandboxStock.status != "exited",
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"{body.ts_code} 已在价投白名单中")

        stock = SandboxStock(
            ts_code=body.ts_code,
            name=body.name,
            reason=body.reason,
            strategy="value",
            status="watching",
        )
        session.add(stock)
        await session.commit()
        await session.refresh(stock)

    return {"ok": True, "id": stock.id, "ts_code": stock.ts_code, "name": stock.name}


@router.delete("/value_watchlist/{stock_id}")
async def remove_value_stock(stock_id: int, body: ValueStockDeleteRequest):
    """移除价投标的（标记为 exited）。需要 Sandbox 访问密码。"""
    import hmac

    from app.config import settings
    from app.database import async_session
    from app.models.sandbox import SandboxStock

    expected = settings.SANDBOX_PASSWORD
    if expected and not hmac.compare_digest(body.password.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="密码错误")

    async with async_session() as session:
        stock = await session.get(SandboxStock, stock_id)
        if not stock or stock.strategy != "value":
            raise HTTPException(status_code=404, detail="标的不存在")
        stock.status = "exited"
        await session.commit()

    return {"ok": True}
