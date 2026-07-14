"""VCP 市场适配度计算服务（PRD 阶段二）。

五项规则（权重合计 100）：
  大盘趋势 25 / 市场宽度 20 / 波动环境 20 / 突破有效性 25 / 交易活跃度 10

三档状态：70-100 适合关注 / 45-69 中性观察 / 0-44 谨慎参与。

否决与降级（PRD 6.5）：
  - 趋势破坏：指数跌破 MA60 且 MA60 向下 → 最高等级限制为「中性观察」
  - 波动冲击：近 5 日实现波动率增幅 ≥ 30% → 下调一档
  - 宽度恶化：市场宽度连续 3 日 < 30% → 下调一档
  - 突破失效：突破后 5 日正收益比例 < 30% → 最终等级「谨慎参与」
  - 数据不足：有效突破样本 < 20 → 突破有效性维度按中性 12 分计入并标记

所有结果可解释：每个维度含 status / status_label / detail / raw，并落地 reason_codes。
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.market import MarketAdaptability
from app.services.market_metrics import compute_market_metrics
from app.services.strategy_config import (
    LEVEL_CAUTIOUS,
    LEVEL_FAVORABLE,
    LEVEL_NEUTRAL,
    RULE_VERSION,
    VCP_DIMENSIONS,
    level_from_score,
)

logger = logging.getLogger("alphareader.vcp_suitability")

# 等级排序（用于降级运算）：favorable > neutral > cautious
_LEVEL_RANK = {LEVEL_CAUTIOUS: 0, LEVEL_NEUTRAL: 1, LEVEL_FAVORABLE: 2}
_LEVEL_LABEL = {LEVEL_FAVORABLE: "适合关注", LEVEL_NEUTRAL: "中性观察", LEVEL_CAUTIOUS: "谨慎参与"}


def _down_one(level: str) -> str:
    """下调一档：favorable→neutral→cautious。"""
    if level == LEVEL_FAVORABLE:
        return LEVEL_NEUTRAL
    return LEVEL_CAUTIOUS


# ───────────────────────────────────────────────────────────
# 各维度评分
# ───────────────────────────────────────────────────────────

def _score_trend(d: dict) -> dict:
    close = d.get("close")
    ma20 = d.get("ma20")
    ma60 = d.get("ma60")
    ma20_up = d.get("ma20_slope_up")
    if close is None or ma20 is None or ma60 is None:
        return {"score": 0, "max": 25, "status": "unavailable",
                "status_label": "数据不足", "detail": "基准指数均线数据不足", "raw": None}
    above_ma20 = close > ma20
    above_ma60 = close > ma60
    up = bool(ma20_up)
    cnt = sum([above_ma20, above_ma60, up])
    score = {3: 25, 2: 15, 1: 5, 0: 0}[cnt]
    label = {3: "偏强", 2: "偏强", 1: "偏弱", 0: "偏弱"}[cnt]
    cond = []
    if above_ma20:
        cond.append("站上20日线")
    if above_ma60:
        cond.append("站上60日线")
    if up:
        cond.append("20日线向上")
    detail = "；".join(cond) if cond else "均不满足"
    return {"score": score, "max": 25, "status": ("strong" if cnt == 3 else "partial" if cnt == 2 else "weak"),
            "status_label": label, "detail": detail,
            "raw": {"close": round(close, 2), "ma20": round(ma20, 2), "ma60": round(ma60, 2), "ma20_up": up}}


def _score_breadth(pct: float | None) -> dict:
    if pct is None:
        return {"score": 0, "max": 20, "status": "unavailable",
                "status_label": "数据不足", "detail": "市场宽度暂无数据", "raw": None}
    if pct > 60:
        return {"score": 20, "max": 20, "status": "strong", "status_label": "偏强",
                "detail": f"站上20日线占比 {pct:.0f}%（>60%）", "raw": pct}
    if pct >= 45:
        return {"score": 14, "max": 20, "status": "neutral", "status_label": "中性",
                "detail": f"站上20日线占比 {pct:.0f}%（45%-60%）", "raw": pct}
    if pct >= 30:
        return {"score": 7, "max": 20, "status": "weak", "status_label": "偏弱",
                "detail": f"站上20日线占比 {pct:.0f}%（30%-45%）", "raw": pct}
    return {"score": 0, "max": 20, "status": "bearish", "status_label": "偏弱",
            "detail": f"站上20日线占比 {pct:.0f}%（<30%）", "raw": pct}


def _score_volatility(d: dict) -> dict:
    vol_pct = d.get("vol_pct_250")
    shock = d.get("vol_shock")
    if vol_pct is None:
        return {"score": 5, "max": 20, "status": "unavailable", "status_label": "数据不足",
                "detail": "波动率分位数据不足", "raw": None}
    if shock is not None and shock >= 0.30:
        return {"score": 0, "max": 20, "status": "shock", "status_label": "骤升",
                "detail": f"近5日波动率上升 {shock*100:.0f}%（≥30%）", "raw": {"vol_pct_250": round(vol_pct, 1), "vol_shock": round(shock, 3)}}
    if 30 <= vol_pct <= 60:
        return {"score": 20, "max": 20, "status": "neutral", "status_label": "适中",
                "detail": f"波动率处历史 {vol_pct:.0f}% 分位（30%-60%）", "raw": {"vol_pct_250": round(vol_pct, 1)}}
    if (20 <= vol_pct < 30) or (60 < vol_pct <= 75):
        return {"score": 12, "max": 20, "status": "neutral", "status_label": "偏高/偏低",
                "detail": f"波动率处历史 {vol_pct:.0f}% 分位", "raw": {"vol_pct_250": round(vol_pct, 1)}}
    return {"score": 5, "max": 20, "status": "neutral", "status_label": "极端",
            "detail": f"波动率处历史 {vol_pct:.0f}% 分位（过高或过低）", "raw": {"vol_pct_250": round(vol_pct, 1)}}


def _score_breakout(b: dict) -> dict:
    sample = b.get("sample_count", 0)
    ratio = b.get("positive_ratio")
    if sample < 20 or ratio is None:
        return {"score": 12, "max": 25, "status": "insufficient", "status_label": "样本不足",
                "detail": f"有效突破样本 {sample} 个（<20），按中性计分", "raw": {"sample": sample, "ratio": ratio}}
    if ratio > 65:
        return {"score": 25, "max": 25, "status": "strong", "status_label": "较好",
                "detail": f"突破后5日正收益比例 {ratio:.0f}%（>65%）", "raw": {"sample": sample, "ratio": ratio}}
    if ratio >= 50:
        return {"score": 18, "max": 25, "status": "neutral", "status_label": "一般",
                "detail": f"突破后5日正收益比例 {ratio:.0f}%（50%-65%）", "raw": {"sample": sample, "ratio": ratio}}
    if ratio >= 35:
        return {"score": 8, "max": 25, "status": "weak", "status_label": "一般",
                "detail": f"突破后5日正收益比例 {ratio:.0f}%（35%-50%）", "raw": {"sample": sample, "ratio": ratio}}
    return {"score": 0, "max": 25, "status": "bearish", "status_label": "较弱",
            "detail": f"突破后5日正收益比例 {ratio:.0f}%（<35%）", "raw": {"sample": sample, "ratio": ratio}}


def _score_activity(ratio: float | None) -> dict:
    if ratio is None:
        return {"score": 0, "max": 10, "status": "unavailable", "status_label": "数据不足",
                "detail": "成交额数据不足", "raw": None}
    if ratio > 110:
        return {"score": 10, "max": 10, "status": "strong", "status_label": "较高",
                "detail": f"成交额达20日均量 {ratio:.0f}%（>110%）", "raw": ratio}
    if ratio >= 90:
        return {"score": 7, "max": 10, "status": "neutral", "status_label": "适中",
                "detail": f"成交额达20日均量 {ratio:.0f}%（90%-110%）", "raw": ratio}
    if ratio >= 80:
        return {"score": 3, "max": 10, "status": "weak", "status_label": "偏低",
                "detail": f"成交额达20日均量 {ratio:.0f}%（80%-90%）", "raw": ratio}
    return {"score": 0, "max": 10, "status": "bearish", "status_label": "偏低",
            "detail": f"成交额达20日均量 {ratio:.0f}%（<80%）", "raw": ratio}


# ───────────────────────────────────────────────────────────
# 主计算
# ───────────────────────────────────────────────────────────

async def compute_vcp_adaptability(
    market: str,
    target_date: date,
    save: bool = True,
) -> dict:
    """计算并（可选）持久化 VCP 市场适配度。

    Returns: 可直接序列化为 API 响应的 dict。
    """
    metrics = await compute_market_metrics(market, target_date)
    derived = metrics["benchmark_derived"]

    trend = _score_trend(derived)
    breadth = _score_breadth(metrics["breadth_pct"])
    volatility = _score_volatility(derived)
    breakout = _score_breakout(metrics["breakout"])
    activity = _score_activity(metrics["turnover_ratio"])

    dims = [
        {"key": "trend", "name": "大盘趋势", **trend},
        {"key": "breadth", "name": "市场宽度", **breadth},
        {"key": "volatility", "name": "波动环境", **volatility},
        {"key": "breakout", "name": "突破有效性", **breakout},
        {"key": "activity", "name": "交易活跃度", **activity},
    ]

    total = sum(d["score"] for d in dims)
    base_level = level_from_score(total)

    reason_codes: list[str] = []
    data_delayed = False
    if metrics["breadth_pct"] is None or metrics["turnover_ratio"] is None:
        data_delayed = True
        reason_codes.append("DATA_DELAY")
    if metrics["benchmark_source"] == "synthetic":
        data_delayed = True
        reason_codes.append("DATA_DELAY")

    # ── 否决 / 降级规则（PRD 6.5）──
    close = derived.get("close")
    ma60 = derived.get("ma60")
    ma60_down = derived.get("ma60_slope_down")
    trend_broken = (close is not None and ma60 is not None and close < ma60 and bool(ma60_down))

    vol_shock = derived.get("vol_shock")
    vol_shock_trig = bool(vol_shock is not None and vol_shock >= 0.30)

    breadth_deter = await _is_breadth_deteriorating(market, target_date, metrics["breadth_pct"])

    b_sample = metrics["breakout"].get("sample_count", 0)
    b_ratio = metrics["breakout"].get("positive_ratio")
    breakout_fail = (b_sample >= 20 and b_ratio is not None and b_ratio < 30)
    if b_sample < 20:
        reason_codes.append("SAMPLE_INSUFFICIENT")

    # 应用降级
    final_level = base_level
    if trend_broken:
        reason_codes.append("TREND_BROKEN")
        if final_level == LEVEL_FAVORABLE:
            final_level = LEVEL_NEUTRAL  # 最高限制为中性观察
    if vol_shock_trig:
        reason_codes.append("VOLATILITY_SHOCK")
        final_level = _down_one(final_level)
    if breadth_deter:
        reason_codes.append("BREADTH_DETERIORATING")
        final_level = _down_one(final_level)
    if breakout_fail:
        reason_codes.append("BREAKOUT_FAIL")
        final_level = LEVEL_CAUTIOUS

    reason_codes = sorted(set(reason_codes))

    conclusion = _build_conclusion(final_level, dims, trend_broken, vol_shock_trig, breadth_deter, breakout_fail)

    result = {
        "strategy_id": "vcp",
        "market": market,
        "trade_date": target_date.isoformat(),
        "level": final_level,
        "level_label": _LEVEL_LABEL[final_level],
        "total_score": round(total, 1),
        "dimensions": dims,
        "reason_codes": reason_codes,
        "conclusion": conclusion,
        "data_delayed": data_delayed,
        "rule_version": RULE_VERSION,
        "input_data_version": f"bench={metrics['benchmark_source']};date={target_date.isoformat()}",
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }

    if save:
        await _save(result, metrics)

    return result


async def _is_breadth_deteriorating(market: str, target_date: date, current_pct: float | None) -> bool:
    """市场宽度连续 3 日 < 30%（含当日）。"""
    if current_pct is None or current_pct >= 30:
        return False
    try:
        async with async_session() as session:
            rows = await session.execute(
                select(MarketAdaptability.dimension_scores, MarketAdaptability.trade_date)
                .where(MarketAdaptability.strategy_id == "vcp")
                .where(MarketAdaptability.market == market)
                .where(MarketAdaptability.trade_date < target_date)
                .order_by(MarketAdaptability.trade_date.desc())
                .limit(2)
            )
            prev = rows.all()
        # 当日已 <30，需再连续 2 日（共 3 日）
        for r in prev:
            pct = _extract_breadth(r.dimension_scores)
            if pct is None or pct >= 30:
                return False
        # prev 有 2 条且都 <30，加上当日 <30 → 连续 3 日
        return len(prev) >= 2
    except Exception as e:  # 容错：历史缺失不阻断
        logger.warning("宽度恶化判断失败: %s", e)
        return False


def _extract_breadth(dimension_scores: list[dict]) -> float | None:
    for d in dimension_scores or []:
        if d.get("key") == "breadth":
            raw = d.get("raw")
            if isinstance(raw, (int, float)):
                return float(raw)
    return None


def _build_conclusion(level, dims, trend_broken, vol_shock, breadth_deter, breakout_fail) -> str:
    base = {
        LEVEL_FAVORABLE: "市场环境对该策略相对友好，可继续观察候选信号。",
        LEVEL_NEUTRAL: "环境存在支持条件，也有明显约束，需加强信号确认。",
        LEVEL_CAUTIOUS: "市场环境对该策略不友好，优先控制风险并等待改善。",
    }[level]
    extras = []
    if trend_broken:
        extras.append("大盘趋势已破坏")
    if vol_shock:
        extras.append("波动率骤升")
    if breadth_deter:
        extras.append("市场宽度持续恶化")
    if breakout_fail:
        extras.append("突破延续性弱")
    if extras:
        return base + "需注意：" + "、".join(extras) + "。"
    return base


async def _save(result: dict, metrics: dict) -> None:
    """upsert 到 market_adaptability。"""
    async with async_session() as session:
        stmt = pg_insert(MarketAdaptability).values(
            strategy_id=result["strategy_id"],
            market=result["market"],
            trade_date=result["trade_date"],
            total_score=result["total_score"],
            level=result["level"],
            dimension_scores=result["dimensions"],
            reason_codes=result["reason_codes"],
            conclusion=result["conclusion"],
            rule_version=result["rule_version"],
            input_data_version=result["input_data_version"],
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_market_adaptability",
            set_={
                "total_score": stmt.excluded.total_score,
                "level": stmt.excluded.level,
                "dimension_scores": stmt.excluded.dimension_scores,
                "reason_codes": stmt.excluded.reason_codes,
                "conclusion": stmt.excluded.conclusion,
                "rule_version": stmt.excluded.rule_version,
                "input_data_version": stmt.excluded.input_data_version,
            },
        )
        await session.execute(stmt)
        await session.commit()


async def get_vcp_adaptability(market: str, target_date: date | None = None, save: bool = True) -> dict:
    """读取已计算结果；若不存在则计算（并落库）。"""
    if target_date is None:
        target_date = date.today()

    async with async_session() as session:
        row = await session.execute(
            select(MarketAdaptability)
            .where(MarketAdaptability.strategy_id == "vcp")
            .where(MarketAdaptability.market == market)
            .where(MarketAdaptability.trade_date == target_date)
        )
        rec = row.scalar_one_or_none()
        if rec is not None:
            return {
                "strategy_id": rec.strategy_id,
                "market": rec.market,
                "trade_date": rec.trade_date.isoformat(),
                "level": rec.level,
                "level_label": _LEVEL_LABEL.get(rec.level, rec.level),
                "total_score": rec.total_score,
                "dimensions": rec.dimension_scores,
                "reason_codes": rec.reason_codes,
                "conclusion": rec.conclusion,
                "data_delayed": any(c == "DATA_DELAY" for c in (rec.reason_codes or [])),
                "rule_version": rec.rule_version,
                "input_data_version": rec.input_data_version,
                "computed_at": rec.computed_at.isoformat(timespec="seconds") if rec.computed_at else None,
            }
    return await compute_vcp_adaptability(market, target_date, save=save)
