"""Alphareader — A 股数据获取模块（异步版）。

职责：
  - 优先通过腾讯财经 API 获取 A 股前复权日线行情（速度快、稳定）
  - akshare 作为备选数据源（当腾讯 API 失败时降级使用）
  - 数据清洗（剔除停牌、去重）
  - 持久化到 PostgreSQL（stock_daily_quote 表）
  - 智能缓存：当天已有数据则跳过下载

数据源优先级：
  1. 腾讯财经 API（日K线、实时行情）— 轻量、无需 akshare 依赖
  2. akshare（东方财富）— 功能全面，但依赖重、偶尔不稳定

核心逻辑：
  akshare 为同步库，通过 asyncio.to_thread() 在线程池中执行，
  避免阻塞 FastAPI 事件循环。

错误处理：
  - 单只股票失败不影响其他股票（逐只 try/except + 重试）
  - 全局异常向上抛出，由调用方决定重试策略
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import date, datetime, timedelta
from itertools import cycle

import threading

import akshare as ak
import pandas as pd
import requests as _requests
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.stock import StockDailyQuote

logger = logging.getLogger("alphareader.data_fetcher")

# ────────── 配置 ──────────
REQUEST_INTERVAL = 1.5          # 每次请求基础间隔（秒），避免触发反爬
REQUEST_JITTER = 0.8            # 随机抖动上限（秒），实际间隔 = INTERVAL + random(0, JITTER)
LOOKBACK_DAYS = 365             # 回溯天数（约 250 个交易日）
MAX_RETRIES = 3                 # 单只股票最大重试次数
RETRY_DELAY = 3                 # 重试间隔（秒）
_AKSHARE_TIMEOUT = 15           # akshare HTTP 请求默认超时（秒）


# ────────── akshare 请求超时注入 ──────────
# akshare 内部使用 requests 库但不设置 timeout，远端断连时会永久挂起。
# 通过 monkey-patch Session.request（所有 HTTP 方法的底层入口）注入默认超时。
_original_session_request = _requests.Session.request
_timeout_patch_lock = threading.Lock()
_timeout_patched = False


def _patched_session_request(self, method, url, **kwargs):
    kwargs.setdefault("timeout", _AKSHARE_TIMEOUT)
    return _original_session_request(self, method, url, **kwargs)


def _ensure_timeout_patch():
    """确保 requests.Session.request 已被 patch（仅执行一次）。"""
    global _timeout_patched
    if _timeout_patched:
        return
    with _timeout_patch_lock:
        if _timeout_patched:
            return
        _requests.Session.request = _patched_session_request
        _timeout_patched = True
        logger.info("已注入 requests 默认超时: %ds", _AKSHARE_TIMEOUT)

# ETF 代码前缀规则（沪深两市场内 ETF）
# 上交所: 51xxxx / 56xxxx / 58xxxx  深交所: 15xxxx / 16xxxx
ETF_PREFIXES = ("51", "56", "58", "15", "16")


# ────────── 代理 IP 轮换 ──────────
# 环境变量 AKSHARE_PROXIES 配置代理列表，逗号分隔
# 示例: AKSHARE_PROXIES=http://user:pass@proxy1:8080,http://user:pass@proxy2:8080
# 留空或不设置则不使用代理
_PROXY_LIST: list[str] = [
    p.strip() for p in os.environ.get("AKSHARE_PROXIES", "").split(",") if p.strip()
]
_proxy_cycle = cycle(_PROXY_LIST) if _PROXY_LIST else None

def _next_proxy() -> dict[str, str] | None:
    """获取下一个代理地址（轮换），无代理配置时返回 None。"""
    if _proxy_cycle is None:
        return None
    proxy_url = next(_proxy_cycle)
    return {"http": proxy_url, "https": proxy_url}

def _apply_proxy():
    """将代理设置注入到环境变量中，akshare 内部使用 requests 库会自动读取。"""
    proxy = _next_proxy()
    if proxy:
        os.environ["HTTP_PROXY"] = proxy["http"]
        os.environ["HTTPS_PROXY"] = proxy["https"]
        logger.debug("使用代理: %s", proxy["http"])
    else:
        # 无代理时清除，防止残留
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)

def _sleep_with_jitter(base: float = REQUEST_INTERVAL):
    """带随机抖动的休眠，模拟人类行为。"""
    import time
    delay = base + random.uniform(0, REQUEST_JITTER)
    time.sleep(delay)

async def _async_sleep_with_jitter(base: float = REQUEST_INTERVAL):
    """异步版带随机抖动休眠。"""
    delay = base + random.uniform(0, REQUEST_JITTER)
    await asyncio.sleep(delay)


# ============================================================
# 1. 获取 A 股股票列表（同步，在线程池中执行）
# ============================================================

def _sync_fetch_stock_list() -> pd.DataFrame:
    """获取当前 A 股所有股票的代码和名称。"""
    _apply_proxy()
    df = ak.stock_zh_a_spot_em()
    df = df[["代码", "名称"]].copy()
    df.reset_index(drop=True, inplace=True)
    return df


async def fetch_stock_list() -> pd.DataFrame:
    """异步包装：在线程池中获取 A 股股票列表。"""
    logger.info("正在获取 A 股股票列表...")
    df = await asyncio.to_thread(_sync_fetch_stock_list)
    logger.info("共获取到 %d 只股票", len(df))
    return df


# ============================================================
# 2. 获取单只股票历史行情（同步，在线程池中执行）
# ============================================================

def _sync_fetch_single_stock_hist(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
    """获取单只股票的前复权日线数据，自带重试机制。"""
    _ensure_timeout_patch()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _apply_proxy()
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                df["股票代码"] = symbol
                return df
            return None
        except KeyError:
            return None
        except Exception as e:
            if attempt < MAX_RETRIES:
                _sleep_with_jitter(RETRY_DELAY)
            else:
                logger.warning("%s 经 %d 次重试仍失败: %s", symbol, MAX_RETRIES, e)
                return None
    return None


# ============================================================
# 3. 批量获取所有股票历史行情
# ============================================================

async def fetch_all_stocks_hist(stock_list: pd.DataFrame) -> pd.DataFrame:
    """遍历股票列表，逐只获取前复权日线数据（在线程池中串行执行，间隔防反爬）。"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")

    codes = stock_list["代码"].tolist()
    names = dict(zip(stock_list["代码"], stock_list["名称"]))
    total = len(codes)

    logger.info("开始下载历史行情 (%s ~ %s)，共 %d 只股票...", start_date, end_date, total)

    all_dfs: list[pd.DataFrame] = []
    for idx, code in enumerate(codes, 1):
        if idx % 200 == 0:
            logger.info("下载进度: %d/%d (%.1f%%)", idx, total, idx / total * 100)

        df = await asyncio.to_thread(
            _sync_fetch_single_stock_hist, code, start_date, end_date
        )
        if df is not None:
            df["名称"] = names.get(code, "")
            all_dfs.append(df)
        await _async_sleep_with_jitter()

    if not all_dfs:
        logger.error("未获取到任何股票数据")
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    logger.info(
        "合并完成，共 %d 条记录，涉及 %d 只股票",
        len(combined),
        combined["股票代码"].nunique(),
    )
    return combined


