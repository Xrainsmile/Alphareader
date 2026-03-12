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
import csv
import io
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dashboard import _verify_token
from app.database import get_db
from app.models.sandbox import SandboxAnalysis, SandboxNav, SandboxStock, SandboxTrade
from app.services.sandbox_nav import INITIAL_CAPITAL, compute_nav_core
from app.services.sandbox_stock import get_sandbox_stock_list

logger = logging.getLogger("alphareader.sandbox")

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


# ════════════════════════════════════════════════════════════
# Pydantic Schemas
# ════════════════════════════════════════════════════════════

class StockCreate(BaseModel):
    ts_code: str = Field(..., max_length=10)
    name: str = Field("", max_length=32)
    reason: str | None = None
    strategy: str = Field("swing", pattern=r"^(swing|value)$")

class AnalysisCreate(BaseModel):
    stock_id: int
    ts_code: str = Field(..., max_length=10)
    score: float = Field(..., ge=0, le=5)
    trend: str = Field(..., max_length=500)
    pattern: str = Field(..., max_length=500)
    volume_price: str = Field(..., max_length=500)
    plan: str = Field(..., max_length=500)
    pnl_thinking: str = Field(..., max_length=500)
    verdict: str = Field(..., max_length=500)

class TradeCreate(BaseModel):
    stock_id: int
    ts_code: str = Field(..., max_length=10)
    action: str = Field(..., pattern=r"^(buy|sell)$")
    price: float = Field(..., gt=0)
    shares: int = Field(..., gt=0)
    trade_date: date
    note: str | None = None


# ════════════════════════════════════════════════════════════
# Sandbox 访问密码验证
# ════════════════════════════════════════════════════════════

class SandboxAuthRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)

@router.post("/verify-access")
async def verify_sandbox_access(body: SandboxAuthRequest):
    """验证模拟仓访问密码。使用恒定时间比较防止时序攻击。"""
    import hmac
    expected = settings.SANDBOX_PASSWORD
    if not expected:
        # 未配置密码 → 直接放行
        return {"ok": True}
    if hmac.compare_digest(body.password.encode(), expected.encode()):
        return {"ok": True}
    raise HTTPException(status_code=403, detail="密码错误")


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

    # 观察池总数（不含退出）
    total_active = counts.holding + counts.watching

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
    discipline: str | None = Query(None, pattern=r"^(retain|gray|research|churn)$", deprecated=True),
    q: str | None = Query(None, max_length=20, description="搜索：代码或名称"),
    holding_only: bool = Query(False, description="仅显示持仓票"),
    db: AsyncSession = Depends(get_db),
):
    """观察池列表，附最新一条推演摘要。支持搜索、仅持仓。
    默认排除已退出(exited)的股票，除非显式传入 status=exited。"""
    _ = discipline  # 兼容旧参数，避免破坏前端历史调用
    return await get_sandbox_stock_list(
        db,
        status=status,
        q=q,
        holding_only=holding_only,
    )


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
                "plan": a.plan,
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
        strategy=body.strategy,
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
        plan=body.plan,
        pnl_thinking=body.pnl_thinking,
        verdict=body.verdict,
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    logger.info("Added analysis #%d for %s", analysis.id, body.ts_code)
    return {"id": analysis.id}


# ── CSV 模板下载 & 批量导入推演 ──

_CSV_TEMPLATE_HEADER = [
    "ts_code", "score", "trend", "pattern", "volume_price",
    "plan", "pnl_thinking", "verdict",
]
_CSV_TEMPLATE_EXAMPLE = [
    "600519", "3.5", "均线多头排列，MA20向上", "杯柄形态突破",
    "放量突破前高，量价配合良好",
    "突破1900加仓，跌破1800止损，目标2200",
    "盈亏比合理，风控明确", "趋势向好，可持有观察",
]


@router.get("/admin/analyses/csv-template")
async def download_csv_template(
    _: None = Depends(_require_admin),
):
    """下载推演批量录入 CSV 模板。"""
    buf = io.StringIO()
    # 写入 BOM 使 Excel 正确识别 UTF-8
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(_CSV_TEMPLATE_HEADER)
    writer.writerow(_CSV_TEMPLATE_EXAMPLE)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=analysis_template.csv"},
    )


