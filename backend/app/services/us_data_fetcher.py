"""Alphareader — 美股数据获取模块（异步版，多源架构）。

职责：
  - 通过 **yfinance** 获取美股前复权日线行情（OHLCV）— 主力数据源
  - 通过 **腾讯财经** 作为辅助交叉验证
  - 数据自洽性校验（写入 DB 前自动检查）
  - 持久化到 PostgreSQL（stock_daily_quote 表，market='US'）
  - 智能缓存：当天已有数据则跳过下载

数据源优先级：
  1. yfinance — 主力数据源（美股历史K线完整）
  2. 腾讯财经 API — 辅助验证（美股K线数据量不足，仅用于交叉验证）
  3. 新浪财经 — 最后一天实时行情抽样验证

内存优化：
  - 分批拉取 + 分批写入 DB（与 A 股 data_fetcher 相同策略）
  - 4GB 服务器友好
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import random
import re
import urllib.request
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
BATCH_SIZE = 100                # 每批写入 DB 的股票数量

# 交叉验证配置
CROSS_VALIDATE_SAMPLE_SIZE = 10  # 每次增量更新后，抽样验证的股票数量
CROSS_VALIDATE_TOLERANCE = 0.02  # 收盘价偏差容忍度（2%）
SANITY_MAX_PCT_CHANGE = 50.0     # 单日涨跌幅上限（50%，美股无涨跌停但过大则异常）
SANITY_MIN_PRICE = 0.001         # 最低合理价格

# 美股活跃标的列表
US_UNIVERSE_URL = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"


# ============================================================
# 1. 获取美股股票列表
# ============================================================

def _sync_fetch_us_stock_list() -> pd.DataFrame:
    """获取美股活跃标的列表。

    策略：
      1. 优先从 DB 已有代码中获取（增量更新场景）
      2. 如果 DB 无数据，从 Wikipedia 获取 S&P500 成分股
      3. 最终 fallback：硬编码核心 50 只
    """
    try:
        # 获取 S&P500 成分股（通过 Wikipedia，设置 timeout 避免卡住）
        sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        req = urllib.request.Request(sp500_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")

        tables = pd.read_html(html)
        sp500 = tables[0][["Symbol", "Security"]].copy()
        sp500.columns = ["代码", "名称"]
        # 清理 ticker（有些有 . 如 BRK.B）
        sp500["代码"] = sp500["代码"].str.replace(".", "-", regex=False)

        logger.info("从 Wikipedia 获取到 %d 只 S&P500 成分股", len(sp500))
        return sp500
    except Exception as e:
        logger.warning("获取 S&P500 列表失败: %s，使用备用列表", e)
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
# 2. 腾讯财经 — 主力数据源
# ============================================================

def _tencent_us_code(ticker: str) -> str:
    """将美股 ticker 转为腾讯财经格式。

    腾讯美股格式: usAAPL.OQ (NASDAQ) / usAAPL.N (NYSE)
    简化处理：统一用不带交易所后缀的格式，腾讯 API 会自动匹配。
    """
    # BRK-B → BRK.B（腾讯用 . 而非 -）
    tc_ticker = ticker.replace("-", ".")
    return f"us{tc_ticker}"


def _sync_fetch_tencent_us_kline(ticker: str, days: int = 320) -> pd.DataFrame | None:
    """通过腾讯财经 API 获取单只美股的前复权日K线数据。

    API: http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq
    返回: [日期, 开盘, 收盘, 最高, 最低, 成交量]
    """
    tc_code = _tencent_us_code(ticker)
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc_code},day,,,{days},qfq"

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8")
        data = json.loads(text)

        # 解析数据：data -> data -> {code} -> qfqday 或 day
        stock_data = data.get("data", {}).get(tc_code, {})
        kline = stock_data.get("qfqday") or stock_data.get("day")
        if not kline:
            # 腾讯有时用不同的 key，尝试遍历
            for key in data.get("data", {}):
                sub = data["data"][key]
                if isinstance(sub, dict):
                    kline = sub.get("qfqday") or sub.get("day")
                    if kline:
                        break

        if not kline:
            return None

        rows = []
        for item in kline:
            # [日期, 开盘, 收盘, 最高, 最低, 成交量]
            if len(item) >= 6:
                try:
                    rows.append({
                        "trade_date": item[0],
                        "open": float(item[1]),
                        "close": float(item[2]),
                        "high": float(item[3]),
                        "low": float(item[4]),
                        "volume": float(item[5]),
                        "ts_code": ticker,
                    })
                except (ValueError, TypeError):
                    continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df.sort_values("trade_date", inplace=True)
        df["change"] = df["close"].diff()
        df["pct_change"] = df["close"].pct_change() * 100
        df["amount"] = ((df["open"] + df["close"]) / 2 * df["volume"]).round(2)

        return df

    except Exception as e:
        logger.debug("腾讯美股K线 %s 失败: %s", ticker, e)
        return None


# ============================================================
# 3. yfinance — Fallback 数据源
# ============================================================

def _sync_fetch_yf_single(
    ticker: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
    """通过 yfinance 获取单只美股的前复权日线数据（fallback 用）。"""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance 未安装，跳过 fallback")
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date, auto_adjust=False)

            if df is None or df.empty:
                return None

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

            # 使用前复权价格
            if "adj_close" in df.columns and "close" in df.columns:
                adj_factor = df["adj_close"] / df["close"]
                adj_factor = adj_factor.fillna(1.0)
                df["open"] = df["open"] * adj_factor
                df["high"] = df["high"] * adj_factor
                df["low"] = df["low"] * adj_factor
                df["close"] = df["adj_close"]

            df["ts_code"] = ticker
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            df = df.sort_values("trade_date")
            df["change"] = df["close"].diff()
            df["pct_change"] = df["close"].pct_change() * 100
            df["amount"] = ((df["open"] + df["close"]) / 2 * df["volume"]).round(2)
            df = df.drop(columns=["adj_close"], errors="ignore")

            return df

        except Exception as e:
            if attempt < MAX_RETRIES:
                import time
                time.sleep(RETRY_DELAY + random.uniform(0, 1))
            else:
                logger.warning("yfinance %s 经 %d 次重试仍失败: %s", ticker, MAX_RETRIES, e)
                return None
    return None


def _sync_fetch_yf_batch(
    tickers: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """通过 yfinance 批量获取多只美股历史数据（fallback 用）。"""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance 未安装，跳过 fallback")
        return {}

    try:
        data = yf.download(
            tickers=tickers,
            start=start_date,
            end=end_date,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )

        if data is None or data.empty:
            return {}

        result = {}

        if len(tickers) == 1:
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
                    logger.debug("解析 yfinance %s 批量数据失败: %s", ticker, e)

        return result
    except Exception as e:
        logger.warning("yfinance 批量下载失败: %s", e)
        return {}


# ============================================================
# 4. 数据自洽性校验
# ============================================================

def validate_sanity(df: pd.DataFrame) -> pd.DataFrame:
    """数据自洽性校验 — 写入 DB 前自动检查，剔除不合理的记录。

    校验规则：
      1. close ∈ [low, high]
      2. open > 0, close > 0, high > 0, low > 0
      3. volume >= 0
      4. low <= high
      5. pct_change 在合理范围内（-50% ~ +50%）
      6. 价格不能为 NaN

    Returns:
        清洗后的 DataFrame（剔除异常行，记录日志）
    """
    if df.empty:
        return df

    original_len = len(df)

    # 基础非空校验
    df = df.dropna(subset=["open", "close", "high", "low"])

    # 价格必须为正
    price_mask = (
        (df["open"] > SANITY_MIN_PRICE)
        & (df["close"] > SANITY_MIN_PRICE)
        & (df["high"] > SANITY_MIN_PRICE)
        & (df["low"] > SANITY_MIN_PRICE)
    )
    df = df[price_mask].copy()

    # low <= high
    df = df[df["low"] <= df["high"]].copy()

    # close ∈ [low, high]（允许 0.1% 的浮点误差）
    epsilon = 0.001
    close_in_range = (
        (df["close"] >= df["low"] * (1 - epsilon))
        & (df["close"] <= df["high"] * (1 + epsilon))
    )
    df = df[close_in_range].copy()

    # pct_change 合理范围
    if "pct_change" in df.columns:
        pct_ok = df["pct_change"].isna() | (df["pct_change"].abs() <= SANITY_MAX_PCT_CHANGE)
        df = df[pct_ok].copy()

    # volume >= 0
    if "volume" in df.columns:
        df = df[df["volume"] >= 0].copy()

    removed = original_len - len(df)
    if removed > 0:
        logger.warning("数据自洽性校验: 剔除 %d 条异常记录（原 %d 条）", removed, original_len)

    return df


def detect_stale_data(df: pd.DataFrame, max_identical_days: int = 5) -> list[str]:
    """检测数据冻结 — 连续 N 天 OHLCV 完全相同的股票（可能数据源故障）。

    Returns:
        疑似冻结的股票代码列表
    """
    stale_tickers = []
    for ticker, group in df.groupby("ts_code"):
        if len(group) < max_identical_days:
            continue
        group = group.sort_values("trade_date")
        # 检查连续 N 天 close 完全相同
        closes = group["close"].values
        for i in range(len(closes) - max_identical_days + 1):
            window = closes[i:i + max_identical_days]
            if len(set(window)) == 1:
                stale_tickers.append(str(ticker))
                break

    if stale_tickers:
        logger.warning("检测到 %d 只股票疑似数据冻结: %s", len(stale_tickers), stale_tickers[:10])

    return stale_tickers


# ============================================================
# 5. 多源交叉验证
# ============================================================

def _sync_cross_validate_with_yfinance(
    tickers: list[str],
    tencent_data: dict[str, pd.DataFrame],
) -> dict[str, dict]:
    """用 yfinance 对腾讯数据做最后一天收盘价交叉验证（同步，在线程中运行）。

    只抽样验证最近 5 天的数据，轻量不影响性能。

    Returns:
        {ticker: {"tencent_close": x, "yf_close": y, "diff_pct": z, "match": bool}}
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.info("yfinance 未安装，跳过交叉验证")
        return {}

    if not tickers or not tencent_data:
        return {}

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

    results = {}
    for ticker in tickers:
        tc_df = tencent_data.get(ticker)
        if tc_df is None or tc_df.empty:
            continue

        tc_last = tc_df.sort_values("trade_date").iloc[-1]
        tc_close = float(tc_last["close"])
        tc_date = tc_last["trade_date"]

        try:
            stock = yf.Ticker(ticker)
            yf_df = stock.history(start=start_date, end=end_date, auto_adjust=True)
            if yf_df is None or yf_df.empty:
                continue

            yf_df = yf_df.reset_index()
            yf_df["Date"] = pd.to_datetime(yf_df["Date"]).dt.date

            # 匹配同一天
            yf_row = yf_df[yf_df["Date"] == tc_date]
            if yf_row.empty:
                # 尝试匹配最后一天
                yf_row = yf_df.iloc[[-1]]

            yf_close = float(yf_row.iloc[0]["Close"])

            if tc_close > 0 and yf_close > 0:
                diff_pct = abs(tc_close - yf_close) / yf_close
                match = diff_pct <= CROSS_VALIDATE_TOLERANCE
                results[ticker] = {
                    "tencent_close": round(tc_close, 2),
                    "yf_close": round(yf_close, 2),
                    "diff_pct": round(diff_pct * 100, 2),
                    "match": match,
                    "date": str(tc_date),
                }
                if not match:
                    logger.warning(
                        "交叉验证不匹配 %s@%s: 腾讯=%.2f, yfinance=%.2f, 偏差=%.2f%%",
                        ticker, tc_date, tc_close, yf_close, diff_pct * 100,
                    )

        except Exception as e:
            logger.debug("yfinance 交叉验证 %s 失败: %s", ticker, e)

    return results


