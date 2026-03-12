"""数据加载器 — 从 PostgreSQL / EMA 快照 / akshare 加载量价与基本面数据。

职责：
  1. 从 stock_daily_quote 表加载近 N 日全市场 OHLCV 行情
  2. 从本地 Parquet 快照加载最新 EMA 数据
  3. 增量更新 EMA（用今日收盘价 + 昨日 EMA 计算今日 EMA）
  4. 从 akshare 拉取全市场季度业绩报告（营收/净利润/EPS/现金流）

设计原则：
  - 全部使用 Pandas 向量化运算，5000+ 只股票毫秒级处理
  - akshare 为同步库，通过 asyncio.to_thread() 避免阻塞事件循环
  - 单只股票数据缺失不影响整体（防御性容错）
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select, text

from app.database import async_session

logger = logging.getLogger("alphareader.screener.data_loader")

# ── 项目根目录与 EMA 快照路径 ──
# 向上查找包含 data/ema_snapshots 的目录，兼容本地和 Docker 两种路径结构
def _find_project_root() -> Path:
    """从当前文件向上查找包含 data/ 目录的项目根。"""
    cur = Path(__file__).resolve().parent
    for _ in range(6):
        if (cur / "data" / "ema_snapshots").exists():
            return cur
        cur = cur.parent
    # fallback: 按本地结构 parents[4]
    return Path(__file__).resolve().parents[4]

PROJECT_ROOT = _find_project_root()
EMA_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "ema_snapshots"

# ── EMA 周期与乘数 ──
EMA_PERIODS = {
    "EMA5": 5,
    "EMA10": 10,
    "EMA20": 20,
    "EMA50": 50,
    "EMA120": 120,
    "EMA200": 200,
}


class DataLoader:
    """数据加载器：统一管理量价、EMA、基本面数据的获取与更新。

    使用方法：
        loader = DataLoader()
        ohlcv_df = await loader.load_ohlcv(lookback_days=120)
        ema_df = loader.load_latest_ema()
        ema_df = loader.update_ema_incremental(ema_df, today_close_df)
        fundamental_df = await loader.load_fundamentals()
    """

    def __init__(self, ema_dir: str | Path | None = None):
        """初始化数据加载器。

        Args:
            ema_dir: EMA 快照目录路径，默认使用项目内的 data/ema_snapshots/
        """
        self.ema_dir = Path(ema_dir) if ema_dir else EMA_SNAPSHOT_DIR

    # ================================================================
    # 1. 从 PostgreSQL 加载近 N 日全市场 OHLCV 行情
    # ================================================================

    async def load_ohlcv(self, lookback_days: int = 130) -> pd.DataFrame:
        """从 stock_daily_quote 表加载近 N 个自然日的全市场 OHLCV 数据。

        返回 DataFrame 列:
            ts_code, trade_date, open, close, high, low, volume, amount, pct_change

        Args:
            lookback_days: 回溯自然日数（非交易日），默认 130 天
                           覆盖 ~90 个交易日，满足 120 日窗口需求。

        Returns:
            按 (ts_code, trade_date) 排序的 DataFrame
        """
        min_date = date.today() - timedelta(days=lookback_days)

        # 使用原始 SQL 以获得最佳性能（5000+ 只 × 90 天 ≈ 45 万行）
        sql = text("""
            SELECT ts_code, trade_date, open, close, high, low,
                   volume, amount, pct_change
            FROM stock_daily_quote
            WHERE trade_date >= :min_date
            ORDER BY ts_code, trade_date
        """)

        async with async_session() as session:
            result = await session.execute(sql, {"min_date": min_date})
            rows = result.fetchall()

        if not rows:
            logger.error("load_ohlcv: 数据库中无 >= %s 的行情数据", min_date)
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=[
            "ts_code", "trade_date", "open", "close", "high", "low",
            "volume", "amount", "pct_change",
        ])

        # 确保类型正确
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        for col in ["open", "close", "high", "low", "volume", "amount", "pct_change"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info(
            "load_ohlcv: 加载 %d 条记录，%d 只股票，日期范围 %s ~ %s",
            len(df), df["ts_code"].nunique(),
            df["trade_date"].min().date(), df["trade_date"].max().date(),
        )
        return df

    # ================================================================
    # 2. 加载最新 EMA 快照
    # ================================================================

    def load_latest_ema(self) -> pd.DataFrame:
        """从本地 Parquet 目录中加载日期最新的 EMA 快照。

        Returns:
            DataFrame: Code, Date, Close, EMA5, EMA10, EMA20, EMA50, EMA120, EMA200
        """
        pattern = str(self.ema_dir / "ema_snapshot_*.parquet")
        files = sorted(glob.glob(pattern))

        if not files:
            logger.error("load_latest_ema: 未找到 EMA 快照文件于 %s", self.ema_dir)
            return pd.DataFrame()

        latest_file = files[-1]
        df = pd.read_parquet(latest_file)
        snapshot_date = Path(latest_file).stem.split("_")[-1]

        logger.info(
            "load_latest_ema: 加载 %s（%d 只标的，日期 %s）",
            Path(latest_file).name, len(df), snapshot_date,
        )
        return df

    # ================================================================
    # 3. 增量更新 EMA（核心公式）
    # ================================================================

    @staticmethod
    def update_ema_incremental(
        ema_yesterday: pd.DataFrame,
        today_close: pd.DataFrame,
    ) -> pd.DataFrame:
        """使用增量公式更新 EMA：EMA_today = Close * k + EMA_yesterday * (1 - k)

        公式：
            multiplier k = 2 / (period + 1)
            EMA_today = Close_today * k + EMA_yesterday * (1 - k)

        Args:
            ema_yesterday: 昨日 EMA 快照 (Code, EMA5, EMA10, ..., EMA200)
            today_close: 今日收盘价 (ts_code, close)

        Returns:
            更新后的 EMA DataFrame（格式与输入一致）
        """
        if ema_yesterday.empty or today_close.empty:
            logger.warning("update_ema_incremental: 输入数据为空，跳过更新")
            return ema_yesterday

        # 统一列名：today_close 的 ts_code -> Code
        close_df = today_close.rename(columns={"ts_code": "Code", "close": "Close_today"})
        close_df = close_df[["Code", "Close_today"]].drop_duplicates(subset="Code")

        # 合并昨日 EMA 与今日收盘价
        merged = ema_yesterday.merge(close_df, on="Code", how="inner")

        if merged.empty:
            logger.warning("update_ema_incremental: 合并后无数据，检查 Code 格式")
            return ema_yesterday

        # 向量化增量更新每个 EMA 周期
        for ema_col, period in EMA_PERIODS.items():
            k = 2.0 / (period + 1)
            merged[ema_col] = (
                merged["Close_today"] * k + merged[ema_col] * (1 - k)
            )

        # 更新 Close 和 Date
        merged["Close"] = merged["Close_today"]
        merged["Date"] = pd.Timestamp(date.today())
        merged.drop(columns=["Close_today"], inplace=True)

        logger.info(
            "update_ema_incremental: 更新 %d 只标的的 EMA",
            len(merged),
        )
        return merged

    def save_ema_snapshot(self, df: pd.DataFrame, snapshot_date: date | None = None):
        """将更新后的 EMA 快照保存为 Parquet + CSV。

        Args:
            df: EMA DataFrame
            snapshot_date: 快照日期，默认今天
        """
        if df.empty:
            logger.warning("save_ema_snapshot: 空数据，跳过保存")
            return

        if snapshot_date is None:
            snapshot_date = date.today()

        date_str = snapshot_date.strftime("%Y%m%d")
        parquet_path = self.ema_dir / f"ema_snapshot_{date_str}.parquet"
        csv_path = self.ema_dir / f"ema_snapshot_{date_str}.csv"

        df.to_parquet(parquet_path, index=False, engine="pyarrow")
        df.to_csv(csv_path, index=False)

        logger.info("save_ema_snapshot: 已保存 %s（%d 只标的）", parquet_path.name, len(df))

    # ================================================================
    # 4. 获取今日收盘价（从 DB 中最新交易日提取）
    # ================================================================

    async def load_today_close(self) -> pd.DataFrame:
        """从 stock_daily_quote 获取最新交易日的收盘价。

        Returns:
            DataFrame: ts_code, close, trade_date
        """
        sql = text("""
            SELECT ts_code, close, trade_date
            FROM stock_daily_quote
            WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_quote)
        """)

        async with async_session() as session:
            result = await session.execute(sql)
            rows = result.fetchall()

        if not rows:
            logger.error("load_today_close: 数据库中无任何行情数据")
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["ts_code", "close", "trade_date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")

        logger.info(
            "load_today_close: %d 只股票，日期 %s",
            len(df), df["trade_date"].iloc[0],
        )
        return df

    # ================================================================
    # 5. 从 akshare 批量拉取基本面数据（全市场）
    # ================================================================

    async def load_fundamentals(self) -> pd.DataFrame:
        """从 akshare 拉取最近 3 个季度的业绩报告数据。

        返回合并后的 DataFrame，每只股票最多 3 行（Q0, Q-1, Q-2）:
            股票代码, 报告期, 每股收益, 营业总收入, 营收同比增长,
            净利润, 净利润同比增长, 每股经营现金流量

        注意：
            akshare 为同步库，通过 to_thread 执行避免阻塞。
            使用 stock_yjbb_em（东方财富业绩报表）一次返回全市场数据。
        """
        # 确定最近 3 个季度的报告期
        quarters = self._recent_quarter_dates(n=3)
        logger.info("load_fundamentals: 拉取报告期 %s", quarters)

        all_dfs = []
        for q_date in quarters:
            try:
                df = await asyncio.to_thread(self._sync_fetch_yjbb, q_date)
                if df is not None and not df.empty:
                    df["report_date"] = q_date
                    all_dfs.append(df)
                    logger.info("load_fundamentals: %s 获取 %d 家", q_date, len(df))
            except Exception as e:
                logger.warning("load_fundamentals: %s 拉取失败: %s", q_date, e)

        if not all_dfs:
            logger.error("load_fundamentals: 未获取到任何基本面数据")
            return pd.DataFrame()

        combined = pd.concat(all_dfs, ignore_index=True)
        logger.info(
            "load_fundamentals: 合计 %d 条记录，覆盖 %d 家公司",
            len(combined), combined["股票代码"].nunique(),
        )
        return combined

    @staticmethod
    def _sync_fetch_yjbb(quarter_date: str) -> pd.DataFrame | None:
        """同步调用 akshare 获取某季度全市场业绩报表。

        Args:
            quarter_date: 报告期，格式 YYYYMMDD（如 '20250930'）

        Returns:
            DataFrame 或 None
        """
        import akshare as ak

        try:
            df = ak.stock_yjbb_em(date=quarter_date)
            if df is not None and not df.empty:
                # 标准化列名
                df = df.rename(columns={
                    "股票代码": "股票代码",
                    "股票简称": "股票简称",
                    "每股收益": "eps",
                    "营业总收入-营业总收入": "revenue",
                    "营业总收入-同比增长": "revenue_yoy",
                    "营业总收入-季度环比增长": "revenue_qoq",
                    "净利润-净利润": "net_profit",
                    "净利润-同比增长": "net_profit_yoy",
                    "净利润-季度环比增长": "net_profit_qoq",
                    "每股经营现金流量": "cashflow_per_share",
                    "每股净资产": "bps",
                    "净资产收益率": "roe",
                    "销售毛利率": "gross_margin",
                })
                return df
        except Exception as e:
            logger.warning("_sync_fetch_yjbb(%s) 异常: %s", quarter_date, e)
        return None

    @staticmethod
    def _recent_quarter_dates(n: int = 3) -> list[str]:
        """获取最近 n 个季度的报告期字符串（YYYYMMDD 格式）。

        季度末日：0331, 0630, 0930, 1231
        """
        today = date.today()
        quarters = []
        # 从当前年份开始向前推
        year = today.year
        month = today.month

        # 找到最近的已发布报告期（通常有 1-2 个月延迟）
        # 保守起见，假设当前月份 -2 个月之前的季报已发布
        ref_date = today - timedelta(days=60)

        quarter_ends = [
            (12, 31), (9, 30), (6, 30), (3, 31),
        ]

        y = ref_date.year
        for _ in range(8):  # 最多回溯 8 个季度
            for m, d in quarter_ends:
                qd = date(y, m, d)
                if qd <= ref_date and len(quarters) < n:
                    quarters.append(qd.strftime("%Y%m%d"))
            y -= 1
            if len(quarters) >= n:
                break

        return quarters[:n]

    # ================================================================
    # 6. 从 DB 批量加载历史最低/最高价（用于 Stage2 过滤）
    # ================================================================

    async def load_price_extremes(self, lookback_days: int = 200) -> pd.DataFrame:
        """加载近 N 天的 high/low 极值，用于 Stage2 过滤器计算。

        返回每只股票的：
            - min_low_120: 过去 120 个交易日最低价
            - max_high_60: 过去 60 个交易日最高价
            - quantile_close_90_60: 过去 60 天收盘价的 90 分位数

        使用 SQL 窗口函数在数据库端完成计算，减少数据传输。
        """
        sql = text("""
            WITH recent AS (
                SELECT ts_code, trade_date, close, high, low, volume,
                       ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
                FROM stock_daily_quote
                WHERE trade_date >= :min_date
            ),
            stats AS (
                SELECT ts_code,
                    -- 过去 120 个交易日最低价
                    MIN(CASE WHEN rn <= 120 THEN low END) AS min_low_120,
                    -- 过去 60 个交易日最高价
                    MAX(CASE WHEN rn <= 60 THEN high END) AS max_high_60,
                    -- 过去 50 个交易日的平均成交量
                    AVG(CASE WHEN rn <= 50 THEN volume END) AS avg_vol_50,
                    -- 最新一天的成交量
                    MAX(CASE WHEN rn = 1 THEN volume END) AS latest_volume,
                    -- 最新收盘价
                    MAX(CASE WHEN rn = 1 THEN close END) AS latest_close
                FROM recent
                GROUP BY ts_code
            )
            SELECT * FROM stats
            WHERE latest_close IS NOT NULL
        """)
        min_date = date.today() - timedelta(days=lookback_days)

        async with async_session() as session:
            result = await session.execute(sql, {"min_date": min_date})
            rows = result.fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=[
            "ts_code", "min_low_120", "max_high_60",
            "avg_vol_50", "latest_volume", "latest_close",
        ])

        for col in df.columns:
            if col != "ts_code":
                df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info("load_price_extremes: %d 只股票的极值统计", len(df))
        return df
