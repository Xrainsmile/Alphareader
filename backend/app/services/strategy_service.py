"""策略页聚合服务 — 筛选摘要 + 个股信号详情（PRD 5.3 / 5.4）。

筛选摘要：基础符合 / 重点观察 / 突破确认 / 较昨日新增 / 数据日期
个股信号：信号成熟度 / 波动收缩 / 成交量收缩 / 中期趋势 / 枢轴位距离 / 突破确认 / 风险提示
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select, text

from app.database import async_session
from app.models.screener import WatchlistDaily
from app.models.stock import StockDailyQuote
from app.services.market_metrics import compute_breakout

logger = logging.getLogger("alphareader.strategy_service")

VCP_KEY_OBSERVE = 80  # 重点观察阈值（VCP 评分）


async def compute_filter_summary(market: str, target_date: date) -> dict:
    """计算筛选摘要（PRD 5.3）。"""
    async with async_session() as session:
        # 基础符合 = 当日 VCP 白名单数量
        base = await session.execute(
            select(WatchlistDaily.ts_code)
            .where(WatchlistDaily.market == market)
            .where(WatchlistDaily.run_date == target_date)
        )
        today_codes = [r[0] for r in base.all()]
        base_count = len(today_codes)

        # 重点观察 = VCP 评分 >= 阈值
        obs = await session.execute(
            select(WatchlistDaily.ts_code)
            .where(WatchlistDaily.market == market)
            .where(WatchlistDaily.run_date == target_date)
            .where(WatchlistDaily.vcp_score >= VCP_KEY_OBSERVE)
        )
        observe_count = len(obs.all())

        # 昨日白名单（用于新增对比）
        yest = await session.execute(
            select(WatchlistDaily.ts_code)
            .where(WatchlistDaily.market == market)
            .where(WatchlistDaily.run_date == target_date - timedelta(days=1))
        )
        yest_codes = set(r[0] for r in yest.all())

    new_count = len(set(today_codes) - yest_codes) if yest_codes else 0

    # 突破确认 = 当日真实突破事件数（PRD 突破定义）
    try:
        bo = await compute_breakout(market, target_date)
        breakout_confirm = bo.get("breakout_today", 0)
    except Exception as e:
        logger.warning("突破确认数计算失败: %s", e)
        breakout_confirm = 0

    return {
        "base_count": base_count,
        "observe_count": observe_count,
        "breakout_confirm": breakout_confirm,
        "new_count": new_count,
        "data_date": target_date.isoformat(),
        "has_yesterday": bool(yest_codes),
    }


async def compute_stock_signal(market: str, ts_code: str, target_date: date) -> dict | None:
    """计算单只股票 VCP 信号详情（PRD 5.4）。"""
    start = target_date - timedelta(days=140)
    async with async_session() as session:
        result = await session.execute(
            text(
                """
                SELECT trade_date, close, volume, high, low, name
                FROM stock_daily_quote
                WHERE market = :m AND ts_code = :code
                  AND trade_date <= :target AND trade_date >= :start
                  AND close IS NOT NULL AND close > 0
                ORDER BY trade_date ASC
                """
            ),
            {"m": market, "code": ts_code, "target": target_date, "start": start},
        )
        rows = result.all()

    if not rows:
        return None

    df = pd.DataFrame(
        [(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), r[5]) for r in rows],
        columns=["trade_date", "close", "volume", "high", "low", "name"],
    )
    n = len(df)
    close = df["close"]
    last_close = float(close.iloc[-1])

    # 中期趋势（MA20 / MA50）
    ma20 = float(close.iloc[-20:].mean()) if n >= 20 else None
    ma50 = float(close.iloc[-50:].mean()) if n >= 50 else None
    mid_trend = "向上" if (ma20 and ma50 and last_close > ma20 and last_close > ma50) else (
        "中性" if (ma20 and last_close > ma20) else "偏弱")

    # 波动收缩：最近三段（各 20 日）收盘价标准差逐级收窄
    vol_contract = "未知"
    contract_detail = ""
    if n >= 60:
        s1 = float(close.iloc[-20:].std())
        s2 = float(close.iloc[-40:-20].std())
        s3 = float(close.iloc[-60:-40].std())
        if s1 < s2 < s3:
            vol_contract = "符合"
            contract_detail = f"近三段波动 {s1:.2f} < {s2:.2f} < {s3:.2f}，逐级收窄"
        elif s1 < s3:
            vol_contract = "部分符合"
            contract_detail = f"近段波动 {s1:.2f} 低于远端 {s3:.2f}"
        else:
            vol_contract = "不符合"
            contract_detail = f"近段波动 {s1:.2f} 未收窄"

    # 成交量收缩：近 20 日均量 vs 前 40 日均量
    vol20 = float(df["volume"].iloc[-20:].mean()) if n >= 20 else None
    vol_prev = float(df["volume"].iloc[-60:-20].mean()) if n >= 60 else None
    vol_ratio = None
    vol_detail = ""
    if vol20 and vol_prev and vol_prev > 0:
        vol_ratio = vol20 / vol_prev - 1.0
        vol_detail = f"近20日均量较前期下降 {abs(vol_ratio)*100:.0f}%"

    # 枢轴高位（近 60 日最高收盘）
    pivot = float(close.iloc[-60:].max()) if n >= 60 else float(close.max())
    pivot_distance = (pivot - last_close) / last_close * 100.0 if last_close else None

    # 突破确认：收盘突破枢轴且量能放大
    breakout_confirmed = False
    if n >= 60 and vol20:
        breakout_confirmed = (last_close > pivot) and (float(df["volume"].iloc[-1]) >= 1.2 * vol20)

    # 信号成熟度
    if breakout_confirmed:
        maturity = "突破确认"
    elif pivot_distance is not None and pivot_distance <= 5 and vol_contract in ("符合", "部分符合"):
        maturity = "接近突破"
    elif mid_trend == "向上":
        maturity = "观察中"
    else:
        maturity = "失效"

    # 风险提示
    risks = []
    if mid_trend != "向上":
        risks.append("中期趋势尚未转强，需等待均线修复")
    if vol_contract == "不符合":
        risks.append("波动未有效收敛，形态成熟度不足")
    if pivot_distance is not None and pivot_distance > 15:
        risks.append(f"距枢轴位 {pivot_distance:.1f}% 较远，尚未进入突破区")
    if breakout_confirmed is False and maturity == "接近突破":
        risks.append("接近突破但量能未确认，警惕假突破")
    if not risks:
        risks.append("形态与趋势条件较完整，仍须以量价确认为准")

    return {
        "ts_code": ts_code,
        "name": rows[-1][5] or ts_code,
        "trade_date": target_date.isoformat(),
        "maturity": maturity,
        "current_price": round(last_close, 2),
        "vol_contraction": {"status": vol_contract, "detail": contract_detail},
        "volume_contraction": {
            "status": ("较明显" if (vol_ratio is not None and vol_ratio <= -0.15) else "一般"),
            "change_pct": round(vol_ratio * 100, 1) if vol_ratio is not None else None,
            "detail": vol_detail,
        },
        "mid_trend": mid_trend,
        "pivot_distance_pct": round(pivot_distance, 2) if pivot_distance is not None else None,
        "breakout_confirmed": breakout_confirmed,
        "risk_hints": risks,
    }
