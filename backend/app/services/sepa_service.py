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

import asyncio
import logging
import re
import urllib.request
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, text as sa_text
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
# 1b. 自动获取指标（填代码 → 拉现价/MA/RS/52周高低）
# ════════════════════════════════════════════════════════════

async def fetch_sepa_indicators(
    market: str, symbol: str, db: AsyncSession
) -> dict:
    """根据市场和代码自动获取 SEPA 趋势模板所需指标。

    CN: stock_daily_quote 算 MA/52周高低, stock_rs_rating 取 RS, 新浪取实时价
    US: stock_daily_quote 算 MA/52周高低, stock_rs_rating 取 RS, 最新收盘价
    HK: 新浪港股接口取实时价和名称，其余留空
    """
    result: dict = {
        "name": None, "price": None, "ma50": None, "ma150": None, "ma200": None,
        "ma200_rising": None, "high52w": None, "low52w": None, "rs": None,
    }

    ts_code = symbol.strip()
    if not ts_code:
        return result

    # ── 港股：仅尝试新浪港股接口 ──
    if market == "HK":
        try:
            hk_data = await _fetch_hk_sina_price(ts_code)
            if hk_data:
                result["name"] = hk_data.get("name")
                result["price"] = hk_data.get("price")
                if hk_data.get("high52w"):
                    result["high52w"] = hk_data["high52w"]
                if hk_data.get("low52w"):
                    result["low52w"] = hk_data["low52w"]
        except Exception as e:
            logger.warning("港股 %s 行情获取失败: %s", ts_code, e)
        return result

    # ── CN / US：从 stock_daily_quote 计算 MA + 52 周高低 ──
    qmarket = "CN" if market == "CN" else "US"

    sql = sa_text("""
        WITH ranked AS (
            SELECT close, high, low, name, trade_date,
                   ROW_NUMBER() OVER (ORDER BY trade_date DESC) as rn
            FROM stock_daily_quote
            WHERE ts_code = :ts_code AND market = :market
        )
        SELECT
            AVG(CASE WHEN rn <= 50  THEN close END)  AS ma50,
            AVG(CASE WHEN rn <= 150 THEN close END)  AS ma150,
            AVG(CASE WHEN rn <= 200 THEN close END)  AS ma200,
            AVG(CASE WHEN rn BETWEEN 22 AND 222 THEN close END) AS ma200_prev,
            MAX(CASE WHEN  rn <= 250 THEN high END)  AS high52w,
            MIN(CASE WHEN  rn <= 250 THEN low END)   AS low52w,
            MAX(CASE WHEN  rn = 1    THEN close END)  AS latest_close,
            MAX(CASE WHEN  rn = 1    THEN name END)   AS name,
            COUNT(*)                                    AS data_count
        FROM ranked
        WHERE rn <= 260
    """)

    res = await db.execute(sql, {"ts_code": ts_code, "market": qmarket})
    row = res.first()

    if row and row.data_count and row.data_count >= 50:
        result["name"] = row.name or None
        result["ma50"] = round(float(row.ma50), 2) if row.ma50 else None
        result["high52w"] = round(float(row.high52w), 2) if row.high52w else None
        result["low52w"] = round(float(row.low52w), 2) if row.low52w else None
        result["price"] = round(float(row.latest_close), 2) if row.latest_close else None

        if row.data_count >= 150:
            result["ma150"] = round(float(row.ma150), 2) if row.ma150 else None
        if row.data_count >= 200:
            result["ma200"] = round(float(row.ma200), 2) if row.ma200 else None
            # MA200 连升 ≥1月：当前 MA200 > 22 交易日前 MA200
            if row.ma200 and row.ma200_prev:
                result["ma200_rising"] = float(row.ma200) > float(row.ma200_prev)

    # ── RS 评级 ──
    try:
        rs_sql = sa_text("""
            SELECT rs_rating, name FROM stock_rs_rating
            WHERE (ts_code = :ts_code OR ts_code LIKE :ts_code_suffix)
              AND market = :market
            ORDER BY trade_date DESC LIMIT 1
        """)
        rs_res = await db.execute(rs_sql, {
            "ts_code": ts_code,
            "ts_code_suffix": f"{ts_code}.%",
            "market": qmarket,
        })
        rs_row = rs_res.first()
        if rs_row:
            result["rs"] = int(rs_row.rs_rating)
            if not result["name"] and rs_row.name:
                result["name"] = rs_row.name
    except Exception as e:
        logger.warning("RS 评级查询失败 %s: %s", ts_code, e)

    # ── CN：新浪实时价覆盖（盘中更准） ──
    if market == "CN":
        try:
            from app.services.data_fetcher import get_sina_prices
            sina_prices = await get_sina_prices([ts_code])
            if ts_code in sina_prices and sina_prices[ts_code] > 0:
                result["price"] = round(sina_prices[ts_code], 2)
        except Exception as e:
            logger.warning("新浪实时价获取失败 %s: %s", ts_code, e)

    return result


async def _fetch_hk_sina_price(code: str) -> dict | None:
    """通过新浪港股接口获取实时价格和名称。"""
    hk_code = code.zfill(5)
    sina_code = f"rt_hk{hk_code}"
    url = f"https://hq.sinajs.cn/list={sina_code}"

    req = urllib.request.Request(url, headers={
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0",
    })

    def _fetch() -> str:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("gbk", errors="replace")

    try:
        text = await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.warning("新浪港股行情请求失败: %s", e)
        return None

    for line in text.strip().split("\n"):
        line = line.strip()
        if '="' not in line:
            continue
        m = re.match(r'var hq_str_rt_hk\d+="(.+)"', line)
        if not m:
            continue
        fields = m.group(1).split(",")
        # 新浪港股 rt_ 格式: [0]中文名 [1]开盘 [2]昨收 [3]最高 [4]最低 [5]现价 [6]成交量 ...
        result: dict = {}
        try:
            if len(fields) >= 1 and fields[0]:
                result["name"] = fields[0]
            if len(fields) >= 6 and fields[5]:
                price = float(fields[5])
                if price > 0:
                    result["price"] = price
            if len(fields) >= 4 and fields[3]:
                result["high52w"] = float(fields[3])
            if len(fields) >= 5 and fields[4]:
                result["low52w"] = float(fields[4])
        except (ValueError, IndexError):
            pass
        return result or None

    return None


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
