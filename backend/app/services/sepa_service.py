"""SEPA 模拟盘训练系统 — 核心业务逻辑。

包含（均为可单测的纯逻辑 + 少量需要 DB 的聚合函数）：
  1. 8 条趋势模板判定（Minervini Trend Template）
  2. 止损位 / 最大风险计算 + 1.5% 硬拦截
  3. 买点检查清单校验
  4. KPI 计算（纪律达标率 / 盈亏比 / 胜率 / 样本量 / 总收益 + 实验评估结论）
  5. 账户状态（现金 / 市值 / 盈亏 / 熔断）

三市场独立账户、独立币种、独立 KPI。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sepa import (
    SEPA_CURRENCY,
    SEPA_DEFAULT_CAPITAL,
    SEPA_MARKETS,
    SepaAccount,
    SepaTrade,
    SepaWatchlistItem,
)

logger = logging.getLogger("alphareader.sepa")

# ════════════════════════════════════════════════════════════
# 规则常量（手册第五、六、十章）
# ════════════════════════════════════════════════════════════
RISK_LIMIT_PCT = 1.5          # 单笔最大亏损占总仓上限（%）→ 超过硬拦截
DEFAULT_STOP_PCT = 7.0        # 默认硬止损幅度（%）
CIRCUIT_BREAKER_PCT = 15.0    # 账户熔断线（亏损达 -15% 强制停手）
NEAR_PIVOT_PCT = 5.0          # 距枢轴 ≤5% 才算买点，否则追高
LOW52W_MIN_PCT = 25.0         # 现价距 52 周低点 ≥25%
HIGH52W_MAX_PCT = 25.0        # 现价距 52 周高点 ≤25%
RS_MIN = 70                   # RS 相对强度门槛

# KPI 目标值（手册第十章）
DISCIPLINE_TARGET = 100.0     # 纪律达标率目标 100%
PROFIT_LOSS_TARGET = 2.0      # 盈亏比目标 ≥2
WIN_RATE_REF = 35.0           # 胜率参考 ≥35%
SAMPLE_TARGET = 15            # 样本量目标 ≥15


def _now_cst() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


# ════════════════════════════════════════════════════════════
# 1. 8 条趋势模板判定
# ════════════════════════════════════════════════════════════

def evaluate_trend_template(
    *,
    price: float | None,
    ma50: float | None,
    ma150: float | None,
    ma200: float | None,
    ma200_rising: bool,
    high52w: float | None,
    low52w: float | None,
    rs: float | None,
) -> tuple[bool, list[dict]]:
    """逐条判定 8 条 Minervini 趋势模板。

    返回 (是否全部通过, 逐条结果列表)。
    任一数据缺失则该条判为未通过（pass=False, note 提示缺数据）。
    """
    def _has(*vals) -> bool:
        return all(v is not None for v in vals)

    details: list[dict] = []

    # 1. 现价 > 150日均线 且 > 200日均线
    if _has(price, ma150, ma200):
        ok = price > ma150 and price > ma200
    else:
        ok = False
    details.append({"no": 1, "desc": "现价 > MA150 且 > MA200", "pass": ok})

    # 2. 150日均线 > 200日均线
    ok = _has(ma150, ma200) and ma150 > ma200
    details.append({"no": 2, "desc": "MA150 > MA200", "pass": ok})

    # 3. 200日均线连续上升 ≥ 1个月
    details.append({"no": 3, "desc": "MA200 连续上升 ≥ 1个月", "pass": bool(ma200_rising)})

    # 4. 50日均线 > 150日均线 且 > 200日均线
    ok = _has(ma50, ma150, ma200) and ma50 > ma150 and ma50 > ma200
    details.append({"no": 4, "desc": "MA50 > MA150 且 > MA200", "pass": ok})

    # 5. 现价 > 50日均线
    ok = _has(price, ma50) and price > ma50
    details.append({"no": 5, "desc": "现价 > MA50", "pass": ok})

    # 6. 现价距52周低点 ≥ 25%
    if _has(price, low52w) and low52w > 0:
        ok = (price - low52w) / low52w >= LOW52W_MIN_PCT / 100
    else:
        ok = False
    details.append({"no": 6, "desc": f"现价距52周低点 ≥ {LOW52W_MIN_PCT:.0f}%", "pass": ok})

    # 7. 现价距52周高点 ≤ 25%
    if _has(price, high52w) and high52w > 0:
        ok = (high52w - price) / high52w <= HIGH52W_MAX_PCT / 100
    else:
        ok = False
    details.append({"no": 7, "desc": f"现价距52周高点 ≤ {HIGH52W_MAX_PCT:.0f}%", "pass": ok})

    # 8. RS ≥ 70
    ok = rs is not None and rs >= RS_MIN
    details.append({"no": 8, "desc": f"RS ≥ {RS_MIN}", "pass": ok})

    all_pass = all(d["pass"] for d in details)
    return all_pass, details


# ════════════════════════════════════════════════════════════
# 2. 止损位 / 最大风险计算 + 1.5% 拦截
# ════════════════════════════════════════════════════════════

def compute_risk(
    *,
    entry_price: float,
    shares: int,
    account_total: float,
    stop_price: float | None = None,
) -> dict:
    """计算止损幅度、最大亏损、占总仓比例，并判定是否超限。

    若未提供 stop_price，按默认 -7% 计算建议止损价。
    """
    if entry_price <= 0 or shares <= 0:
        raise ValueError("entry_price 和 shares 必须为正数")

    # 默认止损价（-7%）
    if stop_price is None or stop_price <= 0:
        stop_price = round(entry_price * (1 - DEFAULT_STOP_PCT / 100), 4)

    position_amount = entry_price * shares
    stop_pct = (stop_price - entry_price) / entry_price * 100  # 负数
    max_loss = max((entry_price - stop_price) * shares, 0.0)
    max_loss_pct = (max_loss / account_total * 100) if account_total > 0 else 0.0
    position_pct = (position_amount / account_total * 100) if account_total > 0 else 0.0

    return {
        "stop_price": round(stop_price, 4),
        "stop_pct": round(stop_pct, 2),
        "position_amount": round(position_amount, 2),
        "position_pct": round(position_pct, 2),
        "max_loss": round(max_loss, 2),
        "max_loss_pct": round(max_loss_pct, 2),
        "risk_limit_pct": RISK_LIMIT_PCT,
        # 硬拦截：止损价必须低于买入价（做多）+ 最大亏损不得超 1.5%
        "stop_valid": stop_price < entry_price,
        "exceeds_risk_limit": max_loss_pct > RISK_LIMIT_PCT,
    }


def near_pivot(entry_price: float, pivot_price: float | None) -> dict:
    """距枢轴距离判定。返回 {distance_pct, within_5pct}。"""
    if not pivot_price or pivot_price <= 0:
        return {"distance_pct": None, "within_5pct": None}
    dist = (entry_price - pivot_price) / pivot_price * 100
    return {
        "distance_pct": round(dist, 2),
        "within_5pct": dist <= NEAR_PIVOT_PCT,
    }


# ════════════════════════════════════════════════════════════
# 3. 买点检查清单（M3 / M7）
# ════════════════════════════════════════════════════════════

def build_checklist(
    *,
    gate_open: bool,
    template_pass: bool,
    vcp_confirmed: bool,
    within_pivot: bool | None,
    stop_price_set: bool,
) -> dict:
    """构建买入前 5 项检查清单，返回逐项结果与是否可下单。"""
    items = [
        {"key": "gate_open", "label": "市场闸门开启", "pass": bool(gate_open)},
        {"key": "template_pass", "label": "8条趋势模板通过", "pass": bool(template_pass)},
        {"key": "vcp_confirmed", "label": "VCP 形态确认", "pass": bool(vcp_confirmed)},
        {"key": "near_pivot", "label": "当前价距枢轴 ≤5%", "pass": bool(within_pivot)},
        {"key": "stop_set", "label": "已设定止损价", "pass": bool(stop_price_set)},
    ]
    # near_pivot 允许强制确认放行（追高），其余为硬性
    hard_keys = {"gate_open", "template_pass", "vcp_confirmed", "stop_set"}
    hard_pass = all(it["pass"] for it in items if it["key"] in hard_keys)
    return {
        "items": items,
        "all_pass": all(it["pass"] for it in items),
        "hard_pass": hard_pass,  # 硬性项是否全过（near_pivot 不计入，可追高放行）
    }


# ════════════════════════════════════════════════════════════
# 4. 账户状态（现金 / 市值 / 盈亏 / 熔断）
# ════════════════════════════════════════════════════════════

async def get_or_create_account(db: AsyncSession, market: str) -> SepaAccount:
    """获取指定市场账户，不存在则用默认资金创建。"""
    if market not in SEPA_MARKETS:
        raise ValueError(f"非法市场: {market}")
    result = await db.execute(select(SepaAccount).where(SepaAccount.market == market))
    acc = result.scalar_one_or_none()
    if acc is None:
        acc = SepaAccount(
            market=market,
            currency=SEPA_CURRENCY[market],
            initial_capital=SEPA_DEFAULT_CAPITAL[market],
            inception_date=_now_cst().date(),
        )
        db.add(acc)
        await db.commit()
        await db.refresh(acc)
    return acc


async def compute_account_state(db: AsyncSession, market: str) -> dict:
    """计算账户现金、持仓市值、累计盈亏、熔断状态。

    现金流模型：
      买入 → cash -= amount；平仓 → cash += exit_price*shares
      cash = initial - Σ(open.amount) + Σ(closed.pnl_amount)
    持仓市值 = Σ(open.shares × current_price)；现价取自同 market+symbol 的 watchlist。
    """
    acc = await get_or_create_account(db, market)
    initial = float(acc.initial_capital)

    # 全部交易
    trades_res = await db.execute(
        select(SepaTrade).where(SepaTrade.market == market)
    )
    trades = trades_res.scalars().all()

    # watchlist 现价表
    wl_res = await db.execute(
        select(SepaWatchlistItem.symbol, SepaWatchlistItem.price).where(
            SepaWatchlistItem.market == market
        )
    )
    price_map = {sym: px for sym, px in wl_res.all() if px is not None}

    open_amount = 0.0
    realized_pnl = 0.0
    market_value = 0.0
    holdings: list[dict] = []

    for t in trades:
        if t.status == "open":
            amt = float(t.amount)
            open_amount += amt
            cur_px = price_map.get(t.symbol) or float(t.entry_price)
            mv = cur_px * t.shares
            market_value += mv
            float_pnl = mv - amt
            holdings.append({
                "id": t.id,
                "symbol": t.symbol,
                "name": t.name,
                "shares": t.shares,
                "entry_price": float(t.entry_price),
                "stop_price": float(t.stop_price),
                "current_price": round(cur_px, 4),
                "market_value": round(mv, 2),
                "float_pnl": round(float_pnl, 2),
                "float_pnl_pct": round((cur_px / float(t.entry_price) - 1) * 100, 2),
                "dist_to_stop_pct": round(
                    (cur_px - float(t.stop_price)) / cur_px * 100, 2
                ) if cur_px > 0 else None,
                "stop_triggered": cur_px <= float(t.stop_price),
                "entry_date": t.entry_date.isoformat(),
            })
        elif t.status == "closed" and t.pnl_amount is not None:
            realized_pnl += float(t.pnl_amount)

    cash = initial - open_amount + realized_pnl
    total_equity = cash + market_value
    total_pnl_pct = (total_equity - initial) / initial * 100 if initial > 0 else 0.0
    circuit_breaker_hit = total_pnl_pct <= -CIRCUIT_BREAKER_PCT
    dist_to_breaker = total_pnl_pct + CIRCUIT_BREAKER_PCT  # 距 -15% 还有多少个百分点

    return {
        "market": market,
        "currency": acc.currency,
        "initial_capital": round(initial, 2),
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total_equity": round(total_equity, 2),
        "realized_pnl": round(realized_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "circuit_breaker_pct": -CIRCUIT_BREAKER_PCT,
        "circuit_breaker_hit": circuit_breaker_hit,
        "dist_to_breaker_pct": round(dist_to_breaker, 2),
        "holdings": holdings,
        "inception_date": acc.inception_date.isoformat(),
    }


# ════════════════════════════════════════════════════════════
# 5. KPI 计算（手册第十章）
# ════════════════════════════════════════════════════════════

async def compute_kpi(db: AsyncSession, market: str, period: str = "all") -> dict:
    """计算纪律达标率 / 盈亏比 / 胜率 / 样本量 / 总收益 + 实验评估结论。

    period: "all"（全程）或 "week"（本周，按 exit_date）。
    """
    stmt = select(SepaTrade).where(
        SepaTrade.market == market, SepaTrade.status == "closed"
    )
    res = await db.execute(stmt)
    closed = list(res.scalars().all())

    if period == "week":
        monday = _now_cst().date()
        monday = date.fromordinal(monday.toordinal() - monday.weekday())
        closed = [t for t in closed if t.exit_date and t.exit_date >= monday]

    sample_size = len(closed)

    # 纪律达标率 = followed_rule=True 笔数 / 已标注笔数
    labeled = [t for t in closed if t.followed_rule is not None]
    followed = [t for t in labeled if t.followed_rule]
    discipline_rate = (len(followed) / len(labeled) * 100) if labeled else None

    # 盈亏比 = 平均盈利% / 平均亏损%（绝对值）
    wins = [t.pnl_pct for t in closed if t.pnl_pct is not None and t.pnl_pct > 0]
    losses = [abs(t.pnl_pct) for t in closed if t.pnl_pct is not None and t.pnl_pct < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    profit_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else None

    # 胜率 = 盈利笔数 / 总笔数
    win_rate = (len(wins) / sample_size * 100) if sample_size else None

    # 总收益（账户层）
    acc_state = await compute_account_state(db, market)
    total_return = acc_state["total_pnl_pct"]

    # 实验评估结论：纪律100% + 盈亏比≥2 + 样本≥15
    passed = (
        discipline_rate is not None and discipline_rate >= DISCIPLINE_TARGET
        and profit_loss_ratio is not None and profit_loss_ratio >= PROFIT_LOSS_TARGET
        and sample_size >= SAMPLE_TARGET
    )
    if passed:
        verdict = "✅ 通过，可加码至更大资金"
    else:
        verdict = "继续训练"

    return {
        "market": market,
        "period": period,
        "discipline_rate": round(discipline_rate, 1) if discipline_rate is not None else None,
        "discipline_target": DISCIPLINE_TARGET,
        "profit_loss_ratio": round(profit_loss_ratio, 2) if profit_loss_ratio is not None else None,
        "profit_loss_target": PROFIT_LOSS_TARGET,
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "win_rate_ref": WIN_RATE_REF,
        "sample_size": sample_size,
        "sample_target": SAMPLE_TARGET,
        "total_return": total_return,
        "passed": passed,
        "verdict": verdict,
    }
