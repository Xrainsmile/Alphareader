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
# 兼容 Docker（/data/ema_snapshots 挂载）和本地（项目根/data/ema_snapshots）
def _find_ema_dir() -> Path:
    """查找 EMA 快照目录，优先使用 Docker 挂载路径。"""
    # Docker 容器内：./data 挂载到 /data
    docker_path = Path("/data/ema_snapshots")
    if docker_path.exists():
        return docker_path

    # 本地开发：从源文件向上查找
    cur = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = cur / "data" / "ema_snapshots"
        if candidate.exists():
            return candidate
        cur = cur.parent

    # fallback: 按本地结构 parents[4]
    return Path(__file__).resolve().parents[4] / "data" / "ema_snapshots"

EMA_SNAPSHOT_DIR = _find_ema_dir()

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
        loader = DataLoader(market="CN")
        ohlcv_df = await loader.load_ohlcv(lookback_days=120)
        ema_df = loader.load_latest_ema()
        ema_df = loader.update_ema_incremental(ema_df, today_close_df)
        fundamental_df = await loader.load_fundamentals()
    """

    def __init__(self, market: str = "CN", ema_dir: str | Path | None = None):
        """初始化数据加载器。

        Args:
            market: 市场标识，"CN"（A 股）或 "US"（美股）
            ema_dir: EMA 快照目录路径，默认使用项目内的 data/ema_snapshots/
        """
        self.market = market.upper()
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
            WHERE trade_date >= :min_date AND market = :market
            ORDER BY ts_code, trade_date
        """)

        async with async_session() as session:
            result = await session.execute(sql, {"min_date": min_date, "market": self.market})
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

    @staticmethod
    def compute_ema_from_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
        """从 OHLCV 历史数据直接计算 EMA（不依赖快照文件）。

        适用于美股等没有预置 EMA 快照的市场。
        需要 OHLCV 至少有 200+ 天数据才能计算 EMA200，
        120+ 天才能计算 EMA120。

        Args:
            ohlcv: 全市场 OHLCV 数据，必须含 ts_code, trade_date, close

        Returns:
            DataFrame: Code, Date, Close, EMA5, EMA10, EMA20, EMA50, EMA120, EMA200
        """
        if ohlcv.empty:
            logger.warning("compute_ema_from_ohlcv: OHLCV 为空")
            return pd.DataFrame()

        # 确保按 ts_code + trade_date 排序
        df = ohlcv[["ts_code", "trade_date", "close"]].copy()
        df = df.sort_values(["ts_code", "trade_date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")

        results = []
        for ts_code, group in df.groupby("ts_code"):
            if len(group) < 20:
                continue  # 至少 20 天才有意义
            row = {"Code": ts_code, "Close": group["close"].iloc[-1]}
            row["Date"] = pd.Timestamp(group["trade_date"].iloc[-1])
            for ema_col, period in EMA_PERIODS.items():
                if len(group) >= period:
                    ema_val = group["close"].ewm(span=period, adjust=False).mean().iloc[-1]
                else:
                    ema_val = group["close"].ewm(span=period, adjust=False).mean().iloc[-1]
                row[ema_col] = ema_val
            results.append(row)

        result_df = pd.DataFrame(results)
        logger.info(
            "compute_ema_from_ohlcv: 从 OHLCV 计算了 %d 只标的的 EMA",
            len(result_df),
        )
        return result_df

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
            WHERE trade_date = (
                SELECT MAX(trade_date) FROM stock_daily_quote WHERE market = :market
            ) AND market = :market
        """)

        async with async_session() as session:
            result = await session.execute(sql, {"market": self.market})
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
            美股暂不支持基本面数据（akshare 仅覆盖 A 股），返回空 DataFrame。
        """
        if self.market != "CN":
            logger.info("load_fundamentals: 市场 %s 暂不支持 akshare 基本面，跳过", self.market)
            return pd.DataFrame()
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
                WHERE trade_date >= :min_date AND market = :market
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
            result = await session.execute(sql, {"min_date": min_date, "market": self.market})
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

    # ================================================================
    # 7. 逐股获取扣非净利润、商誉、净资产（用于基本面过滤）
    # ================================================================

    async def load_financial_details(
        self,
        codes: list[str] | set[str],
        quarter_date: str | None = None,
    ) -> pd.DataFrame:
        """通过 akshare stock_financial_abstract 逐股获取关键财务指标。

        获取字段：扣非净利润、商誉、股东权益合计(净资产)。
        该接口按股票逐只查询，仅对 Stage2 通过的少量候选股调用。
        美股暂不支持（akshare 仅覆盖 A 股），返回空 DataFrame。

        Args:
            codes: 需要查询的股票代码列表
            quarter_date: 指定报告期（YYYYMMDD），None 则自动取最近季度

        Returns:
            DataFrame: 股票代码, deducted_profit, goodwill, net_assets
        """
        if self.market != "CN":
            logger.info("load_financial_details: 市场 %s 暂不支持 akshare 财务数据，跳过", self.market)
            return pd.DataFrame(columns=["股票代码", "deducted_profit", "goodwill", "net_assets"])
        if quarter_date is None:
            quarters = self._recent_quarter_dates(n=1)
            quarter_date = quarters[0] if quarters else "20240930"

        codes_list = list(codes)
        logger.info(
            "load_financial_details: 查询 %d 只股票的扣非净利润/商誉/净资产（报告期 %s）",
            len(codes_list), quarter_date,
        )

        results = []
        failed = 0

        for i, code in enumerate(codes_list):
            if i > 0 and i % 20 == 0:
                logger.info("load_financial_details: 进度 %d/%d", i, len(codes_list))

            try:
                row = await asyncio.to_thread(self._sync_fetch_financial_abstract, code, quarter_date)
                if row is not None:
                    results.append(row)
                else:
                    # 接口无数据，填充默认值
                    results.append({
                        "股票代码": code,
                        "deducted_profit": float("nan"),
                        "goodwill": 0.0,
                        "net_assets": float("nan"),
                    })
            except Exception as e:
                logger.debug("load_financial_details: %s 查询异常: %s", code, e)
                results.append({
                    "股票代码": code,
                    "deducted_profit": float("nan"),
                    "goodwill": 0.0,
                    "net_assets": float("nan"),
                })
                failed += 1

            # 请求间隔，避免被封
            await asyncio.sleep(0.15)

        logger.info(
            "load_financial_details: 完成 %d 只，失败 %d 只",
            len(results), failed,
        )

        if not results:
            return pd.DataFrame(columns=["股票代码", "deducted_profit", "goodwill", "net_assets"])

        df = pd.DataFrame(results)
        # 商誉 NaN 转 0（无商誉的公司视为 0）
        df["goodwill"] = pd.to_numeric(df["goodwill"], errors="coerce").fillna(0.0)
        df["deducted_profit"] = pd.to_numeric(df["deducted_profit"], errors="coerce")
        df["net_assets"] = pd.to_numeric(df["net_assets"], errors="coerce")

        return df

    @staticmethod
    def _sync_fetch_financial_abstract(code: str, quarter_date: str) -> dict | None:
        """同步调用 akshare 获取单只股票的财务摘要关键指标。

        Args:
            code: 6 位股票代码
            quarter_date: 报告期 YYYYMMDD

        Returns:
            包含 deducted_profit, goodwill, net_assets 的 dict，或 None
        """
        import akshare as ak

        try:
            df = ak.stock_financial_abstract(symbol=code)
            if df is None or df.empty:
                return None

            result = {"股票代码": code}

            # 从常用指标中提取目标行
            targets = {
                "扣非净利润": "deducted_profit",
                "商誉": "goodwill",
                "股东权益合计(净资产)": "net_assets",
            }

            for cn_name, en_key in targets.items():
                row = df[(df["选项"] == "常用指标") & (df["指标"] == cn_name)]
                if not row.empty:
                    val = row.iloc[0].get(quarter_date)
                    if val is not None and str(val).strip() not in ("", "nan", "None"):
                        try:
                            result[en_key] = float(val)
                        except (ValueError, TypeError):
                            result[en_key] = float("nan")
                    else:
                        result[en_key] = float("nan")
                else:
                    result[en_key] = float("nan")

            # 商誉 NaN 视为 0
            import math
            if math.isnan(result.get("goodwill", 0.0) or 0.0):
                result["goodwill"] = 0.0

            return result

        except Exception as e:
            logger.debug("_sync_fetch_financial_abstract(%s) 异常: %s", code, e)
            return None