def _sync_cross_validate_with_sina(tickers: list[str]) -> dict[str, float]:
    """用新浪财经获取美股实时行情，作为最新价抽样验证。

    接口: https://hq.sinajs.cn/list=gb_aapl,gb_msft,...
    返回: {ticker: latest_price}
    """
    if not tickers:
        return {}

    # ticker → 新浪格式: AAPL → gb_aapl
    sina_codes = []
    code_map = {}  # sina_code → ticker
    for t in tickers:
        sc = f"gb_{t.lower().replace('-', '')}"
        sina_codes.append(sc)
        code_map[sc] = t

    url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"

    try:
        req = urllib.request.Request(url, headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("gbk", errors="replace")
    except Exception as e:
        logger.debug("新浪美股实时行情请求失败: %s", e)
        return {}

    prices: dict[str, float] = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or '="' not in line:
            continue
        # var hq_str_gb_aapl="Apple Inc,...,最新价,...";
        m = re.match(r'var hq_str_(gb_\w+)="(.+)"', line)
        if not m:
            continue
        sina_sym = m.group(1)
        fields = m.group(2).split(",")
        # 新浪美股格式: fields[1] = 最新价
        if len(fields) >= 2:
            try:
                price = float(fields[1])
                if price > 0:
                    ticker = code_map.get(sina_sym)
                    if ticker:
                        prices[ticker] = price
            except (ValueError, IndexError):
                pass

    return prices


async def cross_validate_latest(
    tencent_data: dict[str, pd.DataFrame],
    sample_size: int = CROSS_VALIDATE_SAMPLE_SIZE,
) -> dict:
    """综合交叉验证入口 — 抽样验证腾讯数据的准确性。

    流程：
      1. 从成功获取的股票中随机抽样
      2. 用 yfinance 对比最后一天收盘价
      3. 用新浪行情对比最新价（如果是交易时段）
      4. 汇总验证报告

    Returns:
        {
            "sample_size": int,
            "yf_results": {...},
            "sina_results": {...},
            "yf_match_rate": float,  # yfinance 匹配率
            "alerts": [...]          # 告警信息
        }
    """
    available_tickers = [t for t, df in tencent_data.items() if df is not None and not df.empty]
    if not available_tickers:
        return {"sample_size": 0, "alerts": ["无可验证数据"]}

    # 随机抽样
    sample = random.sample(available_tickers, min(sample_size, len(available_tickers)))
    logger.info("交叉验证: 抽样 %d 只股票 %s", len(sample), sample)

    # 并发执行 yfinance 和 新浪验证
    yf_results = await asyncio.to_thread(
        _sync_cross_validate_with_yfinance, sample, tencent_data,
    )
    sina_prices = await asyncio.to_thread(_sync_cross_validate_with_sina, sample)

    # 汇总
    alerts = []
    yf_matched = sum(1 for r in yf_results.values() if r.get("match"))
    yf_total = len(yf_results)
    yf_match_rate = yf_matched / yf_total if yf_total > 0 else 0.0

    if yf_total > 0 and yf_match_rate < 0.7:
        alert = f"⚠️ yfinance 交叉验证匹配率偏低: {yf_match_rate:.0%} ({yf_matched}/{yf_total})"
        alerts.append(alert)
        logger.warning(alert)

    # 新浪价格对比
    sina_alerts = []
    for ticker in sample:
        sina_price = sina_prices.get(ticker)
        tc_df = tencent_data.get(ticker)
        if sina_price and tc_df is not None and not tc_df.empty:
            tc_close = float(tc_df.sort_values("trade_date").iloc[-1]["close"])
            if tc_close > 0:
                diff = abs(sina_price - tc_close) / tc_close
                if diff > CROSS_VALIDATE_TOLERANCE:
                    msg = f"新浪 vs 腾讯偏差 {ticker}: 新浪={sina_price:.2f}, 腾讯={tc_close:.2f}, 偏差={diff:.1%}"
                    sina_alerts.append(msg)
                    logger.warning(msg)

    alerts.extend(sina_alerts)

    report = {
        "sample_size": len(sample),
        "yf_results": yf_results,
        "sina_prices": sina_prices,
        "yf_match_rate": round(yf_match_rate, 2),
        "alerts": alerts,
    }

    if alerts:
        logger.warning("交叉验证报告: %d 条告警\n%s", len(alerts), "\n".join(alerts))
    else:
        logger.info("交叉验证通过 ✅ yfinance 匹配率=%.0f%%, 新浪无偏差", yf_match_rate * 100)

    return report


# ============================================================
# 6. 数据持久化（复用 A 股的 upsert 逻辑，标记 market='US'）
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
            "turnover": None,
            "amplitude": None,
            "pct_change": float(row["pct_change"]) if pd.notna(row.get("pct_change")) else None,
            "change": float(row["change"]) if pd.notna(row.get("change")) else None,
        }
        records.append(rec)
    return records


