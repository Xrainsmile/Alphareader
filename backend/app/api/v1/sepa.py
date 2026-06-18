"""SEPA 模拟盘训练系统 API — 三市场（A股/港股/美股）独立账户。

公开 GET（需 API Key）：
  GET  /sepa/markets               — 三市场账户概要
  GET  /sepa/gate?market=          — 市场闸门状态
  GET  /sepa/watchlist?market=     — 股池列表
  GET  /sepa/watchlist/{id}        — 单条详情
  GET  /sepa/account?market=       — 账户总览 + 持仓
  GET  /sepa/trades?market=&filter=— 交易日志
  GET  /sepa/trades/export?market= — CSV 导出
  GET  /sepa/kpi?market=&period=   — KPI 仪表盘
  POST /sepa/check                 — 买点检查清单 + 风险预演（不下单）

后台（X-Sandbox-Password 头部认证）：
  PUT    /sepa/admin/gate                  — 更新闸门
  POST   /sepa/admin/watchlist             — 添加股池标的（自动判8条）
  PUT    /sepa/admin/watchlist/{id}        — 更新数据（重判8条）
  DELETE /sepa/admin/watchlist/{id}        — 删除
  POST   /sepa/admin/trades                — 开仓（强制纪律拦截）
  POST   /sepa/admin/trades/{id}/close     — 平仓（强制标注是否守纪律）
  DELETE /sepa/admin/trades/{id}           — 撤销交易
  PUT    /sepa/admin/account               — 修改账户初始资金
"""

from __future__ import annotations

import csv
import hmac
import io
import logging
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.sepa import (
    SEPA_CURRENCY,
    SEPA_CURRENCY_SYMBOL,
    SEPA_MARKETS,
    SepaAccount,
    SepaMarketGate,
    SepaTrade,
    SepaWatchlistItem,
)
from app.services import sepa_service as svc

logger = logging.getLogger("alphareader.sepa")

router = APIRouter(prefix="/sepa", tags=["sepa"])


def _require_admin(x_sandbox_password: str = Header(None)):
    """SEPA 写操作鉴权 — 复用 SANDBOX_PASSWORD。

    前端解锁后在写请求头携带 X-Sandbox-Password。未配置密码则放行。
    （全站已有 API Key 保护，此处为第二道前端操作锁。）
    """
    expected = settings.SANDBOX_PASSWORD
    if expected and not hmac.compare_digest(
        (x_sandbox_password or "").encode(), expected.encode()
    ):
        raise HTTPException(status_code=401, detail="需要正确的访问密码")


def _check_market(market: str) -> str:
    if market not in SEPA_MARKETS:
        raise HTTPException(status_code=400, detail=f"非法市场: {market}（应为 CN/HK/US）")
    return market


# ════════════════════════════════════════════════════════════
# Pydantic Schemas
# ════════════════════════════════════════════════════════════

class GateUpdate(BaseModel):
    market: str
    index_above_ma50: bool = False
    ma50_trending_up: bool = False
    breadth_healthy: bool = False
    new_highs_gt_lows: bool = False
    note: str | None = None


class WatchlistCreate(BaseModel):
    market: str
    symbol: str = Field(..., max_length=16)
    name: str = Field("", max_length=64)
    price: float | None = None
    ma50: float | None = None
    ma150: float | None = None
    ma200: float | None = None
    ma200_rising: bool = False
    high52w: float | None = None
    low52w: float | None = None
    rs: float | None = None
    vcp_stage: str | None = Field(None, max_length=128)
    pivot_price: float | None = None
    fundamental_note: str | None = None


class WatchlistUpdate(BaseModel):
    name: str | None = Field(None, max_length=64)
    price: float | None = None
    ma50: float | None = None
    ma150: float | None = None
    ma200: float | None = None
    ma200_rising: bool | None = None
    high52w: float | None = None
    low52w: float | None = None
    rs: float | None = None
    vcp_stage: str | None = Field(None, max_length=128)
    pivot_price: float | None = None
    fundamental_note: str | None = None