# ============================================================
# 4. 数据清洗
# ============================================================

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """清洗原始行情数据：剔除停牌（成交量==0）、去重、排序。"""
    if df.empty:
        return df

    before = len(df)

    vol_col = "成交量"
    if vol_col in df.columns:
        df = df[df[vol_col] > 0].copy()

    df.drop_duplicates(inplace=True)
    df.sort_values(by=["股票代码", "日期"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    after = len(df)
    logger.info("数据清洗完成：%d → %d 条（剔除 %d 条停牌/重复记录）", before, after, before - after)
    return df


# ============================================================
# 5. 持久化到 PostgreSQL（替代 SQLite）
# ============================================================

def _df_to_records(df: pd.DataFrame) -> list[dict]:
    """将 akshare DataFrame 转换为 ORM 兼容的 dict 列表。"""
    records = []
    col_map = {
        "股票代码": "ts_code",
        "名称": "name",
        "日期": "trade_date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "换手率": "turnover",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
    }
    for _, row in df.iterrows():
        rec = {"market": "CN"}  # 显式标记为 A 股市场
        for cn_col, en_col in col_map.items():
            if cn_col in df.columns:
                val = row[cn_col]
                if en_col == "trade_date":
                    val = pd.to_datetime(val).date()
                elif pd.isna(val):
                    val = None
                rec[en_col] = val
        records.append(rec)
    return records


async def save_to_db(df: pd.DataFrame) -> int:
    """将 DataFrame 批量 upsert 到 PostgreSQL stock_daily_quote 表。

    Returns:
        写入/更新的记录数。
    """
    records = _df_to_records(df)
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
                    # 防止空 name 覆盖已有的非空 name
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
                    "turnover": stmt.excluded.turnover,
                    "amplitude": stmt.excluded.amplitude,
                    "pct_change": stmt.excluded.pct_change,
                    "change": stmt.excluded.change,
                },
            )
            await session.execute(stmt)
            total_written += len(batch)
        await session.commit()

    logger.info("数据已写入 PostgreSQL，共 %d 条记录", total_written)
    return total_written


async def load_from_db(min_date: date | None = None) -> pd.DataFrame:
    """从 PostgreSQL 加载 A 股行情数据。

    Args:
        min_date: 最早日期，默认回溯 LOOKBACK_DAYS。

    Returns:
        包含行情数据的 DataFrame（列名为中文，与 akshare 原始格式一致）。
    """
    if min_date is None:
        min_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date()

    async with async_session() as session:
        result = await session.execute(
            select(StockDailyQuote)
            .where(StockDailyQuote.market == "CN")
            .where(StockDailyQuote.trade_date >= min_date)
            .order_by(StockDailyQuote.ts_code, StockDailyQuote.trade_date)
        )
        rows = result.scalars().all()

    if not rows:
        return pd.DataFrame()

    col_map = {
        "ts_code": "股票代码",
        "name": "名称",
        "trade_date": "日期",
        "open": "开盘",
        "close": "收盘",
        "high": "最高",
        "low": "最低",
        "volume": "成交量",
        "amount": "成交额",
        "turnover": "换手率",
        "amplitude": "振幅",
        "pct_change": "涨跌幅",
        "change": "涨跌额",
    }
    data = []
    for r in rows:
        data.append({cn: getattr(r, en) for en, cn in col_map.items()})

    df = pd.DataFrame(data)
    logger.info("从 PostgreSQL 加载 %d 条记录（>= %s）", len(df), min_date)
    return df