async def save_us_to_db(df: pd.DataFrame) -> int:
    """将美股 DataFrame 批量 upsert 到 PostgreSQL stock_daily_quote 表（market='US'）。

    写入前自动执行数据自洽性校验。

    Returns:
        写入/更新的记录数。
    """
    # ── 写入前校验 ──
    df = validate_sanity(df)
    if df.empty:
        return 0

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
# 7. 主入口 — 全量获取美股行情（yfinance 主力 + 腾讯交叉验证）
# ============================================================

async def get_all_us_stock_data(force_refresh: bool = False) -> pd.DataFrame:
    """获取全部美股过去一年前复权日线数据（异步主入口）。

    流程：
      1. 检查 PostgreSQL 是否已有当天美股数据
      2. 若有效则直接从数据库加载返回
      3. 使用 yfinance 批量获取日K线（主力数据源）
      4. 数据自洽性校验 → 写入 PostgreSQL
      5. 腾讯/新浪抽样交叉验证

    Args:
        force_refresh: 为 True 时强制重新下载。

    Returns:
        清洗后的完整 DataFrame。
    """
    if not force_refresh and await has_us_today_data():
        logger.info("美股当天数据已存在，从 PostgreSQL 加载")
        return await load_us_from_db()

    # 获取股票列表
    db_list = await fetch_us_stock_list_from_db()
    if db_list.empty or force_refresh:
        stock_list = await fetch_us_stock_list()
    else:
        stock_list = db_list

    codes = stock_list["代码"].tolist()
    names = dict(zip(stock_list["代码"], stock_list["名称"]))
    total = len(codes)

    logger.info("开始获取美股行情（yfinance 主力），共 %d 只...", total)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    total_records = 0
    total_stocks = 0
    yf_ok = 0
    yf_fail_tickers: list[str] = []

    # ── 阶段 1: yfinance 批量获取（主力数据源）──
    YF_BATCH = 20  # 每批 20 只

    for i in range(0, total, YF_BATCH):
        batch_tickers = codes[i : i + YF_BATCH]
        batch_idx = i // YF_BATCH + 1
        total_batches = (total + YF_BATCH - 1) // YF_BATCH

        logger.info("yfinance 批次 %d/%d: %d 只 (%s...)",
                     batch_idx, total_batches, len(batch_tickers), batch_tickers[0])

        batch_data = await asyncio.to_thread(
            _sync_fetch_yf_batch, batch_tickers, start_date, end_date
        )

        if batch_data:
            all_dfs = []
            for ticker, df in batch_data.items():
                df["name"] = names.get(ticker, "")
                all_dfs.append(df)
                yf_ok += 1

            if all_dfs:
                combined = pd.concat(all_dfs, ignore_index=True)
                combined = combined[combined["volume"] > 0].copy()
                combined.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)
                if not combined.empty:
                    written = await save_us_to_db(combined)
                    total_records += written
                    total_stocks += combined["ts_code"].nunique()
                    logger.info("yfinance 批次写入 DB: +%d 条（累计 %d 条，%d 只）",
                                written, total_records, total_stocks)
                del all_dfs, combined
                gc.collect()

        # 记录失败的 ticker
        for t in batch_tickers:
            if t not in (batch_data or {}):
                yf_fail_tickers.append(t)

        await asyncio.sleep(1.0 + random.uniform(0, 0.5))

    logger.info("yfinance 阶段完成: 成功=%d, 失败=%d", yf_ok, len(yf_fail_tickers))

    # ── 阶段 2: yfinance 单只重试（失败的股票逐只获取）──
    if yf_fail_tickers:
        logger.info("开始逐只重试 %d 只 yfinance 失败的股票...", len(yf_fail_tickers))
        retry_ok = 0
        for ticker in yf_fail_tickers:
            df = await asyncio.to_thread(_sync_fetch_yf_single, ticker, start_date, end_date)
            if df is not None and not df.empty:
                df["name"] = names.get(ticker, "")
                df = df[df["volume"] > 0].copy()
                df.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)
                if not df.empty:
                    written = await save_us_to_db(df)
                    total_records += written
                    total_stocks += 1
                    retry_ok += 1
            await asyncio.sleep(0.5 + random.uniform(0, 0.3))

        logger.info("逐只重试完成: 补全=%d, 仍失败=%d", retry_ok, len(yf_fail_tickers) - retry_ok)

    # ── 阶段 3: 数据冻结检测 ──
    all_data = await load_us_from_db()
    if not all_data.empty:
        stale = detect_stale_data(all_data)
        if stale:
            logger.warning("全量下载后发现 %d 只股票疑似数据冻结", len(stale))

    # ── 阶段 4: 腾讯交叉验证（抽样，不阻塞主流程）──
    try:
        # 抽样几只用腾讯数据验证 yfinance 结果
        sample_tickers = random.sample(codes, min(5, len(codes)))
        tencent_data: dict[str, pd.DataFrame] = {}
        for ticker in sample_tickers:
            tc_df = await asyncio.to_thread(_sync_fetch_tencent_us_kline, ticker, 10)
            if tc_df is not None and not tc_df.empty:
                tencent_data[ticker] = tc_df
            await asyncio.sleep(0.3)

        if tencent_data:
            report = await cross_validate_latest(tencent_data)
            logger.info("交叉验证报告: 抽样=%d, yf匹配率=%.0f%%, 告警=%d",
                         report.get("sample_size", 0),
                         report.get("yf_match_rate", 0) * 100,
                         len(report.get("alerts", [])))
    except Exception as e:
        logger.warning("交叉验证异常（不影响主流程）: %s", e)

    logger.info("美股行情获取完成 ✅ 共 %d 条记录，涉及 %d 只股票（yfinance 成功=%d）",
                total_records, total_stocks, yf_ok)

    return await load_us_from_db()