class CheckRequest(BaseModel):
    """买点检查清单 + 风险预演（不下单）。"""
    market: str
    symbol: str = Field(..., max_length=16)
    entry_price: float = Field(..., gt=0)
    shares: int = Field(..., gt=0)
    stop_price: float | None = None
    pivot_price: float | None = None
    vcp_confirmed: bool = False


class TradeOpen(BaseModel):
    market: str
    symbol: str = Field(..., max_length=16)
    name: str = Field("", max_length=64)
    entry_date: date
    entry_price: float = Field(..., gt=0)
    shares: int = Field(..., gt=0)
    stop_price: float = Field(..., gt=0)
    pivot_price: float | None = None
    vcp_confirmed: bool = False
    entry_reason: str | None = None
    force_risky: bool = False  # 距枢轴>5% 追高的强制确认


class TradeClose(BaseModel):
    exit_date: date
    exit_price: float = Field(..., gt=0)
    exit_reason: str = Field(..., max_length=32)  # 止损/止盈/趋势坏
    followed_rule: bool  # 是否按规则止损（KPI 核心，必填）
    review_note: str | None = None


class AccountUpdate(BaseModel):
    market: str
    initial_capital: float = Field(..., gt=0)


# ════════════════════════════════════════════════════════════
# 序列化辅助
# ════════════════════════════════════════════════════════════

