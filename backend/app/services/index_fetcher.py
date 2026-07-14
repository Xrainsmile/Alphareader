"""基准指数日行情采集 — 写入 index_daily 表。

A 股：akshare index_zh_a_hist（沪深300=000300 / 中证1000=000852）
美股：yfinance（^GSPC 标普500 / ^IXIC 纳斯达克），失败则跳过（适配度服务自动改用合成代理）

幂等：重复运行按 (index_code, trade_date) upsert。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.market import IndexDaily

logger = logging.getLogger("alphareader.index_fetcher")

# A 股指数：akshare 代码 → (名称, 市场)
CN_INDICES = {
    "000300": ("沪深300", "CN"),
    "000852": ("中证1000", "CN"),
}
# 美股指数：yfinance 代码 → (名称, 市场)
US_INDICES = {
    "^GSPC": ("标普500", "US"),
    "^IXIC": ("纳斯达克", "US"),
}

# 回溯天数（约 400 自然日 ≈ 270 交易日，满足波动率分位 250 日需求）
LOOKBACK_DAYS = 420


def _last_trade_date(index_code: str) -> date | None:
    """同步查询该指数最近一条数据日期（用于增量）。"""
    from app.database import engine
    import asyncio

    async def _q():
        async with async_session() as s:
            r = await s.execute(
                select(IndexDaily.trade_date)
                .where(IndexDaily.index_code == index_code)
                .order_by(IndexDaily.trade_date.desc())
                .limit(1)
            )
            return r.scalar_one_or_none()

    try:
        return asyncio.get_event_loop().run_until_complete(_q())
    except RuntimeError:
        return None


async def _upsert(rows: list[dict]) -> int:
    if not rows:
        return 0
    async with async_session() as session:
        stmt = pg_insert(IndexDaily).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_index_daily",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "amount": stmt.excluded.amount,
                "source": stmt.excluded.source,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return len(rows)


def _fetch_cn_akshare(code: str, name: str, market: str, start: date, end: date) -> list[dict]:
    """akshare 采集 A 股指数。失败时返回 []。"""
    try:
        import akshare as ak
    except Exception as e:
        logger.warning("akshare 不可用，跳过 A 股指数 %s: %s", code, e)
        return []
    try:
        df = ak.index_zh_a_hist(
            symbol=code, period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            d = _parse_date(r.get("日期"))
            if d is None:
                continue
            out.append({
                "index_code": code, "index_name": name, "market": market,
                "trade_date": d,
                "open": _f(r.get("开盘")), "high": _f(r.get("最高")),
                "low": _f(r.get("最低")), "close": _f(r.get("收盘")),
                "volume": _f(r.get("成交量")), "amount": _f(r.get("成交额")),
                "source": "akshare",
            })
        return out
    except Exception as e:
        logger.warning("akshare 采集指数 %s 失败: %s", code, e)
        return []


def _fetch_us_yfinance(code: str, name: str, market: str, start: date, end: date) -> list[dict]:
    """yfinance 采集美股指数。失败时返回 []（适配度服务将使用合成代理）。"""
    try:
        import yfinance as yf
    except Exception as e:
        logger.warning("yfinance 不可用，跳过美股指数 %s: %s", code, e)
        return []
    try:
        tk = yf.Ticker(code)
        hist = tk.history(start=start, end=end + timedelta(days=1), interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            return []
        out = []
        for idx, r in hist.iterrows():
            d = idx.date()
            out.append({
                "index_code": code, "index_name": name, "market": market,
                "trade_date": d,
                "open": _f(r.get("Open")), "high": _f(r.get("High")),
                "low": _f(r.get("Low")), "close": _f(r.get("Close")),
                "volume": _f(r.get("Volume")), "amount": None,
                "source": "yfinance",
            })
        return out
    except Exception as e:
        logger.warning("yfinance 采集指数 %s 失败（将使用合成代理）: %s", code, e)
        return []


def _parse_date(v) -> date | None:
    try:
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _f(v):
    try:
        if v is None:
            return None
        fv = float(v)
        return fv if fv == fv else None  # NaN → None
    except Exception:
        return None


async def fetch_indices(market: str | None = None) -> dict:
    """采集指数日行情并写入 index_daily。

    market: 'CN' / 'US' / None(全部)。返回 {market: {fetched, stored}}。
    """
    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    summary: dict[str, dict] = {}

    targets = []
    if market in (None, "CN"):
        targets += [("CN", c, n) for c, (n, m) in CN_INDICES.items()]
    if market in (None, "US"):
        targets += [("US", c, n) for c, (n, m) in US_INDICES.items()]

    for mk, code, name in targets:
        rows: list[dict] = []
        if mk == "CN":
            rows = _fetch_cn_akshare(code, name, mk, start, end)
        else:
            rows = _fetch_us_yfinance(code, name, mk, start, end)
        stored = await _upsert(rows)
        summary.setdefault(mk, {"fetched": 0, "stored": 0})
        summary[mk]["fetched"] += len(rows)
        summary[mk]["stored"] += stored
        logger.info("指数 %s(%s) 采集 %d 条，入库 %d 条", name, code, len(rows), stored)

    return summary
