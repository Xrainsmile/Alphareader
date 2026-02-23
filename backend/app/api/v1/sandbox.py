"""模拟仓 API — 前端展示 + 后台管理端点。

前端 GET（公开）：
  GET /sandbox/overview     — 净值曲线 + 概览指标
  GET /sandbox/stocks       — 观察池列表（含最新推演摘要）
  GET /sandbox/stocks/{id}  — 单只股票详情（推演卡片流 + 交易记录）

后台 POST/DELETE（密码保护）：
  POST   /sandbox/admin/stocks       — 添加观察池股票
  DELETE /sandbox/admin/stocks/{id}  — 移除观察池股票
  POST   /sandbox/admin/analyses     — 新增推演记录
  POST   /sandbox/admin/trades       — 新增交易记录

定时触发：
  POST /sandbox/nav/compute  — 计算当日净值（由 scheduler 或手动调用）
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dashboard import _verify_token
from app.database import get_db
from app.models.sandbox import SandboxAnalysis, SandboxNav, SandboxStock, SandboxTrade

logger = logging.getLogger("alphareader.sandbox")

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


# ════════════════════════════════════════════════════════════
# Pydantic Schemas
# ════════════════════════════════════════════════════════════

class StockCreate(BaseModel):
    ts_code: str = Field(..., max_length=10)
    name: str = Field("", max_length=32)
    reason: str | None = None

class AnalysisCreate(BaseModel):
    stock_id: int
    ts_code: str = Field(..., max_length=10)
    title: str = Field(..., max_length=128)
    direction: str = Field("neutral", pattern=r"^(bullish|bearish|neutral)$")
    summary: str
    content: str | None = None
    target_price: float | None = None
    stop_loss: float | None = None

class TradeCreate(BaseModel):
    stock_id: int
    ts_code: str = Field(..., max_length=10)
    action: str = Field(..., pattern=r"^(buy|sell)$")
    price: float = Field(..., gt=0)
    shares: int = Field(..., gt=0)
    trade_date: date
    note: str | None = None


# ════════════════════════════════════════════════════════════
# 前端 GET — 公开接口
# ════════════════════════════════════════════════════════════

@router.get("/overview")
async def sandbox_overview(
    days: int = Query(90, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
):
    """净值曲线 + 概览指标。"""
    # 净值曲线
    nav_result = await db.execute(
        select(SandboxNav)
        .order_by(desc(SandboxNav.trade_date))
        .limit(days)
    )
    nav_rows = nav_result.scalars().all()
    nav_rows.reverse()  # 按时间正序

    # 持仓 / 观察概览
    count_result = await db.execute(
        select(
            func.count().filter(SandboxStock.status == "holding").label("holding"),
            func.count().filter(SandboxStock.status == "watching").label("watching"),
            func.count().filter(SandboxStock.status == "exited").label("exited"),
        ).select_from(SandboxStock)
    )
    counts = count_result.one()

    latest_nav = nav_rows[-1] if nav_rows else None

    return {
        "nav_series": [
            {
                "date": str(n.trade_date),
                "nav": round(float(n.nav), 4),
                "total_pnl": round(float(n.total_pnl), 2),
                "market_value": float(n.total_market_value),
                "cash": float(n.cash),
            }
            for n in nav_rows
        ],
        "summary": {
            "latest_nav": round(float(latest_nav.nav), 4) if latest_nav else 1.0,
            "total_pnl": round(float(latest_nav.total_pnl), 2) if latest_nav else 0.0,
            "holding_count": counts.holding,
            "watching_count": counts.watching,
            "exited_count": counts.exited,
        },
    }


@router.get("/stocks")
async def sandbox_stock_list(
    status: str | None = Query(None, pattern=r"^(watching|holding|exited)$"),
    db: AsyncSession = Depends(get_db),
):
    """观察池列表，附最新一条推演摘要。"""
    query = select(SandboxStock).order_by(desc(SandboxStock.updated_at))
    if status:
        query = query.where(SandboxStock.status == status)
    result = await db.execute(query)
    stocks = result.scalars().all()

    items = []
    for s in stocks:
        # 最新推演
        latest_analysis = await db.execute(
            select(SandboxAnalysis)
            .where(SandboxAnalysis.stock_id == s.id)
            .order_by(desc(SandboxAnalysis.created_at))
            .limit(1)
        )
        la = latest_analysis.scalar_one_or_none()

        # 持仓统计
        trade_result = await db.execute(
            select(
                func.sum(
                    func.case(
                        (SandboxTrade.action == "buy", SandboxTrade.shares),
                        else_=-SandboxTrade.shares,
                    )
                ).label("net_shares"),
            ).where(SandboxTrade.stock_id == s.id)
        )
        net_shares = trade_result.scalar() or 0

        items.append({
            "id": s.id,
            "ts_code": s.ts_code,
            "name": s.name,
            "status": s.status,
            "reason": s.reason,
            "net_shares": int(net_shares),
            "added_at": s.added_at.isoformat() if s.added_at else None,
            "latest_analysis": {
                "id": la.id,
                "title": la.title,
                "direction": la.direction,
                "summary": la.summary,
                "created_at": la.created_at.isoformat(),
            } if la else None,
        })

    return {"items": items, "total": len(items)}


@router.get("/stocks/{stock_id}")
async def sandbox_stock_detail(
    stock_id: int,
    db: AsyncSession = Depends(get_db),
):
    """单只股票详情 — 推演卡片流 + 交易记录。"""
    stock = await db.get(SandboxStock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    # 推演列表
    analyses_result = await db.execute(
        select(SandboxAnalysis)
        .where(SandboxAnalysis.stock_id == stock_id)
        .order_by(desc(SandboxAnalysis.created_at))
    )
    analyses = analyses_result.scalars().all()

    # 交易记录
    trades_result = await db.execute(
        select(SandboxTrade)
        .where(SandboxTrade.stock_id == stock_id)
        .order_by(desc(SandboxTrade.trade_date))
    )
    trades = trades_result.scalars().all()

    # 净持仓
    net_shares = sum(
        t.shares if t.action == "buy" else -t.shares for t in trades
    )

    return {
        "stock": {
            "id": stock.id,
            "ts_code": stock.ts_code,
            "name": stock.name,
            "status": stock.status,
            "reason": stock.reason,
            "net_shares": net_shares,
            "added_at": stock.added_at.isoformat() if stock.added_at else None,
        },
        "analyses": [
            {
                "id": a.id,
                "title": a.title,
                "direction": a.direction,
                "summary": a.summary,
                "content": a.content,
                "target_price": a.target_price,
                "stop_loss": a.stop_loss,
                "created_at": a.created_at.isoformat(),
            }
            for a in analyses
        ],
        "trades": [
            {
                "id": t.id,
                "action": t.action,
                "price": float(t.price),
                "shares": t.shares,
                "trade_date": str(t.trade_date),
                "note": t.note,
                "created_at": t.created_at.isoformat(),
            }
            for t in trades
        ],
    }


# ════════════════════════════════════════════════════════════
# 后台 Admin — 密码保护（复用 Dashboard cookie 验证）
# ════════════════════════════════════════════════════════════


def _require_admin(dash_token: str = Cookie(None)):
    """验证 Dashboard cookie，复用现有认证机制。"""
    if settings.DASHBOARD_PASSWORD and not _verify_token(dash_token or ""):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/admin/stocks")
async def admin_add_stock(
    body: StockCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """添加观察池股票。"""
    # 检查重复
    existing = await db.execute(
        select(SandboxStock).where(SandboxStock.ts_code == body.ts_code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"{body.ts_code} already in sandbox")

    stock = SandboxStock(
        ts_code=body.ts_code,
        name=body.name,
        reason=body.reason,
    )
    db.add(stock)
    await db.commit()
    await db.refresh(stock)
    logger.info("Added sandbox stock: %s %s", stock.ts_code, stock.name)
    return {"id": stock.id, "ts_code": stock.ts_code, "name": stock.name}


@router.delete("/admin/stocks/{stock_id}")
async def admin_remove_stock(
    stock_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """移除观察池股票（标记为 exited）。"""
    stock = await db.get(SandboxStock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    stock.status = "exited"
    await db.commit()
    logger.info("Removed sandbox stock: %s %s (set to exited)", stock.ts_code, stock.name)
    return {"ok": True}


@router.post("/admin/analyses")
async def admin_add_analysis(
    body: AnalysisCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """新增推演记录。"""
    stock = await db.get(SandboxStock, body.stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    analysis = SandboxAnalysis(
        stock_id=body.stock_id,
        ts_code=body.ts_code,
        title=body.title,
        direction=body.direction,
        summary=body.summary,
        content=body.content,
        target_price=body.target_price,
        stop_loss=body.stop_loss,
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    logger.info("Added analysis #%d for %s", analysis.id, body.ts_code)
    return {"id": analysis.id}


@router.post("/admin/trades")
async def admin_add_trade(
    body: TradeCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """新增交易记录，自动更新股票状态。"""
    stock = await db.get(SandboxStock, body.stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    trade = SandboxTrade(
        stock_id=body.stock_id,
        ts_code=body.ts_code,
        action=body.action,
        price=Decimal(str(body.price)),
        shares=body.shares,
        trade_date=body.trade_date,
        note=body.note,
    )
    db.add(trade)
    await db.flush()  # 确保新 trade 写入 session，后续查询能读到

    # 计算净持仓，更新状态（flush 后查询已包含新 trade）
    all_trades_result = await db.execute(
        select(SandboxTrade).where(SandboxTrade.stock_id == body.stock_id)
    )
    all_trades = all_trades_result.scalars().all()
    net = sum(t.shares if t.action == "buy" else -t.shares for t in all_trades)

    if net > 0:
        stock.status = "holding"
    elif net == 0 and body.action == "sell":
        stock.status = "exited"

    await db.commit()
    await db.refresh(trade)
    logger.info(
        "Trade #%d: %s %s x%d @%.2f on %s (net_shares=%d)",
        trade.id, body.action, body.ts_code, body.shares, body.price, body.trade_date, net,
    )
    return {"id": trade.id, "net_shares": net, "stock_status": stock.status}


# ════════════════════════════════════════════════════════════
# NAV 计算
# ════════════════════════════════════════════════════════════

INITIAL_CAPITAL = Decimal("1000000")  # 100 万虚拟初始资金


async def _compute_nav_core(db: AsyncSession, calc_date: date) -> dict | None:
    """NAV 核心计算逻辑（供 API 端点和 scheduler 共用）。

    返回 dict 包含 nav/total_pnl/market_value/cash，若无交易返回 None。
    """
    from app.models.stock import StockDailyQuote
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # 所有交易
    trades_result = await db.execute(
        select(SandboxTrade).where(SandboxTrade.trade_date <= calc_date)
    )
    all_trades = trades_result.scalars().all()

    if not all_trades:
        return None

    # 按股票汇总持仓
    positions: dict[str, int] = {}  # ts_code -> net_shares
    cash_flow = Decimal("0")  # 净流出（买入为正，卖出为负）
    for t in all_trades:
        code = t.ts_code
        if t.action == "buy":
            positions[code] = positions.get(code, 0) + t.shares
            cash_flow += t.price * t.shares
        else:
            positions[code] = positions.get(code, 0) - t.shares
            cash_flow -= t.price * t.shares

    cash = INITIAL_CAPITAL - cash_flow

    # 取收盘价（优先取 calc_date，若无则取最近交易日）
    total_market_value = Decimal("0")
    for code, shares in positions.items():
        if shares <= 0:
            continue
        price_result = await db.execute(
            select(StockDailyQuote.close)
            .where(
                StockDailyQuote.ts_code == code,
                StockDailyQuote.trade_date <= calc_date,
            )
            .order_by(desc(StockDailyQuote.trade_date))
            .limit(1)
        )
        close_price = price_result.scalar()
        if close_price:
            total_market_value += Decimal(str(close_price)) * shares

    nav_value = float((total_market_value + cash) / INITIAL_CAPITAL)
    total_pnl = round((nav_value - 1.0) * 100, 2)

    # Upsert NAV
    stmt = pg_insert(SandboxNav).values(
        trade_date=calc_date,
        total_market_value=total_market_value,
        cash=cash,
        nav=nav_value,
        total_pnl=total_pnl,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_sandbox_nav_date",
        set_={
            "total_market_value": stmt.excluded.total_market_value,
            "cash": stmt.excluded.cash,
            "nav": stmt.excluded.nav,
            "total_pnl": stmt.excluded.total_pnl,
        },
    )
    await db.execute(stmt)
    await db.commit()

    logger.info(
        "NAV computed for %s: nav=%.4f, pnl=%.2f%%, mv=%.2f, cash=%.2f",
        calc_date, nav_value, total_pnl, total_market_value, cash,
    )
    return {
        "date": str(calc_date),
        "nav": round(nav_value, 4),
        "total_pnl": total_pnl,
        "market_value": float(total_market_value),
        "cash": float(cash),
    }


@router.post("/nav/compute")
async def compute_nav(
    target_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """计算指定日期（默认今天）的净值。

    逻辑：
    1. 找出所有 holding 状态的股票
    2. 对每只股票计算净持仓 & 从 stock_daily_quote 取收盘价
    3. 市值 = Σ(净持仓 × 收盘价)
    4. 现金 = 初始资金 - Σ(买入金额) + Σ(卖出金额)
    5. NAV = (市值 + 现金) / 初始资金
    """
    calc_date = target_date or date.today()
    result = await _compute_nav_core(db, calc_date)
    if result is None:
        return {"date": str(calc_date), "nav": 1.0, "message": "No trades yet"}
    return result