def _serialize_watch(w: SepaWatchlistItem) -> dict:
    return {
        "id": w.id,
        "market": w.market,
        "symbol": w.symbol,
        "name": w.name,
        "price": w.price,
        "ma50": w.ma50,
        "ma150": w.ma150,
        "ma200": w.ma200,
        "ma200_rising": w.ma200_rising,
        "high52w": w.high52w,
        "low52w": w.low52w,
        "rs": w.rs,
        "template_pass": w.template_pass,
        "template_detail": w.template_detail,
        "vcp_stage": w.vcp_stage,
        "pivot_price": w.pivot_price,
        "fundamental_note": w.fundamental_note,
        "status": w.status,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


def _serialize_trade(t: SepaTrade) -> dict:
    return {
        "id": t.id,
        "market": t.market,
        "symbol": t.symbol,
        "name": t.name,
        "side": t.side,
        "status": t.status,
        "entry_date": t.entry_date.isoformat() if t.entry_date else None,
        "entry_price": float(t.entry_price),
        "shares": t.shares,
        "amount": float(t.amount),
        "pivot_price": t.pivot_price,
        "stop_price": float(t.stop_price),
        "max_risk": float(t.max_risk),
        "max_risk_pct": t.max_risk_pct,
        "entry_reason": t.entry_reason,
        "risky_entry": t.risky_entry,
        "exit_date": t.exit_date.isoformat() if t.exit_date else None,
        "exit_price": float(t.exit_price) if t.exit_price is not None else None,
        "pnl_pct": t.pnl_pct,
        "pnl_amount": float(t.pnl_amount) if t.pnl_amount is not None else None,
        "exit_reason": t.exit_reason,
        "followed_rule": t.followed_rule,
        "review_note": t.review_note,
    }


def _apply_template(w: SepaWatchlistItem) -> None:
    """根据当前数据重判 8 条模板，写回 template_pass/detail/status。"""
    all_pass, detail = svc.evaluate_trend_template(
        price=w.price, ma50=w.ma50, ma150=w.ma150, ma200=w.ma200,
        ma200_rising=w.ma200_rising, high52w=w.high52w, low52w=w.low52w, rs=w.rs,
    )
    w.template_pass = all_pass
    w.template_detail = detail
    # 数据是否录全
    has_all_data = all(
        v is not None for v in (w.price, w.ma50, w.ma150, w.ma200, w.high52w, w.low52w, w.rs)
    )
    if not has_all_data:
        w.status = "candidate"
    else:
        w.status = "passed" if all_pass else "rejected"


# ════════════════════════════════════════════════════════════
# 公开 GET
# ════════════════════════════════════════════════════════════

@router.get("/markets")
async def list_markets(db: AsyncSession = Depends(get_db)):
    """三市场账户概要（用于前端市场切换器）。"""
    out = []
    for m in SEPA_MARKETS:
        state = await svc.compute_account_state(db, m)
        out.append({
            "market": m,
            "currency": SEPA_CURRENCY[m],
            "symbol": SEPA_CURRENCY_SYMBOL[m],
            "label": {"CN": "A股", "HK": "港股", "US": "美股"}[m],
            "total_equity": state["total_equity"],
            "total_pnl_pct": state["total_pnl_pct"],
            "circuit_breaker_hit": state["circuit_breaker_hit"],
            "holdings_count": len(state["holdings"]),
        })
    return {"items": out}


@router.get("/gate")
async def get_gate(market: str = Query(...), db: AsyncSession = Depends(get_db)):
    """市场闸门状态。不存在则返回默认关闭状态。"""
    _check_market(market)
    res = await db.execute(select(SepaMarketGate).where(SepaMarketGate.market == market))
    g = res.scalar_one_or_none()
    if g is None:
        return {
            "market": market, "index_above_ma50": False, "ma50_trending_up": False,
            "breadth_healthy": False, "new_highs_gt_lows": False, "gate_open": False,
            "note": None, "updated_at": None,
        }
    return {
        "market": g.market,
        "index_above_ma50": g.index_above_ma50,
        "ma50_trending_up": g.ma50_trending_up,
        "breadth_healthy": g.breadth_healthy,
        "new_highs_gt_lows": g.new_highs_gt_lows,
        "gate_open": g.gate_open,
        "note": g.note,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
    }


@router.get("/watchlist")
async def get_watchlist(
    market: str = Query(...),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """股池列表（可按 status 筛选）。"""
    _check_market(market)
    stmt = select(SepaWatchlistItem).where(SepaWatchlistItem.market == market)
    if status:
        stmt = stmt.where(SepaWatchlistItem.status == status)
    stmt = stmt.order_by(desc(SepaWatchlistItem.template_pass), desc(SepaWatchlistItem.updated_at))
    res = await db.execute(stmt)
    return {"items": [_serialize_watch(w) for w in res.scalars().all()]}


@router.get("/autofill")
async def autofill_indicators(
    market: str = Query(...),
    symbol: str = Query(..., min_length=1, max_length=16),
    db: AsyncSession = Depends(get_db),
):
    """填代码自动带出指标：现价/MA/RS/52周高低（按市场，能取多少算多少）。"""
    _check_market(market)
    return await svc.fetch_sepa_indicators(market, symbol.strip(), db)


@router.get("/watchlist/{item_id}")
async def get_watchlist_item(item_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(SepaWatchlistItem).where(SepaWatchlistItem.id == item_id))
    w = res.scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="标的不存在")
    return _serialize_watch(w)


@router.get("/account")
async def get_account(market: str = Query(...), db: AsyncSession = Depends(get_db)):
    """账户总览 + 持仓列表（含浮动盈亏、距止损、止损触发标记）。"""
    _check_market(market)
    return await svc.compute_account_state(db, market)


@router.get("/kpi")
async def get_kpi(
    market: str = Query(...),
    period: str = Query("all", pattern=r"^(all|week)$"),
    db: AsyncSession = Depends(get_db),
):
    """KPI 仪表盘。"""
    _check_market(market)
    return await svc.compute_kpi(db, market, period)


@router.get("/trades")
async def get_trades(
    market: str = Query(...),
    filter: str = Query("all", pattern=r"^(all|open|closed|win|loss|violation)$"),
    db: AsyncSession = Depends(get_db),
):
    """交易日志（filter: all/open/closed/win/loss/violation）。"""
    _check_market(market)
    stmt = select(SepaTrade).where(SepaTrade.market == market).order_by(desc(SepaTrade.entry_date), desc(SepaTrade.id))
    res = await db.execute(stmt)
    trades = list(res.scalars().all())

    def _match(t: SepaTrade) -> bool:
        if filter == "open":
            return t.status == "open"
        if filter == "closed":
            return t.status == "closed"
        if filter == "win":
            return t.status == "closed" and (t.pnl_pct or 0) > 0
        if filter == "loss":
            return t.status == "closed" and (t.pnl_pct or 0) < 0
        if filter == "violation":
            return t.status == "closed" and t.followed_rule is False
        return True

    return {"items": [_serialize_trade(t) for t in trades if _match(t)]}


@router.get("/trades/export")
async def export_trades(market: str = Query(...), db: AsyncSession = Depends(get_db)):
    """导出交易日志为 CSV。"""
    _check_market(market)
    res = await db.execute(
        select(SepaTrade).where(SepaTrade.market == market).order_by(SepaTrade.entry_date)
    )
    trades = res.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "代码", "名称", "状态", "买入日", "买入价", "股数", "金额", "枢轴",
        "止损价", "最大风险", "风险占比%", "卖出日", "卖出价", "盈亏%", "盈亏金额",
        "卖出原因", "是否按规则止损", "买入理由", "复盘备注",
    ])
    for t in trades:
        writer.writerow([
            t.symbol, t.name, t.status, t.entry_date, float(t.entry_price), t.shares,
            float(t.amount), t.pivot_price, float(t.stop_price), float(t.max_risk),
            t.max_risk_pct, t.exit_date or "", float(t.exit_price) if t.exit_price else "",
            t.pnl_pct if t.pnl_pct is not None else "",
            float(t.pnl_amount) if t.pnl_amount is not None else "",
            t.exit_reason or "", "" if t.followed_rule is None else ("是" if t.followed_rule else "否"),
            (t.entry_reason or "").replace("\n", " "), (t.review_note or "").replace("\n", " "),
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sepa_trades_{market}.csv"},
    )


@router.post("/check")
async def check_buy(body: CheckRequest, db: AsyncSession = Depends(get_db)):
    """买点检查清单 + 风险预演（不写库，供下单前实时校验）。"""
    _check_market(body.market)

    # 闸门
    gate_res = await db.execute(select(SepaMarketGate).where(SepaMarketGate.market == body.market))
    gate = gate_res.scalar_one_or_none()
    gate_open = bool(gate and gate.gate_open)

    # 8 条模板（从股池取该标的）
    wl_res = await db.execute(
        select(SepaWatchlistItem).where(
            SepaWatchlistItem.market == body.market, SepaWatchlistItem.symbol == body.symbol
        )
    )
    w = wl_res.scalar_one_or_none()
    template_pass = bool(w and w.template_pass)
    pivot = body.pivot_price if body.pivot_price is not None else (w.pivot_price if w else None)

    # 账户与风险
    acc_state = await svc.compute_account_state(db, body.market)
    risk = svc.compute_risk(
        entry_price=body.entry_price, shares=body.shares,
        account_total=acc_state["total_equity"], stop_price=body.stop_price,
    )
    pivot_info = svc.near_pivot(body.entry_price, pivot)

    checklist = svc.build_checklist(
        gate_open=gate_open,
        template_pass=template_pass,
        vcp_confirmed=body.vcp_confirmed,
        within_pivot=pivot_info["within_5pct"],
        stop_price_set=body.stop_price is not None and body.stop_price > 0,
    )

    can_submit = (
        checklist["hard_pass"]
        and risk["stop_valid"]
        and not risk["exceeds_risk_limit"]
        and not acc_state["circuit_breaker_hit"]
    )

    return {
        "checklist": checklist,
        "risk": risk,
        "pivot": pivot_info,
        "gate_open": gate_open,
        "template_pass": template_pass,
        "circuit_breaker_hit": acc_state["circuit_breaker_hit"],
        "in_watchlist": w is not None,
        "can_submit": can_submit,
    }


# ════════════════════════════════════════════════════════════
# 后台 Admin — X-Sandbox-Password 头部认证
# ════════════════════════════════════════════════════════════

@router.put("/admin/gate")
async def update_gate(
    body: GateUpdate, _=Depends(_require_admin), db: AsyncSession = Depends(get_db)
):
    """更新市场闸门（4 项全 True → 闸门开启）。"""
    _check_market(body.market)
    gate_open = (
        body.index_above_ma50 and body.ma50_trending_up
        and body.breadth_healthy and body.new_highs_gt_lows
    )
    res = await db.execute(select(SepaMarketGate).where(SepaMarketGate.market == body.market))
    g = res.scalar_one_or_none()
    if g is None:
        g = SepaMarketGate(market=body.market)
        db.add(g)
    g.index_above_ma50 = body.index_above_ma50
    g.ma50_trending_up = body.ma50_trending_up
    g.breadth_healthy = body.breadth_healthy
    g.new_highs_gt_lows = body.new_highs_gt_lows
    g.gate_open = gate_open
    g.note = body.note
    await db.commit()
    logger.info("SEPA gate updated: market=%s open=%s", body.market, gate_open)
    return {"ok": True, "market": body.market, "gate_open": gate_open}


@router.post("/admin/watchlist")
async def add_watchlist(
    body: WatchlistCreate, _=Depends(_require_admin), db: AsyncSession = Depends(get_db)
):
    """添加股池标的，自动判定 8 条趋势模板。"""
    _check_market(body.market)
    existing = await db.execute(
        select(SepaWatchlistItem).where(
            SepaWatchlistItem.market == body.market, SepaWatchlistItem.symbol == body.symbol
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"{body.symbol} 已在 {body.market} 股池中")

    w = SepaWatchlistItem(
        market=body.market, symbol=body.symbol, name=body.name,
        price=body.price, ma50=body.ma50, ma150=body.ma150, ma200=body.ma200,
        ma200_rising=body.ma200_rising, high52w=body.high52w, low52w=body.low52w, rs=body.rs,
        vcp_stage=body.vcp_stage, pivot_price=body.pivot_price, fundamental_note=body.fundamental_note,
    )
    _apply_template(w)
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return _serialize_watch(w)


@router.put("/admin/watchlist/{item_id}")
async def update_watchlist(
    item_id: int, body: WatchlistUpdate, _=Depends(_require_admin), db: AsyncSession = Depends(get_db)
):
    """更新股池标的数据并重判 8 条模板。"""
    res = await db.execute(select(SepaWatchlistItem).where(SepaWatchlistItem.id == item_id))
    w = res.scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="标的不存在")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(w, field, val)
    _apply_template(w)
    await db.commit()
    await db.refresh(w)
    return _serialize_watch(w)


@router.delete("/admin/watchlist/{item_id}")
async def delete_watchlist(
    item_id: int, _=Depends(_require_admin), db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(SepaWatchlistItem).where(SepaWatchlistItem.id == item_id))
    w = res.scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="标的不存在")
    await db.delete(w)
    await db.commit()
    return {"ok": True}


