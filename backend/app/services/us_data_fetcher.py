"""Alphareader — 美股数据获取模块（异步版）。

职责：
  - 通过 yfinance 获取美股前复权日线行情（OHLCV）
  - 数据清洗（剔除停牌、去重）
  - 持久化到 PostgreSQL（stock_daily_quote 表，market='US'）
  - 智能缓存：当天已有数据则跳过下载

数据源：
  - yfinance — Yahoo Finance API wrapper，轻量可靠，免费无限制

内存优化：
  - 分批拉取 + 分批写入 DB（与 A 股 data_fetcher 相同策略）
  - 4GB 服务器友好
"""

from __future__ import annotations

import asyncio
import gc
import logging
import random
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.stock import StockDailyQuote

logger = logging.getLogger("alphareader.us_data_fetcher")

# ────────── 配置 ──────────
LOOKBACK_DAYS = 365             # 回溯天数（约 252 个交易日）
MAX_RETRIES = 3                 # 单只股票最大重试次数
RETRY_DELAY = 2                 # 重试间隔（秒）
BATCH_SIZE = 100                # 每批写入 DB 的股票数量（美股总数少于 A 股）

# 美股活跃标的列表（NYSE + NASDAQ 主要成分股）
# Phase 2 先用静态列表，Phase 3 会接入 Finnhub 动态获取
US_UNIVERSE_URL = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"


# ============================================================
# 1. 获取美股股票列表
# ============================================================

def _sync_fetch_us_stock_list() -> pd.DataFrame:
    """获取美股活跃标的列表。

    策略：
      1. 优先从 DB 已有代码中获取（增量更新场景）
      2. 如果 DB 无数据，使用 yfinance 获取 S&P500 + NASDAQ100 成分股作为初始列表
    """
    try:
        import yfinance as yf

        # 获取 S&P500 成分股（通过 Wikipedia）
        sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(sp500_url)
        sp500 = tables[0][["Symbol", "Security"]].copy()
        sp500.columns = ["代码", "名称"]
        # 清理 ticker（有些有 . 如 BRK.B）
        sp500["代码"] = sp500["代码"].str.replace(".", "-", regex=False)

        logger.info("从 Wikipedia 获取到 %d 只 S&P500 成分股", len(sp500))
        return sp500
    except Exception as e:
        logger.warning("获取 S&P500 列表失败: %s，使用备用列表", e)
        # 备用：硬编码核心 50 只
        return _get_core_us_tickers()


def _get_core_us_tickers() -> pd.DataFrame:
    """备用的核心美股列表（市值最大的 ~50 只）。"""
    tickers = {
        "AAPL": "Apple Inc.",
        "MSFT": "Microsoft Corporation",
        "GOOGL": "Alphabet Inc.",
        "AMZN": "Amazon.com Inc.",
        "NVDA": "NVIDIA Corporation",
        "META": "Meta Platforms Inc.",
        "TSLA": "Tesla Inc.",
        "BRK-B": "Berkshire Hathaway Inc.",
        "UNH": "UnitedHealth Group Inc.",
        "JNJ": "Johnson & Johnson",
        "V": "Visa Inc.",
        "XOM": "Exxon Mobil Corporation",
        "JPM": "JPMorgan Chase & Co.",
        "WMT": "Walmart Inc.",
        "MA": "Mastercard Inc.",
        "PG": "Procter & Gamble Co.",
        "HD": "The Home Depot Inc.",
        "CVX": "Chevron Corporation",
        "MRK": "Merck & Co. Inc.",
        "ABBV": "AbbVie Inc.",
        "LLY": "Eli Lilly and Company",
        "AVGO": "Broadcom Inc.",
        "PEP": "PepsiCo Inc.",
        "KO": "The Coca-Cola Company",
        "COST": "Costco Wholesale Corp.",
        "TMO": "Thermo Fisher Scientific",
        "ADBE": "Adobe Inc.",
        "MCD": "McDonald's Corporation",
        "CSCO": "Cisco Systems Inc.",
        "CRM": "Salesforce Inc.",
        "ACN": "Accenture plc",
        "ABT": "Abbott Laboratories",
        "DHR": "Danaher Corporation",
        "NKE": "NIKE Inc.",
        "TXN": "Texas Instruments Inc.",
        "NEE": "NextEra Energy Inc.",
        "PM": "Philip Morris International",
        "NFLX": "Netflix Inc.",
        "AMD": "Advanced Micro Devices",
        "INTC": "Intel Corporation",
        "QCOM": "QUALCOMM Inc.",
        "ORCL": "Oracle Corporation",
        "IBM": "International Business Machines",
        "DIS": "The Walt Disney Company",
        "BA": "The Boeing Company",
        "GE": "General Electric Company",
        "CAT": "Caterpillar Inc.",
        "GS": "Goldman Sachs Group Inc.",
        "AMAT": "Applied Materials Inc.",
        "NOW": "ServiceNow Inc.",
    }
    return pd.DataFrame(
        [{"代码": k, "名称": v} for k, v in tickers.items()]
    )


