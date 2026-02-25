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

import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func, select
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
    score: float = Field(..., ge=0, le=5)
    trend: str = Field(..., max_length=200)
    pattern: str = Field(..., max_length=200)
    volume_price: str = Field(..., max_length=200)
    discipline_action: str = Field(..., pattern=r"^(retain|gray|research|churn)$")
    risk_type: str | None = Field(None, pattern=r"^(top|bottom)$")
    risk_price: float | None = None
    risk_note: str | None = Field(None, max_length=200)
    pnl_thinking: str = Field(..., max_length=200)
    verdict: str = Field(..., max_length=200)

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

    # 按 discipline_action 统计（基于每只活跃股票的最新推演记录）
    active_stocks_result = await db.execute(
        select(SandboxStock.id).where(SandboxStock.status.in_(["holding", "watching"]))
    )
    active_ids = [row[0] for row in active_stocks_result.all()]

    discipline_counts = {"retain": 0, "gray": 0, "research": 0, "churn": 0}
    for sid in active_ids:
        la_result = await db.execute(
            select(SandboxAnalysis.discipline_action)
            .where(SandboxAnalysis.stock_id == sid)
            .order_by(desc(SandboxAnalysis.created_at))
            .limit(1)
        )
        action = la_result.scalar()
        if action and action in discipline_counts:
            discipline_counts[action] += 1
        else:
            discipline_counts["retain"] += 1  # 无推演记录默认留存

    latest_nav = nav_rows[-1] if nav_rows else None
    prev_nav = nav_rows[-2] if len(nav_rows) >= 2 else None

    # 日内收益 = (latest_nav - prev_nav) / prev_nav * 100
    daily_pnl = 0.0
    if latest_nav and prev_nav and prev_nav.nav:
        daily_pnl = round((float(latest_nav.nav) - float(prev_nav.nav)) / float(prev_nav.nav) * 100, 2)

    # 仓位 = market_value / (market_value + cash) * 100
    position_pct = 0.0
    total_assets = float(INITIAL_CAPITAL)
    if latest_nav:
        total_assets = float(latest_nav.total_market_value) + float(latest_nav.cash)
        if total_assets > 0:
            position_pct = round(float(latest_nav.total_market_value) / total_assets * 100, 1)

    # 观察池总数（不含退出）
    total_active = counts.holding + counts.watching

    # ── 多区间收益率计算 ──
    # 查询全部净值记录（用于跨区间计算）
    all_nav_result = await db.execute(
        select(SandboxNav).order_by(SandboxNav.trade_date)
    )
    all_navs = all_nav_result.scalars().all()

    def _find_nav_at_or_before(navs, target_date):
        """找到 target_date 当天或之前最近的净值记录。"""
        best = None
        for n in navs:
            if n.trade_date <= target_date:
                best = n
            else:
                break
        return best

    def _calc_return(navs, start_date):
        """计算从 start_date 到最新的收益率。"""
        if not navs:
            return 0.0
        base = _find_nav_at_or_before(navs, start_date)
        latest = navs[-1]
        if base is None or float(base.nav) == 0:
            return round(float(latest.total_pnl), 2)
        return round((float(latest.nav) - float(base.nav)) / float(base.nav) * 100, 2)

    today = date.today()
    inception_date = date(2026, 2, 13)  # 成立日

    # 成立以来收益率
    pnl_since_inception = _calc_return(all_navs, inception_date) if all_navs else 0.0

    # 近一年
    pnl_1y = _calc_return(all_navs, today - timedelta(days=365))

    # 近三月
    pnl_3m = _calc_return(all_navs, today - timedelta(days=90))

    # 今年以来 (YTD)
    ytd_start = date(today.year, 1, 1)
    pnl_ytd = _calc_return(all_navs, ytd_start)

    # ── 持仓标的仓位分布（供环状图使用）──
    holdings_result = await db.execute(
        select(SandboxStock).where(SandboxStock.status == "holding")
    )
    holding_stocks = holdings_result.scalars().all()

    from app.models.stock import StockDailyQuote

    holdings_data = []
    for hs in holding_stocks:
        # 计算净持仓
        ht_result = await db.execute(
            select(
                func.sum(
                    case(
                        (SandboxTrade.action == "buy", SandboxTrade.shares),
                        else_=-SandboxTrade.shares,
                    )
                )
            ).where(SandboxTrade.stock_id == hs.id)
        )
        net_shares = ht_result.scalar() or 0
        if int(net_shares) <= 0:
            continue

        # 取收盘价
        hp_result = await db.execute(
            select(StockDailyQuote.close)
            .where(StockDailyQuote.ts_code == hs.ts_code)
            .order_by(desc(StockDailyQuote.trade_date))
            .limit(1)
        )
        close_price = hp_result.scalar()
        if close_price is None:
            fb = await db.execute(
                select(SandboxTrade.price)
                .where(SandboxTrade.ts_code == hs.ts_code)
                .order_by(desc(SandboxTrade.trade_date), desc(SandboxTrade.id))
                .limit(1)
            )
            close_price = fb.scalar()
        if close_price:
            mv = float(close_price) * int(net_shares)
            holdings_data.append({
                "name": hs.name,
                "ts_code": hs.ts_code,
                "market_value": round(mv, 2),
            })

    # 计算各标的仓位百分比
    total_mv_holdings = sum(h["market_value"] for h in holdings_data)
    cash_val = float(latest_nav.cash) if latest_nav else float(INITIAL_CAPITAL)
    pie_total = total_mv_holdings + cash_val
    holdings_pie = []
    for h in sorted(holdings_data, key=lambda x: x["market_value"], reverse=True):
        pct = round(h["market_value"] / pie_total * 100, 1) if pie_total > 0 else 0
        holdings_pie.append({
            "name": h["name"],
            "ts_code": h["ts_code"],
            "market_value": h["market_value"],
            "pct": pct,
        })
    cash_pct = round(cash_val / pie_total * 100, 1) if pie_total > 0 else 100
    holdings_pie.append({
        "name": "现金",
        "ts_code": "",
        "market_value": round(cash_val, 2),
        "pct": cash_pct,
    })

    return {
        "nav_series": [
            {
                "date": str(n.trade_date),
                "nav": round(float(n.nav), 4),
                "total_pnl": round(float(n.total_pnl), 2),
                "market_value": float(n.total_market_value),
                "cash": float(n.cash),
                "total_assets": round(float(n.total_market_value) + float(n.cash), 2),
            }
            for n in nav_rows
        ],
        "summary": {
            "latest_nav": round(float(latest_nav.nav), 4) if latest_nav else 1.0,
            "total_pnl": round(float(latest_nav.total_pnl), 2) if latest_nav else 0.0,
            "total_assets": round(total_assets, 2),
            "daily_pnl": daily_pnl,
            "position_pct": position_pct,
            "holding_count": counts.holding,
            "watching_count": counts.watching,
            "exited_count": counts.exited,
            "total_active": total_active,
            "latest_date": str(latest_nav.trade_date) if latest_nav else None,
            "retain_count": discipline_counts["retain"],
            "gray_count": discipline_counts["gray"],
            "research_count": discipline_counts["research"],
            "churn_count": discipline_counts["churn"],
            "pnl_since_inception": pnl_since_inception,
            "pnl_1y": pnl_1y,
            "pnl_3m": pnl_3m,
            "pnl_ytd": pnl_ytd,
        },
        "holdings_pie": holdings_pie,
    }