@router.post("/admin/trades")
async def open_trade(
    body: TradeOpen, _=Depends(_require_admin), db: AsyncSession = Depends(get_db)
):
    """开仓 — M7 纪律强制引擎逐条拦截。"""
    _check_market(body.market)

    # ① 账户熔断检查
    acc_state = await svc.compute_account_state(db, body.market)
    if acc_state["circuit_breaker_hit"]:
        raise HTTPException(status_code=423, detail="账户已触及 -15% 熔断线，禁止开新仓，请强制复盘")

    # ② 市场闸门
    gate_res = await db.execute(select(SepaMarketGate).where(SepaMarketGate.market == body.market))
    gate = gate_res.scalar_one_or_none()
    if not (gate and gate.gate_open):
        raise HTTPException(status_code=423, detail="市场闸门关闭，禁止开新仓（仅可管理已有持仓）")

    # ③ 8 条趋势模板（必须在股池且 passed）
    wl_res = await db.execute(
        select(SepaWatchlistItem).where(
            SepaWatchlistItem.market == body.market, SepaWatchlistItem.symbol == body.symbol
        )
    )
    w = wl_res.scalar_one_or_none()
    if not (w and w.template_pass):
        raise HTTPException(status_code=422, detail="该标的未通过 8 条趋势模板（或不在股池中），禁止买入")

    # ④ VCP 形态确认
    if not body.vcp_confirmed:
        raise HTTPException(status_code=422, detail="未确认 VCP 形态，禁止买入")

    # ⑤ 止损价必须低于买入价
    if body.stop_price >= body.entry_price:
        raise HTTPException(status_code=422, detail="止损价必须低于买入价（做多）")

    # ⑥ 单笔最大亏损 ≤ 1.5%
    risk = svc.compute_risk(
        entry_price=body.entry_price, shares=body.shares,
        account_total=acc_state["total_equity"], stop_price=body.stop_price,
    )
    if risk["exceeds_risk_limit"]:
        raise HTTPException(
            status_code=422,
            detail=f"单笔最大亏损 {risk['max_loss_pct']}% 超过 {svc.RISK_LIMIT_PCT}% 上限，禁止下单",
        )

    # ⑦ 距枢轴 >5% 追高 → 需 force_risky 强制确认
    pivot = body.pivot_price if body.pivot_price is not None else w.pivot_price
    pivot_info = svc.near_pivot(body.entry_price, pivot)
    risky = False
    if pivot_info["within_5pct"] is False:
        if not body.force_risky:
            raise HTTPException(
                status_code=422,
                detail=f"当前价距枢轴 {pivot_info['distance_pct']}% 已追高（>5%），如确认请勾选强制下单",
            )
        risky = True

    # ── 通过全部拦截，建仓 ──
    amount = body.entry_price * body.shares
    trade = SepaTrade(
        market=body.market, symbol=body.symbol, name=body.name or (w.name if w else ""),
        side="buy", status="open",
        entry_date=body.entry_date, entry_price=body.entry_price, shares=body.shares,
        amount=amount, pivot_price=pivot, stop_price=body.stop_price,
        max_risk=risk["max_loss"], max_risk_pct=risk["max_loss_pct"],
        entry_reason=body.entry_reason, risky_entry=risky,
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)
    logger.info("SEPA open: %s %s %d@%.4f stop=%.4f risk=%.2f%%",
                body.market, body.symbol, body.shares, body.entry_price, body.stop_price, risk["max_loss_pct"])
    return _serialize_trade(trade)


