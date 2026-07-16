"""港股日K线行情抓取与入库（market='HK'）。

数据源：腾讯财经 hkfqkline（主，国内可直连）+ 新浪港股 K 线（兜底）。
入库到 stock_daily_quote 表，market='HK'，ts_code 为 5 位零填充代码
（与 SEPA 股池 symbol 一致，如 "00700"）。

仅维护 SEPA / VCP 分析所需的日行情，不做全市场扫描（港股全列表获取成本高）。
默认从 SEPA 股池已关注的 HK 标的 + 可选代码列表抓取。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.sepa import SepaWatchlistItem
from app.models.stock import StockDailyQuote

logger = logging.getLogger("alphareader.hk_data_fetcher")

LOOKBACK_DAYS = 400  # 多抓一些，覆盖回测所需历史


# ───────────────────────────────────────────────────────────
# 1. 单只抓取（同步，在线程内运行）
# ───────────────────────────────────────────────────────────

def _tencent_hk_code(code: str) -> str:
    return f"hk{code.zfill(5)}"


def _sync_fetch_tencent_hk_kline(code: str, days: int = LOOKBACK_DAYS) -> list[dict] | None:
    """腾讯财经港股前复权日K线。返回 [日期,开盘,收盘,最高,最低,成交量] 行。"""
    tc = _tencent_hk_code(code)
    url = f"http://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param={tc},day,,,{days},qfq"
    try:
        import urllib.request
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        stock_data = data.get("data", {}).get(tc, {})
        kline = stock_data.get("qfqday") or stock_data.get("day")
        if not kline:
            return None
        rows = []
        for item in kline:
            if len(item) < 6:
                continue
            rows.append({
                "日期": item[0], "开盘": float(item[1]), "收盘": float(item[2]),
                "最高": float(item[3]), "最低": float(item[4]), "成交量": float(item[5]),
                "股票代码": code.zfill(5),
            })
        return rows or None
    except Exception as e:
        logger.debug("腾讯港股K线 %s 失败: %s", code, e)
        return None


def _sync_fetch_sina_hk_kline(code: str, days: int = LOOKBACK_DAYS) -> list[dict] | None:
    """新浪港股 K 线兜底。"""
    sina_code = f"hk{code.zfill(5)}"
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketDataService.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen={days}"
    )
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("gbk", errors="replace")
        data = json.loads(text)
        if not data:
            return None
        rows = []
        for item in data:
            rows.append({
                "日期": item["day"], "开盘": float(item["open"]), "收盘": float(item["close"]),
                "最高": float(item["high"]), "最低": float(item["low"]),
                "成交量": float(item.get("volume", 0) or 0),
                "股票代码": code.zfill(5),
            })
        return rows or None
    except Exception as e:
        logger.debug("新浪港股K线 %s 失败: %s", code, e)
        return None


# ───────────────────────────────────────────────────────────
# 2. 入库
# ───────────────────────────────────────────────────────────

async def _save_records(records: list[dict], names: dict[str, str] | None = None) -> int:
    """将港股记录 upsert 到 stock_daily_quote（market='HK'）。返回写入条数。"""
    names = names or {}
    if not records:
        return 0
    rows = []
    for r in records:
        d = r["日期"]
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d").date()
        code = r["股票代码"]
        rows.append({
            "ts_code": code,
            "name": names.get(code, "") or "",
            "trade_date": d,
            "market": "HK",
            "open": r["开盘"], "close": r["收盘"], "high": r["最高"], "low": r["最低"],
            "volume": int(r["成交量"]),
            "amount": None, "turnover": None, "amplitude": None,
            "pct_change": None, "change": None,
        })
    total = 0
    async with async_session() as session:
        batch_size = 2000
        for i in range(0, len(rows), batch_size):
            batch = rows[i: i + batch_size]
            stmt = pg_insert(StockDailyQuote).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_quote_code_date",
                set_={
                    "name": func.coalesce(
                        func.nullif(stmt.excluded.name, ""), StockDailyQuote.name
                    ),
                    "market": stmt.excluded.market,
                    "open": stmt.excluded.open,
                    "close": stmt.excluded.close,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "volume": stmt.excluded.volume,
                },
            )
            await session.execute(stmt)
            total += len(batch)
        await session.commit()
    return total


# ───────────────────────────────────────────────────────────
# 3. 批量抓取（异步）
# ───────────────────────────────────────────────────────────

async def fetch_hk_klines(codes: list[str], names: dict[str, str] | None = None) -> int:
    """批量抓取并入库港股日K线。返回写入记录数。幂等（upsert）。"""
    names = names or {}
    all_records: list[dict] = []
    ok_stocks = 0
    for code in codes:
        recs = None
        try:
            recs = await asyncio.to_thread(_sync_fetch_tencent_hk_kline, code, LOOKBACK_DAYS)
            if not recs:
                recs = await asyncio.to_thread(_sync_fetch_sina_hk_kline, code, LOOKBACK_DAYS)
        except Exception as e:
            logger.warning("港股 %s 抓取异常: %s", code, e)
            recs = None
        if recs:
            all_records.extend(recs)
            ok_stocks += 1
        await asyncio.sleep(0.3 + random.uniform(0, 0.2))

    written = await _save_records(all_records, names)
    logger.info("港股K线入库完成：%d 只成功，%d 条记录", ok_stocks, written)
    return written


async def _hk_watchlist_codes() -> tuple[list[str], dict[str, str]]:
    """从 SEPA 股池读取已关注的 HK 标的及其名称。"""
    async with async_session() as session:
        res = await session.execute(
            select(SepaWatchlistItem.symbol, SepaWatchlistItem.name)
            .where(SepaWatchlistItem.market == "HK")
        )
        rows = res.all()
    codes = [s.zfill(5) for s, _ in rows]
    names = {s.zfill(5): (n or "") for s, n in rows}
    return codes, names


async def refresh_hk_quotes(extra_codes: list[str] | None = None) -> int:
    """日常刷新：抓取 SEPA 股池中的 HK 标的（幂等 upsert 全量历史）。"""
    codes, names = await _hk_watchlist_codes()
    seen = set(codes)
    for c in (extra_codes or []):
        c = c.strip().zfill(5)
        if c not in seen:
            codes.append(c)
            seen.add(c)
    if not codes:
        logger.info("港股刷新跳过：股池无 HK 标的")
        return 0
    return await fetch_hk_klines(codes, names)
