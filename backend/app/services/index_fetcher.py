"""基准指数日行情采集 — 写入 index_daily 表。

A 股：腾讯财经（sh{code}）优先，akshare 兜底（沪深300=000300 / 中证1000=000852）
美股：新浪财经 US_MinKService（^GSPC→.INX 标普500 / ^IXIC→.IXIC 纳斯达克）优先（服务器可达+完整历史），
      yfinance（429 限流时失败）/ 腾讯（仅最新 1 天）兜底。
      入库 index_code 统一用 yfinance 代码（^GSPC/^IXIC），与 VCP load_benchmark_index 对齐。

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
# 美股指数：yfinance 代码 → (名称, 市场, 新浪代码)
# 新浪美股指数历史完整（2004 起），服务器可达，作为美股主数据源。
US_INDICES = {
    "^GSPC": ("标普500", "US", ".INX"),
    "^IXIC": ("纳斯达克", "US", ".IXIC"),
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


def _fetch_cn_tencent(code: str, name: str, market: str, start: date, end: date) -> list[dict]:
    """腾讯财经采集 A 股指数（服务器对腾讯行情可达，优先于 akshare）。

    API: http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh{code},day,{start},{end},400,qfq
    返回: data.data.{tc_code}.qfqday = [[日期, 开盘, 收盘, 最高, 最低, 成交量], ...]
    """
    import json
    import urllib.request

    tc_code = f"sh{code}"
    url = (
        f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={tc_code},day,{start.strftime('%Y-%m-%d')},{end.strftime('%Y-%m-%d')},400,qfq"
    )
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8")
        data = json.loads(text)
        stock_data = data.get("data", {}).get(tc_code, {})
        kline = stock_data.get("day") or stock_data.get("qfqday")
        if not kline:
            return []
        out = []
        for item in kline:
            if len(item) < 6:
                continue
            d = _parse_date(item[0])
            if d is None:
                continue
            out.append({
                "index_code": code, "index_name": name, "market": market,
                "trade_date": d,
                "open": _f(item[1]), "close": _f(item[2]),
                "high": _f(item[3]), "low": _f(item[4]),
                "volume": _f(item[5]), "amount": None,
                "source": "tencent",
            })
        return out
    except Exception as e:
        logger.warning("腾讯采集指数 %s 失败: %s", code, e)
        return []


def _fetch_cn_akshare(code: str, name: str, market: str, start: date, end: date) -> list[dict]:
    """akshare 采集 A 股指数（腾讯不可达时的兜底）。失败时返回 []。"""
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


def _fetch_us_tencent(tc_code: str, store_code: str, name: str, market: str, start: date, end: date) -> list[dict]:
    """腾讯财经采集美股指数（yfinance 不可达时的兜底）。"""
    import json
    import urllib.request

    url = (
        f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={tc_code},day,{start.strftime('%Y-%m-%d')},{end.strftime('%Y-%m-%d')},400,qfq"
    )
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8")
        data = json.loads(text)
        stock_data = data.get("data", {}).get(tc_code, {})
        kline = stock_data.get("day") or stock_data.get("qfqday")
        if not kline:
            return []
        out = []
        for item in kline:
            if len(item) < 6:
                continue
            d = _parse_date(item[0])
            if d is None:
                continue
            out.append({
                "index_code": store_code, "index_name": name, "market": market,
                "trade_date": d,
                "open": _f(item[1]), "close": _f(item[2]),
                "high": _f(item[3]), "low": _f(item[4]),
                "volume": _f(item[5]), "amount": None,
                "source": "tencent",
            })
        return out
    except Exception as e:
        logger.warning("腾讯采集美股指数 %s 失败: %s", store_code, e)
        return []


def _fetch_us_yfinance(code: str, name: str, market: str, start: date, end: date) -> list[dict]:
    """yfinance 采集美股指数。失败时回退腾讯（仅 ^IXIC 有可靠腾讯代码）。"""
    try:
        import yfinance as yf
    except Exception as e:
        logger.warning("yfinance 不可用，跳过美股指数 %s: %s", code, e)
        return []
    try:
        tk = yf.Ticker(code)
        hist = tk.history(start=start, end=end + timedelta(days=1), interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            raise ValueError("empty history")
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
        logger.warning("yfinance 采集指数 %s 失败: %s", code, e)
        # 美股仅 ^IXIC 有可靠腾讯代码可兜底
        if code == "^IXIC":
            logger.info("回退腾讯采集 %s", code)
            return _fetch_us_tencent("usIXIC", "^IXIC", name, market, start, end)
        return []


def _fetch_us_sina(sina_code: str, store_code: str, name: str, market: str, start: date, end: date) -> list[dict]:
    """新浪财经采集美股指数日线（服务器可达，返回完整历史；美股主数据源）。

    API: https://stock.finance.sina.com.cn/usstock/api/json.php/US_MinKService.getDailyK?symbol={sina_code}
    返回: [{"d":"2026-07-13","o":开放,"h":最高,"l":最低,"c":收盘,"v":成交量,"a":成交额}, ...]
    sina_code 带点号前缀：.IXIC(纳指) / .INX(标普500) / .DJI(道指)

    入库 index_code 用 store_code（yfinance 代码 ^GSPC/^IXIC），与 VCP 对齐。
    """
    import json
    import urllib.request

    url = (
        "https://stock.finance.sina.com.cn/usstock/api/json.php/"
        f"US_MinKService.getDailyK?symbol={sina_code}"
    )
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8")
        data = json.loads(text)
        if not isinstance(data, list) or not data:
            logger.warning("新浪美股指数 %s 返回空", store_code)
            return []
        out = []
        for item in data:
            d = _parse_date(item.get("d"))
            if d is None or d < start or d > end:
                continue
            raw_a = item.get("a")
            out.append({
                "index_code": store_code, "index_name": name, "market": market,
                "trade_date": d,
                "open": _f(item.get("o")), "high": _f(item.get("h")),
                "low": _f(item.get("l")), "close": _f(item.get("c")),
                "volume": _f(item.get("v")),
                "amount": _f(raw_a) if raw_a not in (None, "0", 0) else None,
                "source": "sina",
            })
        return out
    except Exception as e:
        logger.warning("新浪采集美股指数 %s 失败: %s", store_code, e)
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
        targets += [("US", c, n, s) for c, (n, m, s) in US_INDICES.items()]

    for t in targets:
        mk = t[0]
        rows: list[dict] = []
        if mk == "CN":
            _, code, name = t
            # 腾讯财经优先（服务器可达），akshare 兜底
            rows = _fetch_cn_tencent(code, name, mk, start, end)
            if not rows:
                rows = _fetch_cn_akshare(code, name, mk, start, end)
        else:
            _, code, name, sina = t
            # 新浪美股指数优先（服务器可达+完整历史），yfinance/腾讯兜底
            rows = _fetch_us_sina(sina, code, name, mk, start, end)
            if not rows:
                rows = _fetch_us_yfinance(code, name, mk, start, end)
        stored = await _upsert(rows)
        summary.setdefault(mk, {"fetched": 0, "stored": 0})
        summary[mk]["fetched"] += len(rows)
        summary[mk]["stored"] += stored
        logger.info("指数 %s(%s) 采集 %d 条，入库 %d 条", name, code, len(rows), stored)

    return summary