async def has_today_data(min_stocks: int = 5000) -> bool:
    """检查是否已有最新交易日的 A 股行情数据（足够多的股票）。

    逻辑：
      - 使用**北京时间**判断"今天"，因为容器可能运行在 UTC 时区，
        而 A 股定时任务按 Asia/Shanghai 配置。
      - 在北京时间收盘后（15:00+），必须有**当天**的数据才算就绪；
      - 在收盘前或非交易日，DB 最新是前一个交易日即可。
    """
    from zoneinfo import ZoneInfo

    cst_now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today_cst = cst_now.date()
    is_weekday = today_cst.weekday() < 5  # 周一~周五
    after_close = cst_now.hour >= 15  # 15:00 后 A 股已收盘

    async with async_session() as session:
        # 获取 DB 中最新的 A 股交易日期
        max_date_result = await session.execute(
            select(func.max(StockDailyQuote.trade_date))
            .where(StockDailyQuote.market == "CN")
        )
        max_date = max_date_result.scalar()
        if max_date is None:
            logger.info("has_today_data: 数据库无 A 股行情数据")
            return False

        gap_days = (today_cst - max_date).days

        # 检查最新日期有多少只 A 股
        count_result = await session.execute(
            select(func.count(func.distinct(StockDailyQuote.ts_code)))
            .where(StockDailyQuote.trade_date == max_date)
            .where(StockDailyQuote.market == "CN")
        )
        stock_count = count_result.scalar() or 0

    # 如果是工作日且已收盘，必须有今天的数据才算就绪
    if is_weekday and after_close:
        is_ready = max_date >= today_cst and stock_count >= min_stocks
        logger.info(
            "has_today_data: 收盘后检查 | DB最新=%s, 今天(CST)=%s, 该日%d只A股 → %s（需 max_date>=今天 且 stocks>=%d）",
            max_date, today_cst, stock_count, "跳过" if is_ready else "需更新", min_stocks,
        )
        return is_ready

    # 非交易时段（周末/假期/盘前）：DB 最新距今 ≤ 1 天即可
    is_ready = gap_days <= 1 and stock_count >= min_stocks
    logger.info(
        "has_today_data: 非收盘时段 | DB最新=%s, 今天(CST)=%s, gap=%d天, 该日%d只A股 → %s（阈值: gap<=1 且 stocks>=%d）",
        max_date, today_cst, gap_days, stock_count, "跳过" if is_ready else "需更新", min_stocks,
    )
    return is_ready


# ============================================================
# 6. 主入口（异步）
# ============================================================

async def get_all_stock_data(force_refresh: bool = False) -> pd.DataFrame:
    """获取全部 A 股过去一年前复权日线数据（异步主入口）。

    流程：
      1. 检查 PostgreSQL 是否已有当天数据
      2. 若有效则直接从数据库加载返回
      3. 否则优先使用腾讯财经 API 在线获取（速度快、稳定）
      4. 腾讯失败则降级到 akshare
      5. 清洗 → 写入 PostgreSQL → 返回

    Args:
        force_refresh: 为 True 时强制重新计算 RS Rating，但仍优先使用 DB 已有行情数据。
                       只有当 DB 行情数据不足时才重新下载。

    Returns:
        清洗后的完整 DataFrame。
    """
    # force_refresh 也优先检查 DB：只要有足够的行情数据就直接用，避免重复下载
    if await has_today_data():
        logger.info("当天数据已存在，从 PostgreSQL 加载（force_refresh=%s）", force_refresh)
        return await load_from_db()

    if not force_refresh:
        # 非强制模式：检查是否有近期数据（可能不是今天，但足够计算）
        db_data = await load_from_db()
        if not db_data.empty and db_data["股票代码"].nunique() >= 100:
            logger.info("数据库已有 %d 只股票的行情数据，直接使用",
                        db_data["股票代码"].nunique())
            return db_data

    # 方式 1（优先）：腾讯财经 API — 速度更快、更稳定
    raw_data = pd.DataFrame()
    try:
        db_list = await fetch_stock_list_from_db()
        if not db_list.empty:
            codes = db_list["代码"].tolist()
            names = dict(zip(db_list["代码"], db_list["名称"]))
            # 分批拉取并写入 DB（内存友好）
            await fetch_all_stocks_tencent(codes, names)
            # 数据已写入 DB，从数据库加载
            raw_data = await load_from_db()
            if not raw_data.empty:
                stock_count = (
                    raw_data["股票代码"].nunique() if "股票代码" in raw_data.columns
                    else raw_data["ts_code"].nunique() if "ts_code" in raw_data.columns
                    else 0
                )
                logger.info("腾讯财经 API 数据已写入 DB 并加载，共 %d 只股票", stock_count)
                return raw_data  # 已经是 clean 过的数据，直接返回
    except Exception as e:
        logger.warning("腾讯财经 API 获取行情失败: %s", e)

    # 方式 2（备选）：akshare（当腾讯 API 完全失败或数据过少时）
    if raw_data.empty or (
        "股票代码" in raw_data.columns and raw_data["股票代码"].nunique() < 100
    ):
        logger.info("腾讯财经数据不足（%d 只），尝试 akshare...",
                     raw_data["股票代码"].nunique() if not raw_data.empty and "股票代码" in raw_data.columns else 0)
        try:
            stock_list = await fetch_stock_list()
            raw_data = await fetch_all_stocks_hist(stock_list)
        except Exception as e:
            logger.warning("akshare 也失败: %s", e)

    clean = clean_data(raw_data)

    if not clean.empty:
        await save_to_db(clean)

    return clean