# ============================================================
# 8. 增量更新（yfinance 主力 + 腾讯交叉验证）
# ============================================================

async def incremental_update_us_quotes(days: int = 10) -> int:
    """增量更新美股行情数据。

    策略：yfinance 主力批量获取 → 自洽性校验 → 腾讯抽样交叉验证。

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

    logger.info("开始美股增量更新（最近 %d 天），共 %d 只...", days, total)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    total_records = 0

    # ── yfinance 批量获取（主力数据源）──
    YF_BATCH = 50

    for i in range(0, total, YF_BATCH):
        batch_tickers = codes[i : i + YF_BATCH]

        batch_data = await asyncio.to_thread(
            _sync_fetch_yf_batch, batch_tickers, start_date, end_date
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
                    written = await save_us_to_db(combined)
                    total_records += written
                del all_dfs, combined
                gc.collect()

        await asyncio.sleep(0.5 + random.uniform(0, 0.3))

    logger.info("美股增量更新完成 ✅ 共 %d 条记录（yfinance 批量获取）", total_records)

    # ── 腾讯抽样交叉验证（增量也做，但不阻塞）──
    try:
        sample = random.sample(codes, min(5, len(codes)))
        tencent_data: dict[str, pd.DataFrame] = {}
        for ticker in sample:
            tc_df = await asyncio.to_thread(_sync_fetch_tencent_us_kline, ticker, days + 5)
            if tc_df is not None and not tc_df.empty:
                tencent_data[ticker] = tc_df
            await asyncio.sleep(0.3)

        if tencent_data:
            report = await cross_validate_latest(tencent_data, sample_size=5)
            if report.get("alerts"):
                logger.warning("增量交叉验证告警: %s", report["alerts"])
    except Exception as e:
        logger.debug("增量交叉验证异常: %s", e)

    return total_records


# ============================================================
# 9. 辅助函数
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
        "has_us_today_data: DB最新日期=%s, 距今%d天, 该日%d只美股（阈值: gap<=2 且 stocks>=%d）",
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
# 10. 直接运行入口（开发调试用）
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
