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
from app.schemas.response import APIResponse

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

@router.get("/rs_rating")
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

    items = [RSRatingItem(**row).model_dump() for row in df.to_dict("records")] if not df.empty else []

    # 使用实际数据日期（可能回退到最近交易日）
    actual_date = df.iloc[0]["trade_date"] if not df.empty else query_date

    return APIResponse(data={
        "count": len(items),
        "date": str(actual_date),
        "items": items,
    })


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
    return APIResponse(data=result)


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
                "code": 1,
                "message": "已有计算任务在运行中，请通过 GET /rs_rating/status 查看进度",
                "data": {
                    "status": "conflict",
                    "started_at": _task.started_at.isoformat() if _task.started_at else None,
                },
            },
        )

    logger.info("手动触发 RS Rating 计算 (force=%s)", force)
    asyncio.create_task(_run_compute(force))

    return JSONResponse(
        status_code=202,
        content={
            "code": 0,
            "message": "RS Rating 计算已在后台启动，请通过 GET /api/v1/stocks/rs_rating/status 查看进度",
            "data": {"status": "accepted"},
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
            "code": 0,
            "message": f"行情增量更新已在后台启动（回溯 {days} 天）",
            "data": {"status": "accepted"},
        },
    )


@router.post("/us/update_quotes")
async def trigger_us_update_quotes(
    days: int = Query(10, ge=1, le=365, description="回溯天数"),
    force: bool = Query(False, description="强制全量下载"),
):
    """手动触发美股行情更新（后台任务）。"""
    from app.services.us_data_fetcher import incremental_update_us_quotes, get_all_us_stock_data

    async def _update():
        try:
            if force:
                df = await get_all_us_stock_data(force_refresh=True)
                logger.info("美股全量下载完成: %d 条", len(df))
            else:
                count = await incremental_update_us_quotes(days=days)
                logger.info("美股增量更新完成: %d 条", count)
        except Exception as e:
            logger.error("美股行情更新失败: %s", e)

    asyncio.create_task(_update())
    return JSONResponse(
        status_code=202,
        content={
            "code": 0,
            "message": f"美股行情{'全量下载' if force else f'增量更新（回溯 {days} 天）'}已在后台启动",
            "data": {"status": "accepted"},
        },
    )


@router.get("/search")
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
        return APIResponse(data={"count": 0, "date": str(query_date), "items": [], "message": None})

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
        items = [RSRatingItem(**r).model_dump() for r in matched_rs80]
        return APIResponse(data={"count": len(items), "date": str(actual_date), "items": items})

    # 有匹配但都不在 RS >= 80 内
    if matched_all:
        return APIResponse(data={
            "count": 0,
            "date": str(actual_date),
            "items": [],
            "message": "您搜索的标的 RS Rating ≤80",
        })

    # 完全无匹配
    return APIResponse(data={
        "count": 0,
        "date": str(actual_date),
        "items": [],
        "message": f"未找到匹配「{q.strip()}」的股票",
    })


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
            content={"code": 1, "message": "已有任务在运行中", "data": {"status": "conflict"}},
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
            "code": 0,
            "message": f"RS Rating 回填已启动: {start_date} ~ {end_date}",
            "data": {"status": "accepted"},
        },
    )