# ============================================================
# 7. ETF 行情获取（补充 stock_daily_quote 中 ETF 数据）
# ============================================================

def is_etf(ts_code: str) -> bool:
    """判断代码是否为场内 ETF。"""
    return ts_code[:2] in ETF_PREFIXES


def _sync_fetch_single_etf_hist(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
    """获取单只 ETF 的前复权日线数据，自带重试机制。"""
    _ensure_timeout_patch()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _apply_proxy()
            df = ak.fund_etf_hist_em(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                df["股票代码"] = symbol
                return df
            return None
        except KeyError:
            return None
        except Exception as e:
            if attempt < MAX_RETRIES:
                _sleep_with_jitter(RETRY_DELAY)
            else:
                logger.warning("ETF %s 经 %d 次重试仍失败: %s", symbol, MAX_RETRIES, e)
                return None
    return None


async def fetch_etf_hist(
    etf_codes: list[str],
    lookback_days: int = 30,
) -> pd.DataFrame:
    """批量获取 ETF 历史行情并写入 stock_daily_quote 表。

    Args:
        etf_codes: ETF 代码列表（如 ['512170', '159915']）
        lookback_days: 回溯天数，默认 30 天（ETF 只需近期数据即可）

    Returns:
        合并后的 DataFrame（已写入 DB）
    """
    if not etf_codes:
        return pd.DataFrame()

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")

    logger.info("开始下载 ETF 行情 (%s ~ %s)，共 %d 只: %s", start_date, end_date, len(etf_codes), etf_codes)

    all_dfs: list[pd.DataFrame] = []
    for code in etf_codes:
        df = await asyncio.to_thread(
            _sync_fetch_single_etf_hist, code, start_date, end_date
        )
        if df is not None:
            # fund_etf_hist_em 列名与 stock_zh_a_hist 一致，直接复用 _df_to_records
            all_dfs.append(df)
        await _async_sleep_with_jitter()

    if not all_dfs:
        logger.warning("未获取到任何 ETF 数据")
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = clean_data(combined)

    if not combined.empty:
        await save_to_db(combined)
        logger.info("ETF 行情已写入 DB，共 %d 条记录", len(combined))

    return combined


async def fetch_sandbox_etf_quotes() -> int:
    """从观察池中找出所有 ETF 标的，获取其最新行情并写入 DB。

    Returns:
        更新的 ETF 行情记录数
    """
    from app.models.sandbox import SandboxStock

    async with async_session() as session:
        result = await session.execute(
            select(SandboxStock.ts_code).where(
                SandboxStock.status.in_(["watching", "holding"])
            )
        )
        all_codes = [row[0] for row in result.all()]

    etf_codes = [c for c in all_codes if is_etf(c)]

    if not etf_codes:
        logger.info("观察池中无 ETF 标的，跳过")
        return 0

    df = await fetch_etf_hist(etf_codes, lookback_days=30)
    return len(df)


# ============================================================
# 7.5 新浪财经 HTTP 行情（不依赖 akshare，作为 NAV 计算的可靠备选）
# ============================================================

# ── 腾讯财经代码格式转换 ──

def _tencent_code(code: str) -> str:
    """将纯数字代码转为腾讯财经格式：sh600000 / sz000001。"""
    if code.startswith(("6", "5")):
        return f"sh{code}"
    return f"sz{code}"


def _sync_fetch_tencent_kline(symbol: str, days: int = 320) -> pd.DataFrame | None:
    """通过腾讯财经 API 获取单只股票的前复权日K线数据。

    API: http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq
    返回: [日期, 开盘, 收盘, 最高, 最低, 成交量]
    """
    import json
    import urllib.request

    tc_code = _tencent_code(symbol)
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
            return None

        rows = []
        for item in kline:
            # [日期, 开盘, 收盘, 最高, 最低, 成交量]
            if len(item) >= 6:
                rows.append({
                    "日期": item[0],
                    "开盘": float(item[1]),
                    "收盘": float(item[2]),
                    "最高": float(item[3]),
                    "最低": float(item[4]),
                    "成交量": float(item[5]),
                    "股票代码": symbol,
                })

        if not rows:
            return None

        df = pd.DataFrame(rows)
        # 计算涨跌额和涨跌幅
        df.sort_values("日期", inplace=True)
        df["涨跌额"] = df["收盘"].diff()
        df["涨跌幅"] = df["收盘"].pct_change() * 100
        df["成交额"] = 0.0  # 腾讯 API 不提供成交额
        df["换手率"] = None
        df["振幅"] = None
        return df

    except Exception as e:
        logger.debug("腾讯K线 %s 失败: %s", symbol, e)
        return None


async def fetch_all_stocks_tencent(stock_codes: list[str], stock_names: dict[str, str] | None = None) -> pd.DataFrame:
    """通过腾讯财经 API 批量获取日K线数据（作为 akshare 备选）。

    采用分批拉取 + 分批写入 DB 策略，避免在小内存服务器上 OOM。
    每 BATCH_SIZE 只股票写入一次 DB 后释放内存。

    Args:
        stock_codes: 股票代码列表
        stock_names: 可选，{代码: 名称} 映射

    Returns:
        空 DataFrame（数据已分批写入 DB），调用方应使用 load_from_db() 读取
    """
    import gc

    if stock_names is None:
        stock_names = {}

    BATCH_SIZE = 200  # 每批处理 200 只，约占 ~200MB 内存
    total = len(stock_codes)
    total_records = 0
    total_stocks = 0

    logger.info("开始通过腾讯财经 API 下载历史行情，共 %d 只股票（每 %d 只分批写入 DB）...",
                total, BATCH_SIZE)

    batch_dfs: list[pd.DataFrame] = []
    for idx, code in enumerate(stock_codes, 1):
        if idx % 200 == 0:
            logger.info("腾讯K线下载进度: %d/%d (%.1f%%)", idx, total, idx / total * 100)

        df = await asyncio.to_thread(_sync_fetch_tencent_kline, code, 320)
        if df is not None:
            df["名称"] = stock_names.get(code, "")
            batch_dfs.append(df)

        # 每 BATCH_SIZE 只写入一次 DB 并释放内存
        if len(batch_dfs) >= BATCH_SIZE:
            batch_combined = pd.concat(batch_dfs, ignore_index=True)
            batch_clean = clean_data(batch_combined)
            if not batch_clean.empty:
                await save_to_db(batch_clean)
                total_records += len(batch_clean)
                total_stocks += batch_clean["股票代码"].nunique()
                logger.info("腾讯K线批次写入 DB: +%d 条（累计 %d 条，%d 只）",
                            len(batch_clean), total_records, total_stocks)
            # 释放内存
            del batch_dfs, batch_combined, batch_clean
            batch_dfs = []
            gc.collect()

        # 腾讯 API 较宽松，间隔可短一些
        await asyncio.sleep(0.3 + random.uniform(0, 0.2))

    # 处理最后一批
    if batch_dfs:
        batch_combined = pd.concat(batch_dfs, ignore_index=True)
        batch_clean = clean_data(batch_combined)
        if not batch_clean.empty:
            await save_to_db(batch_clean)
            total_records += len(batch_clean)
            total_stocks += batch_clean["股票代码"].nunique()
        del batch_dfs, batch_combined, batch_clean
        gc.collect()

    if total_records == 0:
        logger.error("腾讯财经 API 未获取到任何股票数据")
        return pd.DataFrame()

    logger.info("腾讯K线全部完成，共 %d 条记录，涉及 %d 只股票（已分批写入 DB）",
                total_records, total_stocks)

    # 返回空 DataFrame — 数据已在 DB 中，调用方会 load_from_db()
    return pd.DataFrame(columns=["股票代码"])


# ============================================================
# 7.4 增量行情更新（只拉最近几天，快速补齐新交易日数据）
# ============================================================

async def incremental_update_quotes(days: int = 10) -> int:
    """增量更新行情数据：只拉最近 N 天的 K 线，快速补齐新交易日。

    与全量拉取（320天 × 5000+只，耗时 ~50 分钟）不同，
    增量只拉最近 10 天，耗时 ~10 分钟，内存 <200MB。

    Args:
        days: 回溯天数，默认 10（覆盖长假后的补数据场景）

    Returns:
        新增/更新的记录数
    """
    import gc

    # 先检查是否已有今天的数据
    if await has_today_data():
        logger.info("增量更新跳过：今天的行情数据已存在")
        return 0

    # 从 DB 获取股票列表
    db_list = await fetch_stock_list_from_db()
    if db_list.empty:
        logger.warning("增量更新失败：数据库中无股票列表")
        return 0

    codes = db_list["代码"].tolist()
    names = dict(zip(db_list["代码"], db_list["名称"]))
    total = len(codes)

    logger.info("开始增量更新行情（最近 %d 天），共 %d 只股票...", days, total)

    BATCH_SIZE = 500  # 增量数据量小，可以用更大的批次
    total_records = 0
    batch_dfs: list[pd.DataFrame] = []

    for idx, code in enumerate(codes, 1):
        if idx % 500 == 0:
            logger.info("增量更新进度: %d/%d (%.1f%%)", idx, total, idx / total * 100)

        df = await asyncio.to_thread(_sync_fetch_tencent_kline, code, days)
        if df is not None:
            df["名称"] = names.get(code, "")
            batch_dfs.append(df)

        # 分批写入 DB
        if len(batch_dfs) >= BATCH_SIZE:
            batch_combined = pd.concat(batch_dfs, ignore_index=True)
            batch_clean = clean_data(batch_combined)
            if not batch_clean.empty:
                await save_to_db(batch_clean)
                total_records += len(batch_clean)
            del batch_dfs, batch_combined, batch_clean
            batch_dfs = []
            gc.collect()

        # 增量拉取间隔更短（数据量小）
        await asyncio.sleep(0.15 + random.uniform(0, 0.1))

    # 最后一批
    if batch_dfs:
        batch_combined = pd.concat(batch_dfs, ignore_index=True)
        batch_clean = clean_data(batch_combined)
        if not batch_clean.empty:
            await save_to_db(batch_clean)
            total_records += len(batch_clean)
        del batch_dfs, batch_combined, batch_clean
        gc.collect()

    logger.info("增量更新完成，共 %d 条记录（%d 只股票）", total_records, total)
    return total_records


def _sync_fetch_stock_list_tencent() -> pd.DataFrame:
    """通过新浪财经获取 A 股股票列表（作为 akshare stock_zh_a_spot_em 的备选）。

    新浪 hq.sinajs.cn 不适合拿列表，改用腾讯每日行情接口获取。
    但腾讯也没有直接的列表接口，所以从数据库已有股票中提取。
    """
    return pd.DataFrame()  # 占位，实际使用数据库已有代码


async def fetch_stock_list_from_db() -> pd.DataFrame:
    """从数据库中获取已有的 A 股代码列表（当在线接口不可用时的备选）。

    优先取非空 name，避免返回空名称导致增量更新时覆盖已有名称。
    """
    from sqlalchemy import text as sa_text

    # 使用 DISTINCT ON + ORDER BY 优先取 name 非空的行（仅 A 股）
    sql = sa_text("""
        SELECT DISTINCT ON (ts_code) ts_code, name
        FROM stock_daily_quote
        WHERE market = 'CN'
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
    logger.info("从数据库获取到 %d 只股票代码", len(df))
    return df

def _sina_code(code: str) -> str:
    """将纯数字代码转为新浪财经格式：sh600000 / sz000001 / sh510300。"""
    if code.startswith(("6", "5")):
        return f"sh{code}"
    return f"sz{code}"


def _sync_fetch_sina_prices(codes: list[str]) -> dict[str, float]:
    """通过新浪财经 HTTP 接口获取最新价格（不复权），返回 {代码: 价格}。

    接口: https://hq.sinajs.cn/list=sh600000,sz000001,...
    返回格式: var hq_str_sh600000="...,当前价,...";
    """
    import re
    import urllib.request

    if not codes:
        return {}

    sina_codes = [_sina_code(c) for c in codes]
    url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"

    req = urllib.request.Request(url, headers={
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("gbk")
    except Exception as e:
        logger.warning("新浪行情 HTTP 请求失败: %s", e)
        return {}

    prices: dict[str, float] = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or '="' not in line:
            continue
        # var hq_str_sh600000="name,open,昨收,当前价,..."
        m = re.match(r'var hq_str_(s[hz]\d{6})="(.+)"', line)
        if not m:
            continue
        sina_sym = m.group(1)
        fields = m.group(2).split(",")
        # 字段索引：[0]名称 [1]今开 [2]昨收 [3]当前价 ...
        if len(fields) >= 4:
            try:
                current_price = float(fields[3])
                if current_price > 0:
                    # 反查原始代码
                    raw_code = sina_sym[2:]  # 去掉 sh/sz 前缀
                    prices[raw_code] = current_price
            except (ValueError, IndexError):
                pass

    return prices


async def get_sina_prices(codes: list[str]) -> dict[str, float]:
    """异步获取新浪财经实时价格。"""
    return await asyncio.to_thread(_sync_fetch_sina_prices, codes)


# ============================================================
# 8. 实时行情（不复权）— 供 NAV 计算使用
# ============================================================

_spot_cache: dict[str, float] = {}   # 短期缓存：{ts_code: latest_price}
_spot_cache_ts: float = 0.0          # 缓存时间戳


def _sync_fetch_tencent_spot_prices(codes: list[str]) -> dict[str, float]:
    """通过腾讯财经 HTTP 接口批量获取实时行情（不复权最新价）。

    接口: http://qt.gtimg.cn/q=sh600000,sz000001,...
    返回格式: v_sh600000="1~贵州茅台~600519~...~当前价~..."
    每次最多约 80 个代码，分批请求。

    Returns: {纯数字代码: 最新价}
    """
    import urllib.request

    if not codes:
        return {}

    prices: dict[str, float] = {}
    BATCH = 80  # 腾讯单次请求上限

    tc_codes_map: dict[str, str] = {}  # tc_code -> raw_code
    for c in codes:
        tc = _tencent_code(c)
        tc_codes_map[tc] = c

    tc_list = list(tc_codes_map.keys())

    for i in range(0, len(tc_list), BATCH):
        batch = tc_list[i:i + BATCH]
        url = f"http://qt.gtimg.cn/q={','.join(batch)}"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.qq.com",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("gbk", errors="replace")

            for line in text.strip().split("\n"):
                line = line.strip().rstrip(";")
                if not line or '="' not in line:
                    continue
                # v_sh600000="1~贵州茅台~600519~当前价~..."
                eq_pos = line.index("=")
                var_name = line[:eq_pos].replace("v_", "")  # sh600000
                fields_str = line[eq_pos + 2:]  # 去掉 ="
                if fields_str.endswith('"'):
                    fields_str = fields_str[:-1]
                fields = fields_str.split("~")
                # 字段[3] = 当前价
                if len(fields) >= 4 and var_name in tc_codes_map:
                    try:
                        price = float(fields[3])
                        if price > 0:
                            prices[tc_codes_map[var_name]] = price
                    except (ValueError, IndexError):
                        pass
        except Exception as e:
            logger.debug("腾讯实时行情批次请求失败: %s", e)
            continue

    return prices


def _sync_fetch_spot_prices() -> dict[str, float]:
    """同步获取 A 股 + ETF 实时行情（不复权最新价），返回 {代码: 最新价}。"""
    prices: dict[str, float] = {}

    # A 股实时行情
    try:
        _apply_proxy()
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                price = row.get("最新价")
                if code and price is not None and float(price) > 0:
                    prices[code] = float(price)
    except Exception as e:
        logger.warning("获取 A 股实时行情失败: %s", e)

    _sleep_with_jitter(0.5)

    # ETF 实时行情
    try:
        _apply_proxy()
        df = ak.fund_etf_spot_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                price = row.get("最新价")
                if code and price is not None and float(price) > 0:
                    prices[code] = float(price)
    except Exception as e:
        logger.warning("获取 ETF 实时行情失败: %s", e)

    return prices


def _sync_fetch_unadjusted_close(code: str) -> float | None:
    """获取单只股票/ETF 的最新不复权收盘价。

    用 adjust="" (不复权) 获取最近 5 个交易日数据，取最新一条的收盘价。
    仅在实时行情拉取失败时作为 fallback 使用。
    """
    from datetime import datetime as dt, timedelta as td

    end_date = dt.now().strftime("%Y%m%d")
    start_date = (dt.now() - td(days=10)).strftime("%Y%m%d")

    for attempt in range(1, 3):
        try:
            _apply_proxy()
            if is_etf(code):
                df = ak.fund_etf_hist_em(
                    symbol=code, period="daily",
                    start_date=start_date, end_date=end_date,
                    adjust="",
                )
            else:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=start_date, end_date=end_date,
                    adjust="",
                )
            if df is not None and not df.empty:
                close = df.iloc[-1].get("收盘")
                if close is not None and float(close) > 0:
                    return float(close)
            return None
        except Exception as e:
            if attempt < 2:
                _sleep_with_jitter(1.0)
            else:
                logger.warning("获取 %s 不复权收盘价失败: %s", code, e)
                return None
    return None


async def get_unadjusted_close(codes: list[str]) -> dict[str, float]:
    """批量获取不复权收盘价（逐只获取，仅对少量持仓使用）。"""
    result: dict[str, float] = {}
    for code in codes:
        price = await asyncio.to_thread(_sync_fetch_unadjusted_close, code)
        if price is not None:
            result[code] = price
        await _async_sleep_with_jitter(0.5)
    return result


async def get_realtime_prices(codes: list[str], timeout: float = 30.0) -> dict[str, float]:
    """获取指定代码列表的实时不复权价格。

    优先使用腾讯财经 HTTP 接口（轻量、快速），失败后 fallback 到 akshare。
    使用短期缓存（5 分钟），避免频繁调用。

    Args:
        codes: 股票/ETF 代码列表
        timeout: 超时秒数（默认 30s）
    Returns: {ts_code: latest_price}
    """
    import time

    global _spot_cache, _spot_cache_ts

    now = time.time()
    # 缓存有效期 5 分钟
    if _spot_cache and (now - _spot_cache_ts) < 300:
        result = {c: _spot_cache[c] for c in codes if c in _spot_cache}
        if len(result) == len(codes):
            return result

    # 方式 1（优先）：腾讯财经实时行情 — 轻量、不依赖 akshare
    try:
        tencent_prices = await asyncio.wait_for(
            asyncio.to_thread(_sync_fetch_tencent_spot_prices, codes),
            timeout=timeout,
        )
        if tencent_prices:
            _spot_cache.update(tencent_prices)
            _spot_cache_ts = now
            logger.info("腾讯实时行情已刷新，共 %d 只标的", len(tencent_prices))
            result = {c: _spot_cache[c] for c in codes if c in _spot_cache}
            if len(result) == len(codes):
                return result
            # 部分代码未覆盖，继续 fallback
            missing = [c for c in codes if c not in _spot_cache]
            logger.info("腾讯实时行情缺少 %d 只，尝试 akshare 补充", len(missing))
    except asyncio.TimeoutError:
        logger.warning("腾讯实时行情超时 (%.0fs)，尝试 akshare", timeout)
    except Exception as e:
        logger.warning("腾讯实时行情异常: %s，尝试 akshare", e)

    # 方式 2（备选）：akshare 全量实时行情
    try:
        akshare_prices = await asyncio.wait_for(
            asyncio.to_thread(_sync_fetch_spot_prices),
            timeout=timeout,
        )
        _spot_cache.update(akshare_prices)
        _spot_cache_ts = now
        logger.info("akshare 实时行情已刷新，共 %d 只标的", len(akshare_prices))
    except asyncio.TimeoutError:
        logger.warning("akshare 实时行情拉取超时 (%.0fs)，使用缓存或跳过", timeout)
    except Exception as e:
        logger.warning("akshare 实时行情拉取异常: %s", e)

    return {c: _spot_cache[c] for c in codes if c in _spot_cache}


# ============================================================
# 9. 历史行情回填（指定日期范围）
# ============================================================

async def backfill_quotes(
    start_date: str,
    end_date: str,
    batch_size: int = 200,
) -> dict:
    """回填指定日期范围的历史行情数据。

    优先使用腾讯财经 API（更快），失败的个股再用 akshare 补充。
    逐只股票拉取指定日期范围的前复权日线，分批写入 DB。
    服务器内存有限，采用分批写入策略。

    Args:
        start_date: 起始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD
        batch_size: 每批写入 DB 的股票数量

    Returns:
        {"total_stocks": N, "total_records": N, "failed": N}
    """
    import gc

    # 计算回溯天数（腾讯 API 需要天数参数）
    from datetime import datetime as _dt
    try:
        d_start = _dt.strptime(start_date, "%Y%m%d")
        d_end = _dt.strptime(end_date, "%Y%m%d")
        backfill_days = max((d_end - d_start).days + 30, 60)  # 多拉 30 天确保覆盖
    except ValueError:
        backfill_days = 365

    # 获取股票列表
    db_list = await fetch_stock_list_from_db()
    if db_list.empty:
        # 数据库无列表，在线获取
        try:
            db_list = await fetch_stock_list()
        except Exception as e:
            logger.error("获取股票列表失败: %s", e)
            return {"total_stocks": 0, "total_records": 0, "failed": 0}

    codes = db_list["代码"].tolist()
    names = dict(zip(db_list["代码"], db_list["名称"]))
    total = len(codes)

    logger.info(
        "开始回填历史行情: %s ~ %s，共 %d 只股票（优先腾讯财经 API）",
        start_date, end_date, total,
    )

    total_records = 0
    total_stocks = 0
    failed = 0
    batch_dfs: list[pd.DataFrame] = []

    for idx, code in enumerate(codes, 1):
        if idx % 200 == 0:
            logger.info(
                "历史行情回填进度: %d/%d (%.1f%%)，已写入 %d 条",
                idx, total, idx / total * 100, total_records,
            )

        # 优先腾讯财经 API
        df = await asyncio.to_thread(_sync_fetch_tencent_kline, code, backfill_days)
        if df is not None and not df.empty:
            df["名称"] = names.get(code, "")
            batch_dfs.append(df)
        else:
            # 腾讯失败则 fallback 到 akshare
            df = await asyncio.to_thread(
                _sync_fetch_single_stock_hist, code, start_date, end_date
            )
            if df is not None and not df.empty:
                df["名称"] = names.get(code, "")
                batch_dfs.append(df)
            else:
                failed += 1

        # 分批写入 DB
        if len(batch_dfs) >= batch_size:
            batch_combined = pd.concat(batch_dfs, ignore_index=True)
            batch_clean = clean_data(batch_combined)
            if not batch_clean.empty:
                await save_to_db(batch_clean)
                total_records += len(batch_clean)
                total_stocks += batch_clean["股票代码"].nunique()
            del batch_dfs, batch_combined, batch_clean
            batch_dfs = []
            gc.collect()

        await asyncio.sleep(0.3 + random.uniform(0, 0.2))  # 腾讯 API 间隔更短

    # 最后一批
    if batch_dfs:
        batch_combined = pd.concat(batch_dfs, ignore_index=True)
        batch_clean = clean_data(batch_combined)
        if not batch_clean.empty:
            await save_to_db(batch_clean)
            total_records += len(batch_clean)
            total_stocks += batch_clean["股票代码"].nunique()
        del batch_dfs, batch_combined, batch_clean
        gc.collect()

    result = {
        "total_stocks": total_stocks,
        "total_records": total_records,
        "failed": failed,
    }
    logger.info("历史行情回填完成: %s", result)
    return result


# ============================================================
# 直接运行入口（开发调试用）
# ============================================================

if __name__ == "__main__":
    import asyncio as _asyncio

    async def _main():
        df = await get_all_stock_data()
        if not df.empty:
            print("\n===== 数据预览 =====")
            print(df.head(10))
            print(f"\n股票数量: {df['股票代码'].nunique()}")
            print(f"记录总数: {len(df)}")
            print(f"日期范围: {df['日期'].min()} ~ {df['日期'].max()}")
        else:
            print("[ERROR] 未获取到有效数据。")

    _asyncio.run(_main())