async def fetch_us_stock_list() -> pd.DataFrame:
    """异步包装：获取美股股票列表。"""
    logger.info("正在获取美股股票列表...")
    df = await asyncio.to_thread(_sync_fetch_us_stock_list)
    logger.info("共获取到 %d 只美股", len(df))
    return df


async def fetch_us_stock_list_from_db() -> pd.DataFrame:
    """从数据库中获取已有的美股代码列表。"""
    sql = sa_text("""
        SELECT DISTINCT ON (ts_code) ts_code, name
        FROM stock_daily_quote
        WHERE market = 'US'
        ORDER BY ts_code,
                 CASE WHEN name IS NOT NULL AND name != '' THEN 0 ELSE 1 END,
                 trade_date DESC
    """)

    async with async_session() as session:
        result = await session.execute(sql)
        rows = result.all()

    if not rows:
        return pd.DataFrame(columns=["代码", "名称"])

    data = [{"代码": r[0], "名称": r[1] or ""} for r in rows]
    df = pd.DataFrame(data)
    logger.info("从数据库获取到 %d 只美股代码", len(df))
    return df


# ============================================================
# 2. 通过 yfinance 获取单只/批量美股历史行情
# ============================================================

def _sync_fetch_single_us_stock(
    ticker: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
    """通过 yfinance 获取单只美股的前复权日线数据。

    Args:
        ticker: 美股 ticker（如 "AAPL"）
        start_date: 起始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"

    Returns:
        DataFrame 或 None
    """
    import yfinance as yf

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date, auto_adjust=False)

            if df is None or df.empty:
                return None

            # yfinance 返回格式：index=Date, columns=[Open,High,Low,Close,Adj Close,Volume]
            df = df.reset_index()
            df = df.rename(columns={
                "Date": "trade_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            })

            # 使用前复权价格（Adj Close 比率调整）
            if "adj_close" in df.columns and "close" in df.columns:
                adj_factor = df["adj_close"] / df["close"]
                adj_factor = adj_factor.fillna(1.0)
                df["open"] = df["open"] * adj_factor
                df["high"] = df["high"] * adj_factor
                df["low"] = df["low"] * adj_factor
                df["close"] = df["adj_close"]

            df["ts_code"] = ticker
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

            # 计算涨跌额和涨跌幅
            df = df.sort_values("trade_date")
            df["change"] = df["close"].diff()
            df["pct_change"] = df["close"].pct_change() * 100

            # 计算成交额（粗估：avg_price × volume）
            df["amount"] = ((df["open"] + df["close"]) / 2 * df["volume"]).round(2)

            # 清理不需要的列
            df = df.drop(columns=["adj_close"], errors="ignore")

            return df

        except Exception as e:
            if attempt < MAX_RETRIES:
                import time
                time.sleep(RETRY_DELAY + random.uniform(0, 1))
            else:
                logger.warning("%s 经 %d 次重试仍失败: %s", ticker, MAX_RETRIES, e)
                return None
    return None


def _sync_fetch_batch_us_stocks(
    tickers: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """通过 yfinance 批量获取多只美股历史数据（单次 HTTP 请求）。

    yfinance.download() 支持批量下载，效率远高于逐只请求。

    Returns:
        {ticker: DataFrame} 字典
    """
    import yfinance as yf

    try:
        data = yf.download(
            tickers=tickers,
            start=start_date,
            end=end_date,
            auto_adjust=True,  # 直接返回前复权价
            group_by="ticker",
            threads=True,
            progress=False,
        )

        if data is None or data.empty:
            return {}

        result = {}

        if len(tickers) == 1:
            # 单只股票时 yfinance 返回单层 columns
            ticker = tickers[0]
            df = data.reset_index()
            df.columns = [c.lower() if isinstance(c, str) else c for c in df.columns]
            if "date" in df.columns:
                df = df.rename(columns={"date": "trade_date"})
            df["ts_code"] = ticker
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            df = df.sort_values("trade_date")
            df["change"] = df["close"].diff()
            df["pct_change"] = df["close"].pct_change() * 100
            df["amount"] = ((df["open"] + df["close"]) / 2 * df["volume"]).round(2)
            result[ticker] = df
        else:
            # 多只股票时 yfinance 返回 MultiIndex columns: (ticker, field)
            for ticker in tickers:
                try:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    df = data[ticker].dropna(how="all").reset_index()
                    if df.empty:
                        continue
                    df.columns = [c.lower() if isinstance(c, str) else c for c in df.columns]
                    if "date" in df.columns:
                        df = df.rename(columns={"date": "trade_date"})
                    df["ts_code"] = ticker
                    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
                    df = df.sort_values("trade_date")
                    df["change"] = df["close"].diff()
                    df["pct_change"] = df["close"].pct_change() * 100
                    df["amount"] = ((df["open"] + df["close"]) / 2 * df["volume"]).round(2)
                    result[ticker] = df
                except Exception as e:
                    logger.debug("解析 %s 批量数据失败: %s", ticker, e)

        return result
    except Exception as e:
        logger.warning("yfinance 批量下载失败: %s", e)
        return {}


# ============================================================
# 3. 数据持久化（复用 A 股的 upsert 逻辑，标记 market='US'）
# ============================================================

def _us_df_to_records(df: pd.DataFrame) -> list[dict]:
    """将美股 DataFrame 转换为 ORM 兼容的 dict 列表。"""
    records = []
    required_cols = {"ts_code", "trade_date", "open", "close", "high", "low", "volume"}
    if not required_cols.issubset(set(df.columns)):
        logger.warning("DataFrame 缺少必要列: %s", required_cols - set(df.columns))
        return []

    for _, row in df.iterrows():
        rec = {
            "ts_code": str(row["ts_code"]),
            "name": str(row.get("name", "") or ""),
            "trade_date": row["trade_date"] if isinstance(row["trade_date"], date) else pd.to_datetime(row["trade_date"]).date(),
            "market": "US",
            "open": float(row["open"]) if pd.notna(row["open"]) else None,
            "close": float(row["close"]) if pd.notna(row["close"]) else None,
            "high": float(row["high"]) if pd.notna(row["high"]) else None,
            "low": float(row["low"]) if pd.notna(row["low"]) else None,
            "volume": int(row["volume"]) if pd.notna(row["volume"]) else None,
            "amount": float(row.get("amount", 0) or 0) if pd.notna(row.get("amount")) else None,
            "turnover": None,  # yfinance 不提供换手率
            "amplitude": None,
            "pct_change": float(row["pct_change"]) if pd.notna(row.get("pct_change")) else None,
            "change": float(row["change"]) if pd.notna(row.get("change")) else None,
        }
        records.append(rec)
    return records


async def save_us_to_db(df: pd.DataFrame) -> int:
    """将美股 DataFrame 批量 upsert 到 PostgreSQL stock_daily_quote 表（market='US'）。

    Returns:
        写入/更新的记录数。
    """
    records = _us_df_to_records(df)
    if not records:
        return 0

    batch_size = 2000
    total_written = 0

    async with async_session() as session:
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            stmt = pg_insert(StockDailyQuote).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_quote_code_date",
                set_={
                    "name": func.coalesce(
                        func.nullif(stmt.excluded.name, ""),
                        StockDailyQuote.name,
                    ),
                    "market": stmt.excluded.market,
                    "open": stmt.excluded.open,
                    "close": stmt.excluded.close,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                    "pct_change": stmt.excluded.pct_change,
                    "change": stmt.excluded.change,
                },
            )
            await session.execute(stmt)
            total_written += len(batch)
        await session.commit()

    logger.info("美股数据已写入 PostgreSQL，共 %d 条记录", total_written)
    return total_written


# ============================================================
# 4. 主入口 — 全量获取美股行情
# ============================================================

async def get_all_us_stock_data(force_refresh: bool = False) -> pd.DataFrame:
    """获取全部美股过去一年前复权日线数据（异步主入口）。

    流程：
      1. 检查 PostgreSQL 是否已有当天美股数据
      2. 若有效则直接从数据库加载返回
      3. 否则使用 yfinance 批量下载
      4. 写入 PostgreSQL → 返回

    Args:
        force_refresh: 为 True 时强制重新下载。

    Returns:
        清洗后的完整 DataFrame。
    """
    if not force_refresh and await has_us_today_data():
        logger.info("美股当天数据已存在，从 PostgreSQL 加载")
        return await load_us_from_db()

    # 尝试从 DB 获取已有列表
    db_list = await fetch_us_stock_list_from_db()
    if db_list.empty or force_refresh:
        # 首次运行或强制刷新：获取在线列表
        stock_list = await fetch_us_stock_list()
    else:
        stock_list = db_list

    codes = stock_list["代码"].tolist()
    names = dict(zip(stock_list["代码"], stock_list["名称"]))
    total = len(codes)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    logger.info("开始通过 yfinance 下载美股行情 (%s ~ %s)，共 %d 只...", start_date, end_date, total)

    total_records = 0
    total_stocks = 0

    # yfinance 支持批量下载，每批 20 只（避免单次请求过大）
    YF_BATCH = 20
    for i in range(0, total, YF_BATCH):
        batch_tickers = codes[i : i + YF_BATCH]
        logger.info("yfinance 批次 %d/%d (tickers: %s...)",
                     i // YF_BATCH + 1,
                     (total + YF_BATCH - 1) // YF_BATCH,
                     batch_tickers[:3])

        batch_data = await asyncio.to_thread(
            _sync_fetch_batch_us_stocks, batch_tickers, start_date, end_date
        )

        if batch_data:
            all_dfs = []
            for ticker, df in batch_data.items():
                df["name"] = names.get(ticker, "")
                all_dfs.append(df)

            if all_dfs:
                combined = pd.concat(all_dfs, ignore_index=True)
                # 剔除停牌（volume==0）
                combined = combined[combined["volume"] > 0].copy()
                combined.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)

                if not combined.empty:
                    await save_us_to_db(combined)
                    total_records += len(combined)
                    total_stocks += combined["ts_code"].nunique()

                del all_dfs, combined
                gc.collect()

        # yfinance 间隔
        await asyncio.sleep(1.0 + random.uniform(0, 0.5))

    logger.info("美股行情下载完成，共 %d 条记录，涉及 %d 只股票", total_records, total_stocks)

    return await load_us_from_db()


# ============================================================
# 5. 增量更新（只拉最近几天）
# ============================================================

async def incremental_update_us_quotes(days: int = 10) -> int:
    """增量更新美股行情数据。

    Args:
        days: 回溯天数，默认 10

    Returns:
        新增/更新的记录数
    """
    if await has_us_today_data():
        logger.info("美股增量更新跳过：今天的行情数据已存在")
        return 0

    db_list = await fetch_us_stock_list_from_db()
    if db_list.empty:
        logger.warning("美股增量更新失败：数据库中无美股列表")
        return 0

    codes = db_list["代码"].tolist()
    names = dict(zip(db_list["代码"], db_list["名称"]))
    total = len(codes)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    logger.info("开始美股增量更新（最近 %d 天），共 %d 只...", days, total)

    total_records = 0
    YF_BATCH = 50  # 增量数据量小，可以用更大的批次

    for i in range(0, total, YF_BATCH):
        batch_tickers = codes[i : i + YF_BATCH]

        batch_data = await asyncio.to_thread(
            _sync_fetch_batch_us_stocks, batch_tickers, start_date, end_date
        )

        if batch_data:
            all_dfs = []
            for ticker, df in batch_data.items():
                df["name"] = names.get(ticker, "")
                all_dfs.append(df)

            if all_dfs:
                combined = pd.concat(all_dfs, ignore_index=True)
                combined = combined[combined["volume"] > 0].copy()
                combined.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)

                if not combined.empty:
                    await save_us_to_db(combined)
                    total_records += len(combined)

                del all_dfs, combined
                gc.collect()

        await asyncio.sleep(0.5 + random.uniform(0, 0.3))

    logger.info("美股增量更新完成，共 %d 条记录", total_records)
    return total_records