@router.post("/admin/trades/{trade_id}/close")
async def close_trade(
    trade_id: int, body: TradeClose, _=Depends(_require_admin), db: AsyncSession = Depends(get_db)
):
    """平仓 — 强制标注「是否按规则止损」（KPI 核心）。"""
    res = await db.execute(select(SepaTrade).where(SepaTrade.id == trade_id))
    t = res.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="交易不存在")
    if t.status == "closed":
        raise HTTPException(status_code=409, detail="该交易已平仓")

    entry = float(t.entry_price)
    pnl_amount = (body.exit_price - entry) * t.shares
    pnl_pct = (body.exit_price / entry - 1) * 100

    t.status = "closed"
    t.exit_date = body.exit_date
    t.exit_price = body.exit_price
    t.pnl_amount = round(pnl_amount, 4)
    t.pnl_pct = round(pnl_pct, 2)
    t.exit_reason = body.exit_reason
    t.followed_rule = body.followed_rule
    t.review_note = body.review_note
    await db.commit()
    await db.refresh(t)
    logger.info("SEPA close: id=%d pnl=%.2f%% followed_rule=%s", trade_id, pnl_pct, body.followed_rule)
    return _serialize_trade(t)


@router.delete("/admin/trades/{trade_id}")
async def delete_trade(
    trade_id: int, _=Depends(_require_admin), db: AsyncSession = Depends(get_db)
):
    """撤销交易记录。"""
    res = await db.execute(select(SepaTrade).where(SepaTrade.id == trade_id))
    t = res.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="交易不存在")
    await db.delete(t)
    await db.commit()
    return {"ok": True}


@router.put("/admin/account")
async def update_account(
    body: AccountUpdate, _=Depends(_require_admin), db: AsyncSession = Depends(get_db)
):
    """修改账户初始资金。"""
    _check_market(body.market)
    acc = await svc.get_or_create_account(db, body.market)
    from decimal import Decimal
    acc.initial_capital = Decimal(str(body.initial_capital))
    await db.commit()
    return {"ok": True, "market": body.market, "initial_capital": body.initial_capital}