@router.post("/quotes/backfill")
async def trigger_quotes_backfill(
    start_date: date = Query(..., description="起始日期 YYYY-MM-DD"),
    end_date: date = Query(..., description="结束日期 YYYY-MM-DD"),
):
    """回填指定日期范围的历史行情数据（后台任务，使用 akshare）。

    耗时较长（每只股票约 0.5~1 秒，5000+ 只约 1~2 小时）。
    """
    if _task.status == TaskStatus.RUNNING:
        return JSONResponse(
            status_code=409,
            content={"code": 1, "message": "已有任务在运行中", "data": {"status": "conflict"}},
        )

    # 底层 backfill_quotes 需要 YYYYMMDD 格式字符串
    sd = start_date.strftime("%Y%m%d")
    ed = end_date.strftime("%Y%m%d")

    async def _run():
        try:
            _task.reset()
            result = await backfill_quotes(sd, ed)
            _task.complete(result["total_stocks"])
            logger.info("行情回填完成: %s", result)
        except Exception as e:
            _task.fail(str(e))
            logger.error("行情回填失败: %s\n%s", e, traceback.format_exc())

    asyncio.create_task(_run())
    return JSONResponse(
        status_code=202,
        content={
            "code": 0,
            "message": f"历史行情回填已启动: {start_date} ~ {end_date}",
            "data": {"status": "accepted"},
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


def _generate_futu_url(ts_code: str, market: str = "A") -> str:
    """根据股票代码生成行情页面链接。

    A 股使用雪球（富途 A 股网页版已下线）:
        https://xueqiu.com/S/SH600786
    港股使用富途: https://www.futunn.com/stock/{code}-HK
    美股使用富途: https://www.futunn.com/stock/{SYMBOL}-US
    """
    if market == "A":
        code = ts_code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "").strip()
        if ts_code.endswith(".SH") or code.startswith("6"):
            prefix = "SH"
        elif ts_code.endswith(".BJ") or code.startswith("4") or code.startswith("8") or code.startswith("92"):
            prefix = "BJ"
        else:
            prefix = "SZ"
        return f"https://xueqiu.com/S/{prefix}{code}"
    elif market == "HK":
        code = ts_code.strip()
        return f"https://www.futunn.com/stock/{code}-HK"
    else:
        symbol = ts_code.upper().strip()
        return f"https://www.futunn.com/stock/{symbol}-US"



class VCPFilterOptions(BaseModel):
    """VCP 白名单可用的行业和概念枚举值。"""
    industries: list[str]
    concepts: list[str]


@router.get("/vcp_watchlist/filters")
async def get_vcp_filter_options(
    target_date: date | None = Query(None, description="查询日期，默认最新"),
    market: str = Query("CN", description="市场：CN=A股, US=美股"),
):
    """获取 VCP 白名单中可用的行业和概念板块枚举值（用于前端筛选器）。"""
    from sqlalchemy import select, func as sa_func

    from app.database import async_session
    from app.models.screener import WatchlistDaily

    market = market.upper()
    if market not in ("CN", "US"):
        market = "CN"

    async with async_session() as session:
        if target_date:
            query_date = target_date
        else:
            max_date_q = await session.execute(
                select(sa_func.max(WatchlistDaily.run_date))
                .where(WatchlistDaily.market == market)
            )
            query_date = max_date_q.scalar()
            if not query_date:
                return APIResponse(data={"industries": [], "concepts": []})

        # 查询所有行业（去重去空排序）
        ind_stmt = (
            select(sa_func.distinct(WatchlistDaily.industry))
            .where(WatchlistDaily.run_date == query_date)
            .where(WatchlistDaily.market == market)
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
            .where(WatchlistDaily.market == market)
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

    return APIResponse(data={"industries": industries, "concepts": concepts})


@router.get("/vcp_watchlist")
async def get_vcp_watchlist(
    target_date: date | None = Query(None, description="查询日期，默认最新"),
    market: str = Query("CN", description="市场：CN=A股, US=美股"),
    industry: str | None = Query(None, description="行业筛选，多个用逗号分隔"),
    concepts: str | None = Query(None, description="概念板块筛选，多个用逗号分隔（包含任一即匹配）"),
):
    """查询 VCP 策略白名单。

    返回最新一期（或指定日期）的 Screener 白名单，
    含技术面指标、基本面指标、行业题材、资金流向等维度。
    支持按行业和概念板块筛选，支持按市场过滤。
    收盘价优先从 stock_daily_quote 最新记录获取（避免 Screener 快照价过时）。
    """
    from sqlalchemy import select, func as sa_func, or_, desc as sa_desc

    from app.database import async_session
    from app.models.screener import WatchlistDaily
    from app.models.stock import StockDailyQuote

    market = market.upper()
    if market not in ("CN", "US"):
        market = "CN"

    async with async_session() as session:
        # 确定查询日期：用户指定或取该市场最新
        if target_date:
            query_date = target_date
        else:
            max_date_q = await session.execute(
                select(sa_func.max(WatchlistDaily.run_date))
                .where(WatchlistDaily.market == market)
            )
            query_date = max_date_q.scalar()
            if not query_date:
                return APIResponse(data={"count": 0, "date": str(date.today()), "items": [], "market": market})

        # 查询白名单（按市场过滤）
        stmt = (
            select(WatchlistDaily)
            .where(WatchlistDaily.run_date == query_date)
            .where(WatchlistDaily.market == market)
        )

        # A 股兜底排除 ST 股票
        if market == "CN":
            stmt = stmt.where(
                ~WatchlistDaily.name.like("%ST%")
                | WatchlistDaily.name.is_(None)
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

        # 批量从 stock_daily_quote 获取最新收盘价，覆盖 Screener 快照价
        ts_codes = [row.ts_code for row in rows]
        latest_prices: dict[str, float] = {}
        if ts_codes:
            from sqlalchemy import text as sa_text
            price_sql = sa_text("""
                SELECT DISTINCT ON (ts_code) ts_code, close
                FROM stock_daily_quote
                WHERE ts_code = ANY(:codes) AND market = :market
                ORDER BY ts_code, trade_date DESC
            """)
            price_result = await session.execute(
                price_sql, {"codes": ts_codes, "market": market}
            )
            for code, close in price_result.all():
                if close is not None:
                    latest_prices[code] = float(close)

    items = []
    for row in rows:
        # 根据市场类型生成 futu 链接
        futu_market = "A" if market == "CN" else "US"
        # 优先使用行情表最新收盘价，fallback 到 Screener 快照
        price = latest_prices.get(row.ts_code, row.current_price)
        item = VCPWatchlistItem(
            ts_code=row.ts_code,
            name=row.name,
            current_price=price,
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
            futu_url=_generate_futu_url(row.ts_code, market=futu_market),
        )
        items.append(item)

    return APIResponse(data={
        "count": len(items),
        "date": str(query_date),
        "market": market,
        "items": [i.model_dump() for i in items],
    })


# ── 右侧趋势策略白名单 ──

class TrendWatchlistItem(BaseModel):
    """右侧趋势白名单单条记录。"""
    ts_code: str
    name: str | None = None
    current_price: float | None = None
    trend_score: float | None = None
    adx: float | None = None
    rsi: float | None = None
    ma20: float | None = None
    ma50: float | None = None
    volume_ratio: float | None = None
    industry: str | None = None
    concepts: str | None = None
    main_business: str | None = None
    fund_flow_net: float | None = None
    futu_url: str | None = None


class TrendWatchlistResponse(BaseModel):
    """右侧趋势白名单响应。"""
    count: int
    date: date
    items: list[TrendWatchlistItem]


class TrendFilterOptions(BaseModel):
    """右侧趋势白名单可用的行业和概念枚举值。"""
    industries: list[str]
    concepts: list[str]


@router.get("/trend_watchlist/filters")
async def get_trend_filter_options(
    target_date: date | None = Query(None, description="查询日期，默认最新"),
    market: str = Query("CN", description="市场：CN=A股, US=美股"),
):
    """获取右侧趋势白名单中可用的行业和概念板块枚举值（用于前端筛选器）。"""
    from sqlalchemy import select, func as sa_func

    from app.database import async_session
    from app.models.screener import TrendWatchlistDaily

    market = market.upper()
    if market not in ("CN", "US"):
        market = "CN"

    async with async_session() as session:
        if target_date:
            query_date = target_date
        else:
            max_date_q = await session.execute(
                select(sa_func.max(TrendWatchlistDaily.run_date))
                .where(TrendWatchlistDaily.market == market)
            )
            query_date = max_date_q.scalar()
            if not query_date:
                return APIResponse(data={"industries": [], "concepts": []})

        # 查询所有行业（去重去空排序）
        ind_stmt = (
            select(sa_func.distinct(TrendWatchlistDaily.industry))
            .where(TrendWatchlistDaily.run_date == query_date)
            .where(TrendWatchlistDaily.market == market)
            .where(TrendWatchlistDaily.industry.isnot(None))
            .where(TrendWatchlistDaily.industry != "")
            .order_by(TrendWatchlistDaily.industry)
        )
        ind_result = await session.execute(ind_stmt)
        industries = [r[0] for r in ind_result.all()]

        # 查询所有概念（拆分逗号分隔值，去重排序）
        con_stmt = (
            select(TrendWatchlistDaily.concepts)
            .where(TrendWatchlistDaily.run_date == query_date)
            .where(TrendWatchlistDaily.market == market)
            .where(TrendWatchlistDaily.concepts.isnot(None))
            .where(TrendWatchlistDaily.concepts != "")
        )
        con_result = await session.execute(con_stmt)
        concept_set: set[str] = set()
        for (raw,) in con_result.all():
            for c in raw.split(","):
                c = c.strip()
                if c:
                    concept_set.add(c)
        concepts = sorted(concept_set)

    return APIResponse(data={"industries": industries, "concepts": concepts})


@router.get("/trend_watchlist")
async def get_trend_watchlist(
    target_date: date | None = Query(None, description="查询日期，默认最新"),
    market: str = Query("CN", description="市场：CN=A股, US=美股"),
    industry: str | None = Query(None, description="行业筛选，多个用逗号分隔"),
    concepts: str | None = Query(None, description="概念板块筛选，多个用逗号分隔（包含任一即匹配）"),
):
    """查询右侧趋势策略白名单。

    返回最新一期（或指定日期）的趋势 Screener 白名单，
    含 trend_score、ADX、RSI、SMA20/50、放量倍数等技术面指标，
    以及行业题材、资金流向等维度。
    支持按行业和概念板块筛选，支持按市场过滤。
    收盘价优先从 stock_daily_quote 最新记录获取（避免 Screener 快照价过时）。
    """
    from sqlalchemy import select, func as sa_func, or_, desc as sa_desc

    from app.database import async_session
    from app.models.screener import TrendWatchlistDaily
    from app.models.stock import StockDailyQuote

    market = market.upper()
    if market not in ("CN", "US"):
        market = "CN"

    async with async_session() as session:
        # 确定查询日期：用户指定或取该市场最新
        if target_date:
            query_date = target_date
        else:
            max_date_q = await session.execute(
                select(sa_func.max(TrendWatchlistDaily.run_date))
                .where(TrendWatchlistDaily.market == market)
            )
            query_date = max_date_q.scalar()
            if not query_date:
                return APIResponse(data={"count": 0, "date": str(date.today()), "items": [], "market": market})

        # 查询白名单（按市场过滤）
        stmt = (
            select(TrendWatchlistDaily)
            .where(TrendWatchlistDaily.run_date == query_date)
            .where(TrendWatchlistDaily.market == market)
        )

        # A 股兜底排除 ST 股票
        if market == "CN":
            stmt = stmt.where(
                ~TrendWatchlistDaily.name.like("%ST%")
                | TrendWatchlistDaily.name.is_(None)
            )

        # 行业筛选
        if industry:
            ind_list = [i.strip() for i in industry.split(",") if i.strip()]
            if ind_list:
                stmt = stmt.where(TrendWatchlistDaily.industry.in_(ind_list))

        # 概念板块筛选
        if concepts:
            con_list = [c.strip() for c in concepts.split(",") if c.strip()]
            if con_list:
                concept_conditions = [
                    TrendWatchlistDaily.concepts.like(f"%{c}%") for c in con_list
                ]
                stmt = stmt.where(or_(*concept_conditions))

        stmt = stmt.order_by(TrendWatchlistDaily.trend_score.desc().nulls_last())
        result = await session.execute(stmt)
        rows = result.scalars().all()

        # 批量从 stock_daily_quote 获取最新收盘价，覆盖 Screener 快照价
        ts_codes = [row.ts_code for row in rows]
        latest_prices: dict[str, float] = {}
        if ts_codes:
            from sqlalchemy import text as sa_text
            price_sql = sa_text("""
                SELECT DISTINCT ON (ts_code) ts_code, close
                FROM stock_daily_quote
                WHERE ts_code = ANY(:codes) AND market = :market
                ORDER BY ts_code, trade_date DESC
            """)
            price_result = await session.execute(
                price_sql, {"codes": ts_codes, "market": market}
            )
            for code, close in price_result.all():
                if close is not None:
                    latest_prices[code] = float(close)

    items = []
    for row in rows:
        futu_market = "A" if market == "CN" else "US"
        # 优先使用行情表最新收盘价，fallback 到 Screener 快照
        price = latest_prices.get(row.ts_code, row.current_price)
        item = TrendWatchlistItem(
            ts_code=row.ts_code,
            name=row.name,
            current_price=price,
            trend_score=row.trend_score,
            adx=row.adx,
            rsi=row.rsi,
            ma20=row.ma20,
            ma50=row.ma50,
            volume_ratio=row.volume_ratio,
            industry=row.industry,
            concepts=row.concepts,
            main_business=row.main_business,
            fund_flow_net=row.fund_flow_net,
            futu_url=_generate_futu_url(row.ts_code, market=futu_market),
        )
        items.append(item)

    return APIResponse(data={
        "count": len(items),
        "date": str(query_date),
        "market": market,
        "items": [i.model_dump() for i in items],
    })


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


@router.get("/value_watchlist")
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
            return APIResponse(data={"count": 0, "items": []})

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

    return APIResponse(data={"count": len(items), "items": [i.model_dump() for i in items]})


# ── Ticker 速览（新闻卡片 Ticker 点击使用）──

class TickerLookupResponse(BaseModel):
    """Ticker 速览信息。"""
    ts_code: str | None = None
    name: str | None = None
    industry: str | None = None
    in_vcp: bool = False
    vcp_score: float | None = None
    in_trend: bool = False
    trend_score: float | None = None
    futu_url: str | None = None


@router.get("/ticker_lookup")
async def ticker_lookup(
    code: str = Query(..., min_length=1, max_length=20, description="股票代码（如 300750、NVDA、300750.SZ）"),
):
    """Ticker 速览 — 查询指定标的是否在当日 VCP / 趋势白名单中。

    支持多种输入格式：纯数字代码（300750）、带后缀（300750.SZ）、美股代码（NVDA）。
    先从 VCP 和趋势白名单最新数据中匹配，返回是否在白名单中及相关评分。
    若不在白名单中，从行情表兜底查询股票名称。
    """
    from sqlalchemy import select, func as sa_func

    from app.database import async_session
    from app.models.screener import WatchlistDaily, TrendWatchlistDaily
    from app.models.stock import StockDailyQuote

    raw = code.strip().upper()

    # 标准化代码并识别市场
    # A 股：6位纯数字（如 300750、600519）或带 .SZ/.SH 后缀
    # 港股：5位纯数字（如 00700、09988）
    # 美股：含字母（如 NVDA、AAPL）
    market_type = "US"  # 默认美股
    if raw.replace(".", "").replace("SZ", "").replace("SH", "").isdigit():
        digits = raw.split(".")[0]
        if len(digits) == 5:
            # 港股：5 位纯数字
            ts_code = digits
            market_type = "HK"
        else:
            # A 股：6 位纯数字
            ts_code = digits
            market_type = "A"
    else:
        ts_code = raw

    result_data = {
        "ts_code": ts_code,
        "name": None,
        "industry": None,
        "in_vcp": False,
        "vcp_score": None,
        "in_trend": False,
        "trend_score": None,
        "futu_url": None,
    }

    async with async_session() as session:
        # 查 VCP 白名单最新日期
        vcp_max_q = await session.execute(
            select(sa_func.max(WatchlistDaily.run_date))
        )
        vcp_date = vcp_max_q.scalar()

        if vcp_date:
            vcp_row = await session.execute(
                select(WatchlistDaily)
                .where(WatchlistDaily.run_date == vcp_date)
                .where(WatchlistDaily.ts_code == ts_code)
                .limit(1)
            )
            vcp_item = vcp_row.scalars().first()
            if vcp_item:
                result_data["in_vcp"] = True
                result_data["vcp_score"] = vcp_item.vcp_score
                result_data["name"] = vcp_item.name
                result_data["industry"] = vcp_item.industry

        # 查趋势白名单最新日期
        trend_max_q = await session.execute(
            select(sa_func.max(TrendWatchlistDaily.run_date))
        )
        trend_date = trend_max_q.scalar()

        if trend_date:
            trend_row = await session.execute(
                select(TrendWatchlistDaily)
                .where(TrendWatchlistDaily.run_date == trend_date)
                .where(TrendWatchlistDaily.ts_code == ts_code)
                .limit(1)
            )
            trend_item = trend_row.scalars().first()
            if trend_item:
                result_data["in_trend"] = True
                result_data["trend_score"] = trend_item.trend_score
                if not result_data["name"]:
                    result_data["name"] = trend_item.name
                if not result_data["industry"]:
                    result_data["industry"] = trend_item.industry

        # 兜底：若白名单中没有名称，从行情表查询
        if not result_data["name"]:
            name_row = await session.execute(
                select(StockDailyQuote.name)
                .where(StockDailyQuote.ts_code == ts_code)
                .where(StockDailyQuote.name.isnot(None))
                .where(StockDailyQuote.name != "")
                .order_by(StockDailyQuote.trade_date.desc())
                .limit(1)
            )
            name_val = name_row.scalar()
            if name_val:
                result_data["name"] = name_val

    # 生成富途链接（A 股 / 港股 / 美股）
    result_data["futu_url"] = _generate_futu_url(ts_code, market=market_type)

    return APIResponse(data=result_data)