# ============================================================
# 6. 辅助函数
# ============================================================

async def has_us_today_data(min_stocks: int = 100) -> bool:
    """检查是否已有最新交易日的美股数据。

    美股约 500+（S&P500）只活跃标的，阈值设为 100。
    """
    today = date.today()
    async with async_session() as session:
        max_date_result = await session.execute(
            select(func.max(StockDailyQuote.trade_date))
            .where(StockDailyQuote.market == "US")
        )
        max_date = max_date_result.scalar()
        if max_date is None:
            logger.info("has_us_today_data: 数据库无美股数据")
            return False

        gap_days = (today - max_date).days

        count_result = await session.execute(
            select(func.count(func.distinct(StockDailyQuote.ts_code)))
            .where(StockDailyQuote.trade_date == max_date)
            .where(StockDailyQuote.market == "US")
        )
        stock_count = count_result.scalar() or 0

    logger.info(
        "has_us_today_data: DB最新日期=%s, 距今%d天, 该日%d只美股（阈值: gap<=1 且 stocks>=%d）",
        max_date, gap_days, stock_count, min_stocks,
    )
    # 美股可能因时差晚一天，允许 gap<=2
    return gap_days <= 2 and stock_count >= min_stocks


async def load_us_from_db(min_date: date | None = None) -> pd.DataFrame:
    """从 PostgreSQL 加载美股行情数据。

    Returns:
        包含行情数据的 DataFrame（英文列名）。
    """
    if min_date is None:
        min_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date()

    async with async_session() as session:
        result = await session.execute(
            select(StockDailyQuote)
            .where(StockDailyQuote.market == "US")
            .where(StockDailyQuote.trade_date >= min_date)
            .order_by(StockDailyQuote.ts_code, StockDailyQuote.trade_date)
        )
        rows = result.scalars().all()

    if not rows:
        return pd.DataFrame()

    data = []
    for r in rows:
        data.append({
            "ts_code": r.ts_code,
            "name": r.name,
            "trade_date": r.trade_date,
            "open": r.open,
            "close": r.close,
            "high": r.high,
            "low": r.low,
            "volume": r.volume,
            "amount": r.amount,
            "pct_change": r.pct_change,
            "change": r.change,
        })

    df = pd.DataFrame(data)
    logger.info("从 PostgreSQL 加载 %d 条美股记录（>= %s）", len(df), min_date)
    return df


# ============================================================
# 7. 直接运行入口（开发调试用）
# ============================================================

if __name__ == "__main__":
    import asyncio as _asyncio

    async def _main():
        df = await get_all_us_stock_data()
        if not df.empty:
            print("\n===== 美股数据预览 =====")
            print(df.head(10))
            print(f"\n股票数量: {df['ts_code'].nunique()}")
            print(f"记录总数: {len(df)}")
            print(f"日期范围: {df['trade_date'].min()} ~ {df['trade_date'].max()}")
        else:
            print("[ERROR] 未获取到有效美股数据。")

    _asyncio.run(_main())
