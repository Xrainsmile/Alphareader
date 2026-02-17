"""Alphareader — A 股数据获取模块（异步版）。

职责：
  - 从 akshare 获取 A 股股票列表和前复权日线行情
  - 数据清洗（剔除停牌、去重）
  - 持久化到 PostgreSQL（stock_daily_quote 表）
  - 智能缓存：当天已有数据则跳过下载

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
from datetime import date, datetime, timedelta

import akshare as ak
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.stock import StockDailyQuote

logger = logging.getLogger("alphareader.data_fetcher")

# ────────── 配置 ──────────
REQUEST_INTERVAL = 0.1          # 每次请求间隔（秒），防触发反爬
LOOKBACK_DAYS = 365             # 回溯天数（约 250 个交易日）
MAX_RETRIES = 3                 # 单只股票最大重试次数
RETRY_DELAY = 2                 # 重试间隔（秒）


# ============================================================
# 1. 获取 A 股股票列表（同步，在线程池中执行）
# ============================================================

def _sync_fetch_stock_list() -> pd.DataFrame:
    """获取当前 A 股所有股票的代码和名称。"""
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
    import time

    for attempt in range(1, MAX_RETRIES + 1):
        try:
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
                time.sleep(RETRY_DELAY)
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
        await asyncio.sleep(REQUEST_INTERVAL)

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
        rec = {}
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
                    "name": stmt.excluded.name,
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
    """从 PostgreSQL 加载行情数据。

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


async def has_today_data() -> bool:
    """检查今天是否已有缓存数据。"""
    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(StockDailyQuote)
            .where(StockDailyQuote.trade_date == today)
        )
        count = result.scalar() or 0
    return count > 0


# ============================================================
# 6. 主入口（异步）
# ============================================================

async def get_all_stock_data(force_refresh: bool = False) -> pd.DataFrame:
    """获取全部 A 股过去一年前复权日线数据（异步主入口）。

    流程：
      1. 检查 PostgreSQL 是否已有当天数据
      2. 若有效则直接从数据库加载返回
      3. 否则在线获取 → 清洗 → 写入 PostgreSQL → 返回

    Args:
        force_refresh: 为 True 时强制重新下载，忽略缓存。

    Returns:
        清洗后的完整 DataFrame。
    """
    if not force_refresh:
        if await has_today_data():
            logger.info("当天数据已存在，从 PostgreSQL 加载")
            return await load_from_db()

    stock_list = await fetch_stock_list()
    raw_data = await fetch_all_stocks_hist(stock_list)
    clean = clean_data(raw_data)

    if not clean.empty:
        await save_to_db(clean)

    return clean


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