@router.post("/admin/analyses/batch")
async def admin_batch_import_analyses(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """通过 CSV 文件批量导入推演记录。

    CSV 列: ts_code, score, trend, pattern, volume_price,
            plan, pnl_thinking, verdict

    系统自动根据 ts_code 匹配观察池中的 stock_id。
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 .csv 文件")

    content = await file.read()
    # 尝试 UTF-8 BOM / UTF-8 / GBK 解码
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
        try:
            text = content.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise HTTPException(status_code=400, detail="文件编码无法识别，请使用 UTF-8 编码保存")

    reader = csv.DictReader(io.StringIO(text))
    # 验证表头
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV 文件为空或格式错误")

    # 标准化表头（去空格）
    reader.fieldnames = [f.strip() for f in reader.fieldnames]
    missing = set(_CSV_TEMPLATE_HEADER[:5]) - set(reader.fieldnames)  # 前5个必填列
    if missing:
        raise HTTPException(status_code=400, detail=f"CSV 缺少必要列: {', '.join(missing)}")

    # 预加载观察池 ts_code -> stock_id 映射
    result = await db.execute(
        select(SandboxStock.id, SandboxStock.ts_code, SandboxStock.name)
        .where(SandboxStock.status != "exited")
    )
    stock_map = {row.ts_code: row.id for row in result.all()}

    imported = 0
    errors: list[dict] = []

    for row_num, row in enumerate(reader, start=2):  # 从第2行开始（第1行是表头）
        ts_code = (row.get("ts_code") or "").strip()
        if not ts_code:
            errors.append({"row": row_num, "error": "ts_code 为空"})
            continue

        stock_id = stock_map.get(ts_code)
        if stock_id is None:
            errors.append({"row": row_num, "ts_code": ts_code, "error": "不在观察池中"})
            continue

        # 解析字段
        try:
            score = float((row.get("score") or "0").strip())
            if score < 0 or score > 5:
                raise ValueError("评分须在 0-5 之间")
        except ValueError as e:
            errors.append({"row": row_num, "ts_code": ts_code, "error": f"score 无效: {e}"})
            continue

        trend = (row.get("trend") or "").strip()
        pattern = (row.get("pattern") or "").strip()
        volume_price = (row.get("volume_price") or "").strip()
        pnl_thinking = (row.get("pnl_thinking") or "").strip()
        verdict = (row.get("verdict") or "").strip()

        plan = (row.get("plan") or "").strip()

        if not all([trend, pattern, volume_price, pnl_thinking, verdict]):
            errors.append({"row": row_num, "ts_code": ts_code, "error": "trend/pattern/volume_price/pnl_thinking/verdict 不能为空"})
            continue

        analysis = SandboxAnalysis(
            stock_id=stock_id,
            ts_code=ts_code,
            score=round(score, 1),
            trend=trend[:500],
            pattern=pattern[:500],
            volume_price=volume_price[:500],
            plan=plan[:500] if plan else None,
            pnl_thinking=pnl_thinking[:500],
            verdict=verdict[:500],
        )
        db.add(analysis)
        imported += 1

    if imported > 0:
        await db.commit()

    logger.info("Batch import analyses: %d imported, %d errors", imported, len(errors))
    return {
        "imported": imported,
        "errors": errors,
        "total_rows": imported + len(errors),
    }


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
                "plan": a.plan,
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

@router.post("/nav/compute")
async def compute_nav(
    target_date: date | None = None,
    cash_balance: float | None = None,
    market_value: float | None = None,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """计算指定日期（默认今天）的净值。"""
    from app.services.data_fetcher import fetch_sandbox_etf_quotes

    calc_date = target_date or date.today()

    try:
        etf_count = await fetch_sandbox_etf_quotes()
        if etf_count > 0:
            logger.info("NAV compute: ETF 行情已更新 %d 条", etf_count)
    except Exception as etf_err:
        logger.warning("NAV compute: ETF 行情更新失败（不影响计算）: %s", etf_err)

    result = await compute_nav_core(
        db,
        calc_date,
        cash_balance=cash_balance,
        market_value_override=market_value,
    )
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

