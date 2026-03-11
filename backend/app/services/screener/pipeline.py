"""Daily Screener Pipeline — 串行过滤管道编排。

完整流水线：
  1. 加载 OHLCV 行情数据（PostgreSQL）
  2. 加载/更新 EMA 快照（本地 Parquet + 增量更新）
  3. 计算价格极值（SQL 窗口函数）
  4. Stage2 趋势过滤器（技术面 8 项条件）
  5. 拉取基本面数据（akshare 批量接口）
  6. 基本面过滤器（防雷 + 营收 + EPS 加速）
  7. 输出白名单 JSON + 控制台打印

设计原则：
  - 每步独立 try/except，单步失败不崩溃
  - 日志记录每步耗时与通过数量
  - 支持 dry-run 模式（只打印不保存）
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .data_loader import DataLoader
from .filters import (
    FundamentalFilter,
    FundamentalFilterConfig,
    MinerviniScreener,
    Stage2FilterConfig,
)

logger = logging.getLogger("alphareader.screener.pipeline")

# 输出目录
PROJECT_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = PROJECT_ROOT / "data" / "watchlists"


class ScreenerPipeline:
    """每日白名单筛选管道 — 编排数据加载、过滤、输出全流程。

    使用方法：
        pipeline = ScreenerPipeline()
        result = await pipeline.run()
    """

    def __init__(
        self,
        stage2_config: Stage2FilterConfig | None = None,
        fundamental_config: FundamentalFilterConfig | None = None,
        output_dir: str | Path | None = None,
        dry_run: bool = False,
    ):
        """初始化筛选管道。

        Args:
            stage2_config: Stage2 过滤器配置，None 使用默认值
            fundamental_config: 基本面过滤器配置，None 使用默认值
            output_dir: 输出目录，默认 data/watchlists/
            dry_run: 仅打印不保存文件
        """
        self.loader = DataLoader()
        self.stage2_screener = MinerviniScreener(stage2_config)
        self.fundamental_filter = FundamentalFilter(fundamental_config)
        self.output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        self.dry_run = dry_run

    async def run(self) -> dict:
        """执行完整的筛选管道。

        Returns:
            运行结果摘要 dict，含 watchlist, stats, duration 等
        """
        pipeline_start = time.time()
        today_str = date.today().strftime("%Y-%m-%d")
        logger.info("=" * 60)
        logger.info("Daily Screener 启动 | %s", today_str)
        logger.info("=" * 60)

        result = {
            "date": today_str,
            "watchlist": [],
            "stats": {},
            "errors": [],
        }

        # ── Step 1: 加载 OHLCV 行情 ──
        step_start = time.time()
        try:
            ohlcv = await self.loader.load_ohlcv(lookback_days=200)
            if ohlcv.empty:
                result["errors"].append("OHLCV 数据加载失败")
                return result
            result["stats"]["ohlcv_records"] = len(ohlcv)
            result["stats"]["ohlcv_stocks"] = ohlcv["ts_code"].nunique()
        except Exception as e:
            logger.error("Step 1 OHLCV 加载异常: %s", e, exc_info=True)
            result["errors"].append(f"OHLCV: {e}")
            return result
        logger.info("Step 1 OHLCV 加载完成 [%.1fs]", time.time() - step_start)

        # ── Step 2: 加载/更新 EMA ──
        step_start = time.time()
        try:
            ema_df = self.loader.load_latest_ema()
            if ema_df.empty:
                result["errors"].append("EMA 快照加载失败")
                return result

            # 检查 EMA 快照日期是否是今天
            ema_date = pd.Timestamp(ema_df["Date"].iloc[0]).date()
            today = date.today()
            latest_trade_date = ohlcv["trade_date"].max().date()

            if ema_date < latest_trade_date:
                logger.info("EMA 快照日期 %s 早于最新交易日 %s，执行增量更新", ema_date, latest_trade_date)
                # 获取最新交易日的收盘价
                today_close = await self.loader.load_today_close()
                if not today_close.empty:
                    ema_df = DataLoader.update_ema_incremental(ema_df, today_close)
                    # 保存更新后的快照
                    if not self.dry_run:
                        self.loader.save_ema_snapshot(ema_df, latest_trade_date)
            else:
                logger.info("EMA 快照已是最新 (%s)", ema_date)

            result["stats"]["ema_stocks"] = len(ema_df)
        except Exception as e:
            logger.error("Step 2 EMA 加载/更新异常: %s", e, exc_info=True)
            result["errors"].append(f"EMA: {e}")
            return result
        logger.info("Step 2 EMA 加载/更新完成 [%.1fs]", time.time() - step_start)

        # ── Step 3: 计算价格极值 ──
        step_start = time.time()
        try:
            extremes = await self.loader.load_price_extremes(lookback_days=200)
            if extremes.empty:
                result["errors"].append("价格极值计算失败")
                return result
            result["stats"]["extremes_stocks"] = len(extremes)
        except Exception as e:
            logger.error("Step 3 价格极值计算异常: %s", e, exc_info=True)
            result["errors"].append(f"Extremes: {e}")
            return result
        logger.info("Step 3 价格极值计算完成 [%.1fs]", time.time() - step_start)

        # ── Step 4: Stage2 趋势过滤 ──
        step_start = time.time()
        try:
            stage2_passed = self.stage2_screener.apply(ohlcv, ema_df, extremes)
            result["stats"].update(self.stage2_screener.filter_stats)

            if stage2_passed.empty:
                logger.warning("Stage2 过滤后无候选股票")
                result["stats"]["stage2_passed"] = 0
                return result

            candidate_codes = set(stage2_passed["ts_code"].values)
            result["stats"]["stage2_passed"] = len(candidate_codes)
        except Exception as e:
            logger.error("Step 4 Stage2 过滤异常: %s", e, exc_info=True)
            result["errors"].append(f"Stage2: {e}")
            return result
        logger.info("Step 4 Stage2 过滤完成 [%.1fs]", time.time() - step_start)

        # ── Step 5: 拉取基本面数据 ──
        step_start = time.time()
        try:
            fundamental_df = await self.loader.load_fundamentals()
            result["stats"]["fundamental_records"] = len(fundamental_df)
        except Exception as e:
            logger.warning("Step 5 基本面数据拉取失败: %s，跳过基本面过滤", e)
            fundamental_df = pd.DataFrame()
            result["errors"].append(f"Fundamentals: {e}")
        logger.info("Step 5 基本面数据拉取完成 [%.1fs]", time.time() - step_start)

        # ── Step 6: 基本面过滤 ──
        step_start = time.time()
        try:
            final_codes = self.fundamental_filter.apply(fundamental_df, candidate_codes)
            result["stats"].update(self.fundamental_filter.filter_stats)
            result["stats"]["final_count"] = len(final_codes)
        except Exception as e:
            logger.warning("Step 6 基本面过滤异常: %s，使用 Stage2 结果", e)
            final_codes = candidate_codes
            result["errors"].append(f"FundFilter: {e}")
        logger.info("Step 6 基本面过滤完成 [%.1fs]", time.time() - step_start)

        # ── Step 7: 组装输出 ──
        watchlist = self._build_watchlist(
            final_codes, stage2_passed, fundamental_df, ema_df,
        )
        result["watchlist"] = watchlist
        result["stats"]["output_count"] = len(watchlist)

        # 保存文件
        if not self.dry_run and watchlist:
            self._save_output(watchlist, today_str)

        # 打印结果
        self._print_summary(result)

        duration = time.time() - pipeline_start
        result["duration_sec"] = round(duration, 1)
        logger.info("=" * 60)
        logger.info("Daily Screener 完成 | 耗时 %.1fs | 白名单 %d 只", duration, len(watchlist))
        logger.info("=" * 60)

        return result

    def _build_watchlist(
        self,
        final_codes: set[str],
        stage2_df: pd.DataFrame,
        fundamental_df: pd.DataFrame,
        ema_df: pd.DataFrame,
    ) -> list[dict]:
        """组装最终白名单输出。

        输出字段：
            ticker, current_price, eps_growth, revenue_yoy, ema20, ema50, ema120,
            vcp_score (ATR 收缩度)
        """
        watchlist = []

        for code in sorted(final_codes):
            entry = {"ticker": code, "current_price": None, "eps_growth": None, "vcp_score": None}

            # 从 stage2_df 取价格和 VCP 指标
            row = stage2_df[stage2_df["ts_code"] == code]
            if not row.empty:
                r = row.iloc[0]
                entry["current_price"] = round(float(r.get("latest_close", 0)), 2) if pd.notna(r.get("latest_close")) else None

                # VCP Score = 1 - (ATR20 / ATR60)，越大越收敛
                atr20 = r.get("atr_20")
                atr60 = r.get("atr_60")
                if pd.notna(atr20) and pd.notna(atr60) and atr60 > 0:
                    entry["vcp_score"] = round(1.0 - float(atr20) / float(atr60), 3)

            # 从 EMA 取均线数据
            ema_row = ema_df[ema_df["Code"] == code] if "Code" in ema_df.columns else ema_df[ema_df["ts_code"] == code]
            if not ema_row.empty:
                er = ema_row.iloc[0]
                entry["ema20"] = round(float(er.get("EMA20", 0)), 2) if pd.notna(er.get("EMA20")) else None
                entry["ema50"] = round(float(er.get("EMA50", 0)), 2) if pd.notna(er.get("EMA50")) else None
                entry["ema120"] = round(float(er.get("EMA120", 0)), 2) if pd.notna(er.get("EMA120")) else None

            # 从基本面取 EPS 增长
            if not fundamental_df.empty:
                fund_row = fundamental_df[fundamental_df["股票代码"] == code]
                if not fund_row.empty:
                    latest = fund_row.sort_values("report_date", ascending=False).iloc[0]
                    eps_g = latest.get("net_profit_yoy")
                    entry["eps_growth"] = round(float(eps_g), 2) if pd.notna(eps_g) else None
                    rev_yoy = latest.get("revenue_yoy")
                    entry["revenue_yoy"] = round(float(rev_yoy), 2) if pd.notna(rev_yoy) else None

            watchlist.append(entry)

        # 按 VCP Score 降序排列（收敛度最高的排前面）
        watchlist.sort(key=lambda x: x.get("vcp_score") or -999, reverse=True)
        return watchlist

    def _save_output(self, watchlist: list[dict], date_str: str):
        """保存白名单到 JSON 文件。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"watchlist_{date_str.replace('-', '')}.json"
        filepath = self.output_dir / filename

        output = {
            "date": date_str,
            "generated_at": datetime.now().isoformat(),
            "count": len(watchlist),
            "watchlist": watchlist,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info("白名单已保存: %s (%d 只)", filepath, len(watchlist))

    def _print_summary(self, result: dict):
        """打印漏斗过滤汇总到控制台。"""
        stats = result["stats"]
        watchlist = result["watchlist"]

        print("\n" + "═" * 60)
        print(f"  Daily Screener | {result['date']}")
        print("═" * 60)

        # 漏斗统计
        funnel = [
            ("全市场输入", stats.get("total_input", "-")),
            ("A1 均线多头排列", stats.get("A1_ema_trend", "-")),
            ("A2 脱离底部≥30%", stats.get("A2_bottom_rebound", "-")),
            ("A3 逼近前高≤15%", stats.get("A3_near_high", "-")),
            ("B1 站上筹码峰值", stats.get("B1_above_poc", "-")),
            ("B2 箱体突破90%", stats.get("B2_breakout", "-")),
            ("B3 放量≥1.5x", stats.get("B3_volume_surge", "-")),
            ("C1 VCP波动收缩", stats.get("C1_vcp_contraction", "-")),
            ("C2 大阳线活跃", stats.get("C2_big_yang", "-")),
            ("基本面通过", stats.get("fundamental_passed", "-")),
        ]
        print("\n  ┌─ 量化漏斗 ─────────────────────┐")
        for name, count in funnel:
            bar = "█" * min(int(count / max(stats.get("total_input", 1), 1) * 30), 30) if isinstance(count, int) else ""
            print(f"  │ {name:<16s} {str(count):>6s} {bar}")
        print(f"  └─ 最终白名单: {len(watchlist):>4d} 只 ──────────┘")

        # Top 20 白名单
        if watchlist:
            print("\n  ┌─ Top 20 白名单 ────────────────────────────────────────┐")
            print(f"  │ {'Ticker':<8s} {'Price':>8s} {'VCP':>6s} {'EPS%':>7s} {'Rev%':>7s} │")
            print(f"  │ {'─' * 40} │")
            for item in watchlist[:20]:
                ticker = item["ticker"]
                price = f"{item['current_price']:.2f}" if item.get("current_price") else "-"
                vcp = f"{item['vcp_score']:.3f}" if item.get("vcp_score") else "-"
                eps = f"{item['eps_growth']:.1f}" if item.get("eps_growth") else "-"
                rev = f"{item['revenue_yoy']:.1f}" if item.get("revenue_yoy") else "-"
                print(f"  │ {ticker:<8s} {price:>8s} {vcp:>6s} {eps:>7s} {rev:>7s} │")
            print(f"  └────────────────────────────────────────────────────────┘")

        if result["errors"]:
            print(f"\n  ⚠️  Errors: {result['errors']}")
        print()
