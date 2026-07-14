"""策略页 API — 策略列表 / 概览 / 市场适配度 / 个股信号 / 手动计算。

前缀：/api/v1/strategy （经 require_api_key 保护）
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from app.services.strategy_config import (
    RULE_VERSION,
    get_strategy_profile,
    list_strategies,
)
from app.services.strategy_service import compute_filter_summary, compute_stock_signal
from app.services.vcp_suitability import compute_vcp_adaptability, get_vcp_adaptability

logger = logging.getLogger("alphareader.api.strategy")

router = APIRouter(prefix="/strategy", tags=["strategy"])


def _resolve_date(date_str: str | None) -> date:
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date 格式应为 YYYY-MM-DD")
    return date.today()


@router.get("/list")
async def strategy_list(market: str = Query("CN", description="CN=A股, US=美股")):
    """策略列表（含启用 / 即将上线状态）。"""
    return {"market": market, "rule_version": RULE_VERSION, "strategies": list_strategies(market)}


@router.get("/overview")
async def strategy_overview(
    market: str = Query("CN"),
    strategy_id: str = Query("vcp"),
    date: str | None = Query(None, description="YYYY-MM-DD，默认最近交易日"),
):
    """策略概览：画像 + 市场适配 + 筛选摘要 + 风险提示（PRD 7.2）。"""
    target = _resolve_date(date)
    profile = get_strategy_profile(strategy_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"未知策略: {strategy_id}")

    resp = {
        "strategy_id": strategy_id,
        "market": market,
        "trade_date": target.isoformat(),
        "profile": profile,
        "adaptability": None,
        "filter_summary": None,
    }

    # 模拟仓不参与适配度
    if profile.get("no_adaptability"):
        return resp

    if not profile.get("enabled") or profile.get("coming_soon"):
        resp["coming_soon"] = True
        return resp

    # VCP 实装：返回适配度与筛选摘要
    try:
        resp["adaptability"] = await get_vcp_adaptability(market, target, save=True)
    except Exception as e:
        logger.exception("计算市场适配度失败: %s", e)
        resp["adaptability"] = None

    try:
        resp["filter_summary"] = await compute_filter_summary(market, target)
    except Exception as e:
        logger.warning("筛选摘要计算失败: %s", e)
        resp["filter_summary"] = None

    return resp


@router.get("/adaptability")
async def strategy_adaptability(
    market: str = Query("CN"),
    strategy_id: str = Query("vcp"),
    date: str | None = Query(None),
):
    """市场适配度明细（用于 suitability_detail_click 展开指标解释）。"""
    target = _resolve_date(date)
    if strategy_id != "vcp":
        raise HTTPException(status_code=400, detail="当前仅 VCP 支持市场适配度")
    try:
        return await get_vcp_adaptability(market, target, save=True)
    except Exception as e:
        logger.exception("市场适配度计算失败: %s", e)
        raise HTTPException(status_code=500, detail=f"适配度计算失败: {e}")


@router.get("/stock_signal")
async def strategy_stock_signal(
    market: str = Query("CN"),
    strategy_id: str = Query("vcp"),
    ts_code: str = Query(..., description="股票代码，如 300750 / NVDA"),
    date: str | None = Query(None),
):
    """个股信号详情（PRD 5.4）。"""
    target = _resolve_date(date)
    try:
        signal = await compute_stock_signal(market, ts_code, target)
    except Exception as e:
        logger.exception("个股信号计算失败: %s", e)
        raise HTTPException(status_code=500, detail=f"个股信号计算失败: {e}")
    if signal is None:
        raise HTTPException(status_code=404, detail=f"未找到 {ts_code} 在 {target} 的行情数据")
    return signal


@router.post("/compute")
async def strategy_compute(
    market: str = Query("CN"),
    date: str | None = Query(None),
):
    """手动触发：采集指数 + 计算 VCP 适配度（日终任务也可调用）。"""
    from app.services.index_fetcher import fetch_indices

    target = _resolve_date(date)
    idx_summary = {}
    try:
        idx_summary = await fetch_indices(market)
    except Exception as e:
        logger.warning("指数采集跳过（适配度将使用合成代理）: %s", e)

    try:
        result = await compute_vcp_adaptability(market, target, save=True)
    except Exception as e:
        logger.exception("VCP 适配度计算失败: %s", e)
        raise HTTPException(status_code=500, detail=f"适配度计算失败: {e}")

    return {"index_fetch": idx_summary, "adaptability": result}
