"""Daily Screener Pipeline — 串行过滤管道编排。

完整流水线：
  1. 加载 OHLCV 行情数据（PostgreSQL）
  2. 加载/更新 EMA 快照（本地 Parquet + 增量更新）
  3. 计算价格极值（SQL 窗口函数）
  4. Stage2 趋势过滤器（技术面 8 项条件）
  5. 拉取基本面数据（akshare 批量接口）
  6. 基本面过滤器（防雷 + 营收 + EPS 加速）
  7. 输出白名单 JSON + 写入数据库 + 控制台打印

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

from app.database import async_session
from app.models.screener import ScreenerRun, WatchlistDaily

from .data_loader import DataLoader
from .filters import (
    FundamentalFilter,
    FundamentalFilterConfig,
    MinerviniScreener,
    Stage2FilterConfig,
)

logger = logging.getLogger("alphareader.screener.pipeline")

# 输出目录 — 兼容 Docker 挂载路径和本地开发
_docker_watchlist_dir = Path("/data/watchlists")
_local_watchlist_dir = Path(__file__).resolve().parents[4] / "data" / "watchlists"
OUTPUT_DIR = _docker_watchlist_dir if _docker_watchlist_dir.exists() else _local_watchlist_dir


class ScreenerPipeline:
    """每日白名单筛选管道 — 编排数据加载、过滤、输出全流程。

    使用方法：
        pipeline = ScreenerPipeline(market="CN")
        result = await pipeline.run()
    """

    def __init__(
        self,
        market: str = "CN",
        stage2_config: Stage2FilterConfig | None = None,
        fundamental_config: FundamentalFilterConfig | None = None,
        output_dir: str | Path | None = None,
        dry_run: bool = False,
    ):
        """初始化筛选管道。

        Args:
            market: 市场标识，"CN"（A 股）或 "US"（美股）
            stage2_config: Stage2 过滤器配置，None 使用默认值
            fundamental_config: 基本面过滤器配置，None 使用默认值
            output_dir: 输出目录，默认 data/watchlists/
            dry_run: 仅打印不保存文件
        """
        self.market = market.upper()
        self.loader = DataLoader(market=self.market)
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
        logger.info("Daily Screener 启动 | %s | market=%s", today_str, self.market)
        logger.info("=" * 60)

        result = {
            "date": today_str,
            "market": self.market,
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

        # ── Step 1.5: 剔除 ST 股票（仅 A 股市场）──
        st_codes: set[str] = set()
        try:
            from .utils import load_st_codes
            st_codes = await load_st_codes(self.market)
            if st_codes:
                before = ohlcv["ts_code"].nunique()
                ohlcv = ohlcv[~ohlcv["ts_code"].isin(st_codes)]
                after = ohlcv["ts_code"].nunique()
                result["stats"]["st_removed"] = before - after
                logger.info("剔除 ST 股票: %d 只 (%d → %d)", before - after, before, after)
        except Exception as e:
            logger.warning("ST 股票剔除异常（不影响后续流程）: %s", e)

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

            # 从 EMA 中也剔除 ST 股票
            if st_codes:
                code_col = "Code" if "Code" in ema_df.columns else "ts_code"
                ema_before = len(ema_df)
                ema_df = ema_df[~ema_df[code_col].isin(st_codes)]
                logger.info("EMA 剔除 ST: %d → %d", ema_before, len(ema_df))

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
            # 从 extremes 中也剔除 ST 股票
            if st_codes:
                ext_before = len(extremes)
                extremes = extremes[~extremes["ts_code"].isin(st_codes)]
                logger.info("Extremes 剔除 ST: %d → %d", ext_before, len(extremes))
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

        # ── Step 5.5: 拉取扣非净利润、商誉、净资产（逐股查询）──
        step_start = time.time()
        financial_details_df = pd.DataFrame()
        try:
            financial_details_df = await self.loader.load_financial_details(candidate_codes)
            result["stats"]["financial_details_count"] = len(financial_details_df)
        except Exception as e:
            logger.warning("Step 5.5 扣非净利润/商誉数据拉取失败: %s，继续基本面过滤", e)
            result["errors"].append(f"FinancialDetails: {e}")
        logger.info("Step 5.5 扣非净利润/商誉数据拉取完成 [%.1fs]", time.time() - step_start)

        # ── Step 6: 基本面过滤 ──
        step_start = time.time()
        try:
            final_codes = self.fundamental_filter.apply(
                fundamental_df, candidate_codes, financial_details_df,
            )
            result["stats"].update(self.fundamental_filter.filter_stats)
            result["stats"]["final_count"] = len(final_codes)
        except Exception as e:
            logger.warning("Step 6 基本面过滤异常: %s，使用 Stage2 结果", e)
            final_codes = candidate_codes
            result["errors"].append(f"FundFilter: {e}")
        logger.info("Step 6 基本面过滤完成 [%.1fs]", time.time() - step_start)

        # ── Step 7: 组装输出 ──
        # 从本地 DB 批量查出股票名称（stock_daily_quote 每天入库时已带 name）
        name_map: dict[str, str] = {}
        try:
            from .utils import load_stock_names
            name_map = await load_stock_names(final_codes, self.market)
            logger.info("从 DB 加载 %d 只股票名称", len(name_map))
        except Exception as e:
            logger.warning("从 DB 加载股票名称失败（不影响后续流程）: %s", e)

        watchlist = self._build_watchlist(
            final_codes, stage2_passed, fundamental_df, ema_df, name_map,
        )
        result["stats"]["output_count"] = len(watchlist)

        # ── Step 7.5: 补充行业/题材/主营/资金流向（仅 A 股）──
        if watchlist and not self.dry_run:
            step_start = time.time()
            try:
                from .enricher import enrich_watchlist
                watchlist = await enrich_watchlist(watchlist, market=self.market)
                logger.info("Step 7.5 数据补充完成 [%.1fs]", time.time() - step_start)
            except Exception as e:
                logger.warning("Step 7.5 数据补充异常（不影响后续流程）: %s", e)

        result["watchlist"] = watchlist

        # 保存文件
        if not self.dry_run and watchlist:
            self._save_output(watchlist, today_str)

        # 打印结果
        self._print_summary(result)

        duration = time.time() - pipeline_start
        result["duration_sec"] = round(duration, 1)

        # ── 写入数据库 ──
        if not self.dry_run:
            await self._save_to_db(result, pipeline_start, duration)

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
        name_map: dict[str, str] | None = None,
    ) -> list[dict]:
        """组装最终白名单输出。

        输出字段：
            ticker, name, current_price, eps_growth, revenue_yoy, ema20, ema50, ema120,
            vcp_score (ATR 收缩度)
        """
        if name_map is None:
            name_map = {}
        watchlist = []

        for code in sorted(final_codes):
            entry = {
                "ticker": code,
                "name": name_map.get(code, ""),
                "current_price": None,
                "eps_growth": None,
                "vcp_score": None,
            }

            # 从 stage2_df 取价格和 VCP 指标
            row = stage2_df[stage2_df["ts_code"] == code]
            if not row.empty:
                r = row.iloc[0]
                entry["current_price"] = round(float(r.get("latest_close", 0)), 2) if pd.notna(r.get("latest_close")) else None

                # VCP Score = 1 - (Range_10d% / Range_40d%)，越大越收敛
                r_short = r.get("range_short_pct")
                r_long = r.get("range_long_pct")
                if pd.notna(r_short) and pd.notna(r_long) and r_long > 0:
                    entry["vcp_score"] = round(1.0 - float(r_short) / float(r_long), 3)

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

    async def _save_to_db(self, result: dict, pipeline_start: float, duration: float):
        """将运行记录和白名单写入数据库。

        同一天重跑策略：
          - screener_runs: 始终追加（保留每次运行的审计记录，方便调参对比）
          - watchlist_daily: 先删除当天旧数据再写入，保证唯一约束不冲突，
            且白名单始终反映最新一次运行的结果。
          - 两步操作在同一事务内，保证原子性。

        失败时仅记录日志，不影响整体 pipeline 结果。
        """
        from datetime import timezone

        from sqlalchemy import delete

        today = date.today()
        started = datetime.fromtimestamp(pipeline_start, tz=timezone.utc)
        finished = datetime.now(tz=timezone.utc)
        stats = result.get("stats", {})
        errors = result.get("errors", [])
        watchlist = result.get("watchlist", [])

        # 判断状态
        if errors and not watchlist:
            status = "failed"
        elif errors:
            status = "partial"
        else:
            status = "success"

        try:
            async with async_session() as db:
                # 写入运行记录（始终追加，保留审计日志）
                run = ScreenerRun(
                    run_date=today,
                    market=self.market,
                    started_at=started,
                    finished_at=finished,
                    duration_sec=round(duration, 1),
                    total_input=stats.get("total_input", 0) or stats.get("ohlcv_stocks", 0),
                    stage2_passed=stats.get("stage2_passed", 0),
                    fundamental_passed=stats.get("fundamental_passed", 0),
                    final_count=stats.get("final_count", len(watchlist)),
                    stats=stats,
                    errors=errors,
                    status=status,
                )
                db.add(run)
                await db.flush()  # 获取 run.id

                # 清除当天旧白名单（若存在），再写入新数据
                deleted = await db.execute(
                    delete(WatchlistDaily).where(
                        WatchlistDaily.run_date == today,
                        WatchlistDaily.market == self.market,
                    )
                )
                if deleted.rowcount:
                    logger.info("清除当天旧白名单: %d 条", deleted.rowcount)

                # 写入白名单条目
                for item in watchlist:
                    entry = WatchlistDaily(
                        run_date=today,
                        market=self.market,
                        ts_code=item["ticker"],
                        name=item.get("name"),
                        current_price=item.get("current_price"),
                        ema20=item.get("ema20"),
                        ema50=item.get("ema50"),
                        ema120=item.get("ema120"),
                        vcp_score=item.get("vcp_score"),
                        eps_growth=item.get("eps_growth"),
                        revenue_yoy=item.get("revenue_yoy"),
                        industry=item.get("industry"),
                        concepts=item.get("concepts"),
                        main_business=item.get("main_business"),
                        fund_flow_net=item.get("fund_flow_net"),
                        run_id=run.id,
                    )
                    db.add(entry)

                await db.commit()
                logger.info("已写入数据库: ScreenerRun#%d + %d 条白名单", run.id, len(watchlist))

        except Exception as e:
            logger.error("数据库写入失败（不影响 pipeline 结果）: %s", e, exc_info=True)

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
            ("剔除ST", f'-{stats["st_removed"]}' if stats.get("st_removed") else "0"),
            ("A1 均线多头排列", stats.get("A1_ema_trend", "-")),
            ("A2 脱离底部≥30%", stats.get("A2_bottom_rebound", "-")),
            ("A3 逼近前高≤15%", stats.get("A3_near_high", "-")),
            ("B1 站上筹码峰值", stats.get("B1_above_poc", "-")),
            ("B2 箱体突破90%", stats.get("B2_breakout", "-")),
            ("B3 放量≥1.5x[跳过]", stats.get("B3_volume_surge", "-")),
            ("C1 VCP-NRC收敛", stats.get("C1_vcp_contraction", "-")),
            ("C2 大阳线[跳过]", stats.get("C2_big_yang", "-")),
            ("商誉防雷(≥30%)", f'-{stats["goodwill_killed"]}' if stats.get("goodwill_killed") else "0"),
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