@router.get("/stock-search")
async def sandbox_stock_search(
    q: str = Query(..., min_length=1, max_length=20, description="搜索关键词（代码或名称）"),
    db: AsyncSession = Depends(get_db),
):
    """轻量级股票搜索 — 从行情表去重搜索代码/名称，供 admin 页面选股使用。"""
    from app.models.stock import StockDailyQuote

    keyword = f"%{q.strip()}%"
    # 从行情表查找不重复的 (ts_code, name)，按代码排序，最多返回 20 条
    result = await db.execute(
        select(StockDailyQuote.ts_code, StockDailyQuote.name)
        .where(
            (StockDailyQuote.ts_code.ilike(keyword)) | (StockDailyQuote.name.ilike(keyword))
        )
        .group_by(StockDailyQuote.ts_code, StockDailyQuote.name)
        .order_by(StockDailyQuote.ts_code)
        .limit(20)
    )
    rows = result.all()
    return {"items": [{"ts_code": r.ts_code, "name": r.name} for r in rows]}


@router.get("/stocks")
async def sandbox_stock_list(
    status: str | None = Query(None, pattern=r"^(watching|holding|exited)$"),
    discipline: str | None = Query(None, pattern=r"^(retain|gray|research|churn)$"),
    q: str | None = Query(None, max_length=20, description="搜索：代码或名称"),
    holding_only: bool = Query(False, description="仅显示持仓票"),
    db: AsyncSession = Depends(get_db),
):
    """观察池列表，附最新一条推演摘要。支持按 discipline_action 筛选、搜索、仅持仓。
    默认排除已退出(exited)的股票，除非显式传入 status=exited。"""
    from app.models.stock import StockDailyQuote

    query = select(SandboxStock).order_by(desc(SandboxStock.updated_at))
    if status:
        query = query.where(SandboxStock.status == status)
    else:
        query = query.where(SandboxStock.status != "exited")
    if holding_only:
        query = query.where(SandboxStock.status == "holding")
    if q:
        keyword = f"%{q.strip()}%"
        query = query.where(
            (SandboxStock.ts_code.ilike(keyword)) | (SandboxStock.name.ilike(keyword))
        )
    result = await db.execute(query)
    stocks = result.scalars().all()

    # 从 SandboxNav 表读取最新快照（轻量级，不触发实时行情拉取）
    nav_result = await db.execute(
        select(SandboxNav).order_by(desc(SandboxNav.trade_date)).limit(1)
    )
    latest_nav = nav_result.scalar_one_or_none()
    total_assets = float(latest_nav.total_market_value + latest_nav.cash) if latest_nav else float(INITIAL_CAPITAL)

    items = []
    for s in stocks:
        # 最新推演（按 ID 倒序，比 created_at 更可靠）
        latest_analysis = await db.execute(
            select(SandboxAnalysis)
            .where(SandboxAnalysis.stock_id == s.id)
            .order_by(desc(SandboxAnalysis.id))
            .limit(1)
        )
        la = latest_analysis.scalar_one_or_none()

        # 推演记录统计（总数 + 最新更新时间）
        analysis_stats = await db.execute(
            select(
                func.count(SandboxAnalysis.id).label("count"),
                func.max(SandboxAnalysis.created_at).label("latest_at"),
            ).where(SandboxAnalysis.stock_id == s.id)
        )
        stats_row = analysis_stats.one()
        analysis_count = stats_row.count or 0
        analysis_latest_at = stats_row.latest_at

        # 按 discipline_action 过滤
        if discipline:
            action = la.discipline_action if la else "retain"
            if action != discipline:
                continue

        # 持仓统计
        trade_result = await db.execute(
            select(
                func.sum(
                    case(
                        (SandboxTrade.action == "buy", SandboxTrade.shares),
                        else_=-SandboxTrade.shares,
                    )
                ).label("net_shares"),
            ).where(SandboxTrade.stock_id == s.id)
        )
        net_shares = trade_result.scalar() or 0

        # 计算持仓比例（持仓市值 / 总资产）— 使用行情表数据，不触发实时拉取
        position_pct = 0.0
        if int(net_shares) > 0:
            # 优先：行情表收盘价
            price_result = await db.execute(
                select(StockDailyQuote.close)
                .where(StockDailyQuote.ts_code == s.ts_code)
                .order_by(desc(StockDailyQuote.trade_date))
                .limit(1)
            )
            close_price = price_result.scalar()
            if close_price is None:
                # 回退：最近交易价格
                fb = await db.execute(
                    select(SandboxTrade.price)
                    .where(SandboxTrade.ts_code == s.ts_code)
                    .order_by(desc(SandboxTrade.trade_date), desc(SandboxTrade.id))
                    .limit(1)
                )
                close_price = fb.scalar()
                if close_price:
                    close_price = float(close_price)
            if close_price and total_assets > 0:
                market_val = float(close_price) * int(net_shares)
                position_pct = round(market_val / total_assets * 100, 1)

        items.append({
            "id": s.id,
            "ts_code": s.ts_code,
            "name": s.name,
            "status": s.status,
            "reason": s.reason,
            "position_pct": position_pct,
            "added_at": s.added_at.isoformat() if s.added_at else None,
            "analysis_count": analysis_count,
            "analysis_latest_at": analysis_latest_at.isoformat() if analysis_latest_at else None,
            "latest_analysis": {
                "id": la.id,
                "score": la.score,
                "discipline_action": la.discipline_action,
                "verdict": la.verdict,
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
                "score": a.score,
                "trend": a.trend,
                "pattern": a.pattern,
                "volume_price": a.volume_price,
                "discipline_action": a.discipline_action,
                "risk_type": a.risk_type,
                "risk_price": a.risk_price,
                "risk_note": a.risk_note,
                "pnl_thinking": a.pnl_thinking,
                "verdict": a.verdict,
                "created_at": a.created_at.isoformat(),
            }
            for a in analyses
        ],
        "trades": [
            {
                "id": t.id,
                "ts_code": t.ts_code,
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
        score=body.score,
        trend=body.trend,
        pattern=body.pattern,
        volume_price=body.volume_price,
        discipline_action=body.discipline_action,
        risk_type=body.risk_type,
        risk_price=body.risk_price,
        risk_note=body.risk_note,
        pnl_thinking=body.pnl_thinking,
        verdict=body.verdict,
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    logger.info("Added analysis #%d for %s", analysis.id, body.ts_code)
    return {"id": analysis.id}


@router.get("/admin/analyses")
async def admin_list_analyses(
    stock_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """查看所有推演记录，可按 stock_id 筛选。"""
    query = select(SandboxAnalysis).order_by(desc(SandboxAnalysis.created_at))
    if stock_id is not None:
        query = query.where(SandboxAnalysis.stock_id == stock_id)
    result = await db.execute(query)
    analyses = result.scalars().all()

    return {
        "items": [
            {
                "id": a.id,
                "stock_id": a.stock_id,
                "ts_code": a.ts_code,
                "score": a.score,
                "trend": a.trend,
                "pattern": a.pattern,
                "volume_price": a.volume_price,
                "discipline_action": a.discipline_action,
                "risk_type": a.risk_type,
                "risk_price": a.risk_price,
                "risk_note": a.risk_note,
                "pnl_thinking": a.pnl_thinking,
                "verdict": a.verdict,
                "created_at": a.created_at.isoformat(),
            }
            for a in analyses
        ],
        "total": len(analyses),
    }


@router.delete("/admin/analyses/{analysis_id}")
async def admin_delete_analysis(
    analysis_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """删除推演记录。"""
    analysis = await db.get(SandboxAnalysis, analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    await db.delete(analysis)
    await db.commit()
    logger.info("Deleted analysis #%d for %s", analysis_id, analysis.ts_code)
    return {"ok": True}


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
        stock.status = "watching"

    await db.commit()
    await db.refresh(trade)
    logger.info(
        "Trade #%d: %s %s x%d @%.2f on %s (net_shares=%d)",
        trade.id, body.action, body.ts_code, body.shares, body.price, body.trade_date, net,
    )
    return {"id": trade.id, "net_shares": net, "stock_status": stock.status}


@router.delete("/admin/trades/{trade_id}")
async def admin_delete_trade(
    trade_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """撤回（删除）交易记录，重新计算持仓状态。"""
    trade = await db.get(SandboxTrade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    stock_id = trade.stock_id
    ts_code = trade.ts_code

    # 删除该交易
    await db.delete(trade)
    await db.flush()

    # 重新计算该股票净持仓
    remaining_result = await db.execute(
        select(SandboxTrade).where(SandboxTrade.stock_id == stock_id)
    )
    remaining = remaining_result.scalars().all()
    net = sum(t.shares if t.action == "buy" else -t.shares for t in remaining)

    # 更新股票状态
    stock = await db.get(SandboxStock, stock_id)
    if stock:
        if net > 0:
            stock.status = "holding"
        else:
            stock.status = "watching"

    await db.commit()
    logger.info("Deleted trade #%d (%s), net_shares=%d", trade_id, ts_code, net)
    return {"ok": True, "net_shares": net, "stock_status": stock.status if stock else None}


# ════════════════════════════════════════════════════════════
# NAV 计算
# ════════════════════════════════════════════════════════════

INITIAL_CAPITAL = Decimal("104152.59")  # 104,152.59 元初始总资产（NAV=1 的基准）


async def _compute_nav_core(db: AsyncSession, calc_date: date, cash_balance: float | None = None, use_realtime: bool = True, market_value_override: float | None = None) -> dict | None:
    """NAV 核心计算逻辑（供 API 端点和 scheduler 共用）。

    计算公式（标准基金净值算法）：
      初始总资产 = INITIAL_CAPITAL = 104,152.59（NAV=1 的基准）
      当前现金 = cash_balance（手动传入）或 INITIAL_CAPITAL - Σ(买入金额) + Σ(卖出金额)
      持仓市值 = Σ(净持仓 × 不复权最新价)
      当天总资产 = 当前现金 + 持仓市值
      NAV = 当天总资产 / 初始总资产
      收益率 = (NAV - 1) × 100%

    Args:
        db: 数据库 session
        calc_date: 计算日期
        cash_balance: 可选，手动传入的实际现金余额（覆盖从交易推算的值，用于补偿手续费等差异）
        use_realtime: 是否拉取实时不复权行情（默认 True）。scheduler 调用时传 False 避免拖慢进程。

    返回 dict 包含 nav/total_pnl/market_value/cash/total_assets，若无交易返回 None。
    """
    from app.models.stock import StockDailyQuote
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.services.data_fetcher import get_sina_prices, is_etf

    # 所有交易
    trades_result = await db.execute(
        select(SandboxTrade).where(SandboxTrade.trade_date <= calc_date)
    )
    all_trades = trades_result.scalars().all()

    if not all_trades:
        return None

    # 按股票汇总持仓 + 计算现金变动
    positions: dict[str, int] = {}  # ts_code -> net_shares
    cash_flow = Decimal("0")  # 净现金流出（买入为正流出，卖出为负流出）
    for t in all_trades:
        code = t.ts_code
        if t.action == "buy":
            positions[code] = positions.get(code, 0) + t.shares
            cash_flow += t.price * t.shares  # 买入花钱
        else:
            positions[code] = positions.get(code, 0) - t.shares
            cash_flow -= t.price * t.shares  # 卖出回款

    # 当前现金：优先使用手动传入值（含手续费补偿），否则从交易推算
    if cash_balance is not None:
        cash = Decimal(str(cash_balance))
    else:
        cash = INITIAL_CAPITAL - cash_flow

    # 获取持仓代码列表
    holding_codes = [code for code, shares in positions.items() if shares > 0]

    # 获取持仓最新价格（不复权）
    realtime_prices: dict[str, float] = {}
    if use_realtime and holding_codes and calc_date >= date.today():
        # 方式 1: 新浪财经 HTTP 接口（最可靠，不依赖 akshare）
        try:
            realtime_prices = await get_sina_prices(holding_codes)
            if realtime_prices:
                logger.info("NAV: 新浪行情获取成功 %d/%d: %s", len(realtime_prices), len(holding_codes), realtime_prices)
        except Exception as e:
            logger.warning("NAV: 新浪行情获取失败: %s", e)

        # 方式 2: 如果新浪接口也有缺失，尝试 akshare 逐只获取
        missing_codes = [c for c in holding_codes if c not in realtime_prices]
        if missing_codes:
            logger.info("NAV: 新浪行情缺少 %d 只，尝试 akshare: %s", len(missing_codes), missing_codes)
            try:
                from app.services.data_fetcher import get_unadjusted_close
                ak_prices = await get_unadjusted_close(missing_codes)
                if ak_prices:
                    realtime_prices.update(ak_prices)
                    logger.info("NAV: akshare 补全 %d 只: %s", len(ak_prices), ak_prices)
            except Exception as e:
                logger.warning("NAV: akshare 补全失败: %s", e)

    # 计算持仓市值
    total_market_value = Decimal("0")
    holdings_detail = []  # 用于日志输出每只股票的明细
    for code, shares in positions.items():
        if shares <= 0:
            continue

        close_price = None
        price_source = ""

        # 优先级 1: 不复权价格（逐只获取 or 实时行情）
        if code in realtime_prices:
            close_price = realtime_prices[code]
            price_source = "unadjusted"
        else:
            # 优先级 2: 行情表收盘价（注意：前复权，历史日期回退用）
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
            if close_price is not None:
                price_source = "db_qfq"

            # 优先级 3: 最近一笔交易价格
            if close_price is None:
                fallback_result = await db.execute(
                    select(SandboxTrade.price)
                    .where(
                        SandboxTrade.ts_code == code,
                        SandboxTrade.trade_date <= calc_date,
                    )
                    .order_by(desc(SandboxTrade.trade_date), desc(SandboxTrade.id))
                    .limit(1)
                )
                fallback_price = fallback_result.scalar()
                if fallback_price:
                    close_price = float(fallback_price)
                    price_source = "trade_fallback"
                    logger.info("NAV: %s no quote data, using trade price %.4f", code, close_price)

        if close_price:
            mv = Decimal(str(close_price)) * shares
            total_market_value += mv
            holdings_detail.append(
                f"{code}: price={close_price}({price_source}) × {shares}shares = ¥{float(mv):.2f}"
            )

    # 输出每只持仓的价格明细
    if holdings_detail:
        logger.info("NAV holdings detail:\n  %s", "\n  ".join(holdings_detail))

    # 如果手动传入了市值，直接覆盖计算结果
    if market_value_override is not None:
        total_market_value = Decimal(str(market_value_override))
        logger.info("NAV: 使用手动输入市值 ¥%.2f（覆盖计算值）", market_value_override)

    total_assets = total_market_value + cash
    nav_value = float(total_assets / INITIAL_CAPITAL) if INITIAL_CAPITAL > 0 else 1.0
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
        "NAV computed for %s: nav=%.4f, pnl=%.2f%%, mv=%.2f, cash=%.2f%s",
        calc_date, nav_value, total_pnl, total_market_value, cash,
        " (manual cash)" if cash_balance is not None else "",
    )
    return {
        "date": str(calc_date),
        "nav": round(nav_value, 4),
        "total_pnl": total_pnl,
        "market_value": float(total_market_value),
        "cash": float(cash),
        "total_assets": round(float(total_market_value + cash), 2),
        "holdings_detail": holdings_detail,
    }


@router.post("/nav/compute")
async def compute_nav(
    target_date: date | None = None,
    cash_balance: float | None = None,
    market_value: float | None = None,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """计算指定日期（默认今天）的净值。

    Args:
        target_date: 计算日期（默认今天）
        cash_balance: 可选，实际现金余额（券商账户中的可用资金，
                      传入后将覆盖从交易推算的值，用于补偿手续费等差异）
        market_value: 可选，手动输入的持仓市值（当行情获取失败时使用）

    逻辑：
    1. 汇总所有交易记录，计算各股票净持仓
    2. 获取实时不复权行情计算持仓市值
    3. 当天总资产 = 现金 + 持仓市值
    4. NAV = 当天总资产 / 初始总资产 (104,152.59)
    """
    calc_date = target_date or date.today()

    # 先更新 ETF 行情，确保计算使用最新数据
    try:
        from app.services.data_fetcher import fetch_sandbox_etf_quotes
        etf_count = await fetch_sandbox_etf_quotes()
        if etf_count > 0:
            logger.info("NAV compute: ETF 行情已更新 %d 条", etf_count)
    except Exception as etf_err:
        logger.warning("NAV compute: ETF 行情更新失败（不影响计算）: %s", etf_err)

    result = await _compute_nav_core(db, calc_date, cash_balance=cash_balance, market_value_override=market_value)
    if result is None:
        return {
            "date": str(calc_date),
            "nav": 1.0,
            "market_value": 0.0,
            "cash": float(INITIAL_CAPITAL),
            "total_assets": float(INITIAL_CAPITAL),
            "message": "No trades yet",
        }
    return result


@router.get("/nav/debug-prices")
async def debug_prices(
    db: AsyncSession = Depends(get_db),
):
    """调试端点：展示每只持仓股票通过各种来源获取的价格，不写入数据库。"""
    from app.models.stock import StockDailyQuote
    from app.services.data_fetcher import get_unadjusted_close, get_realtime_prices, get_sina_prices

    # 汇总持仓
    trades_result = await db.execute(select(SandboxTrade))
    all_trades = trades_result.scalars().all()
    positions: dict[str, int] = {}
    for t in all_trades:
        code = t.ts_code
        if t.action == "buy":
            positions[code] = positions.get(code, 0) + t.shares
        else:
            positions[code] = positions.get(code, 0) - t.shares

    holding_codes = [code for code, shares in positions.items() if shares > 0]

    # 0) 新浪财经 HTTP 接口（不依赖 akshare）
    sina = {}
    try:
        sina = await get_sina_prices(holding_codes)
    except Exception as e:
        sina = {"error": str(e)}

    # 1) 逐只不复权收盘价 (akshare)
    unadj = {}
    try:
        unadj = await get_unadjusted_close(holding_codes)
    except Exception as e:
        unadj = {"error": str(e)}

    # 2) 全市场实时行情 (akshare)
    spot = {}
    try:
        spot = await get_realtime_prices(holding_codes)
    except Exception as e:
        spot = {"error": str(e)}

    # 3) 行情表前复权价
    db_qfq = {}
    for code in holding_codes:
        r = await db.execute(
            select(StockDailyQuote.close, StockDailyQuote.trade_date)
            .where(StockDailyQuote.ts_code == code)
            .order_by(desc(StockDailyQuote.trade_date))
            .limit(1)
        )
        row = r.first()
        if row:
            db_qfq[code] = {"price": float(row[0]), "date": str(row[1])}

    # 汇总
    result = []
    for code in holding_codes:
        shares = positions[code]
        entry = {
            "code": code,
            "shares": shares,
            "sina_price": sina.get(code) if isinstance(sina, dict) else None,
            "unadjusted_close": unadj.get(code) if isinstance(unadj, dict) else None,
            "spot_realtime": spot.get(code) if isinstance(spot, dict) else None,
            "db_qfq": db_qfq.get(code),
        }
        if isinstance(sina, dict) and sina.get(code):
            entry["mv_sina"] = round(sina[code] * shares, 2)
        if isinstance(unadj, dict) and unadj.get(code):
            entry["mv_unadjusted"] = round(unadj[code] * shares, 2)
        if isinstance(spot, dict) and spot.get(code):
            entry["mv_spot"] = round(spot[code] * shares, 2)
        if db_qfq.get(code) and isinstance(db_qfq[code], dict):
            entry["mv_db_qfq"] = round(db_qfq[code]["price"] * shares, 2)
        result.append(entry)

    total_mv_sina = sum(e.get("mv_sina", 0) for e in result)
    total_mv_unadj = sum(e.get("mv_unadjusted", 0) for e in result)
    total_mv_spot = sum(e.get("mv_spot", 0) for e in result)
    total_mv_qfq = sum(e.get("mv_db_qfq", 0) for e in result)

    return {
        "holdings": result,
        "total_mv_sina": round(total_mv_sina, 2),
        "total_mv_unadjusted": round(total_mv_unadj, 2),
        "total_mv_spot": round(total_mv_spot, 2),
        "total_mv_db_qfq": round(total_mv_qfq, 2),
    }

