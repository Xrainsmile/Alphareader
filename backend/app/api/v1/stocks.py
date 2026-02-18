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

from app.services.indicators import compute_and_save_rs_rating, load_rs_rating

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
    """后台执行 RS Rating 计算。"""
    try:
        _task.reset()
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
