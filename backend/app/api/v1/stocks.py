"""Stock data & RS Rating API endpoints."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import date, datetime
from enum import Enum

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
    score: float
    rs_rating: int
    close: float | None = None
    pct_change: float | None = None
    change: float | None = None


class RSRatingResponse(BaseModel):
    count: int
    date: date
    items: list[RSRatingItem]


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
