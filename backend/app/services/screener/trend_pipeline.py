"""右侧趋势 Pipeline — 串行过滤管道编排。

完整流水线：
  1. 加载 OHLCV 行情数据（PostgreSQL，80 天）
  1.5. 剔除 ST 股票
  2. 日均成交额过滤 + 技术面 5 条漏斗（TrendScreener）
  3. 补充行业/题材/主营/资金流向（enricher）
  4. 输出白名单 JSON + 写入数据库 + 控制台打印

设计原则：
  - 复用 DataLoader 的 load_ohlcv() 和 ST 剔除逻辑
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
from app.models.screener import TrendScreenerRun, TrendWatchlistDaily

from .data_loader import DataLoader
from .trend_filters import TrendFilterConfig, TrendScreener

logger = logging.getLogger("alphareader.screener.trend_pipeline")

# 输出目录 — 兼容 Docker 挂载路径和本地开发
_docker_watchlist_dir = Path("/data/trend_watchlists")
_local_watchlist_dir = Path(__file__).resolve().parents[4] / "data" / "trend_watchlists"
OUTPUT_DIR = _docker_watchlist_dir if _docker_watchlist_dir.exists() else _local_watchlist_dir


class TrendPipeline:
    """右侧趋势每日白名单筛选管道 — 编排数据加载、过滤、输出全流程。

    使用方法：
        pipeline = TrendPipeline(market="CN")
        result = await pipeline.run()
    """

    def __init__(
        self,
        market: str = "CN",
        config: TrendFilterConfig | None = None,
        output_dir: str | Path | None = None,
        dry_run: bool = False,
    ):
        """初始化趋势筛选管道。

        Args:
            market: 市场标识，"CN"（A 股）或 "US"（美股）
            config: 趋势过滤器配置，None 使用默认值
            output_dir: 输出目录，默认 data/trend_watchlists/
            dry_run: 仅打印不保存文件
        """
        self.market = market.upper()
        self.loader = DataLoader(market=self.market)
        self.trend_screener = TrendScreener(config)
        self.output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        self.dry_run = dry_run

    async def run(self) -> dict:
        """执行完整的趋势筛选管道。

        Returns:
            运行结果摘要 dict，含 watchlist, stats, duration 等
        """
        pipeline_start = time.time()
        today_str = date.today().strftime("%Y-%m-%d")
        logger.info("=" * 60)
        logger.info("Trend Screener 启动 | %s | market=%s", today_str, self.market)
        logger.info("=" * 60)

        result = {
            "date": today_str,
            "market": self.market,
            "watchlist": [],
            "stats": {},
            "errors": [],
        }

        # ── Step 1: 加载 OHLCV 行情（80 天足够 SMA50 + ADX28 + 缓冲）──
        step_start = time.time()
        try:
            ohlcv = await self.loader.load_ohlcv(lookback_days=120)
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

        # ── Step 2: 右侧趋势技术面过滤 ──
        step_start = time.time()
        try:
            trend_passed = self.trend_screener.apply(ohlcv)
            result["stats"].update(self.trend_screener.filter_stats)

            if trend_passed.empty:
                logger.warning("趋势过滤后无候选股票")
                result["stats"]["trend_passed"] = 0
                # 即使没有结果也要写空的 DB 记录
                duration = time.time() - pipeline_start
                result["duration_sec"] = round(duration, 1)
                if not self.dry_run:
                    await self._save_to_db(result, pipeline_start, duration)
                self._print_summary(result)
                return result

            result["stats"]["trend_passed"] = len(trend_passed)
        except Exception as e:
            logger.error("Step 2 趋势过滤异常: %s", e, exc_info=True)
            result["errors"].append(f"TrendFilter: {e}")
            return result
        logger.info("Step 2 趋势过滤完成 [%.1fs]", time.time() - step_start)

        # ── Step 2.5: 从 DB 批量加载股票名称 ──
        name_map: dict[str, str] = {}
        try:
            from .utils import load_stock_names
            passed_codes = set(trend_passed["ts_code"].tolist())
            name_map = await load_stock_names(passed_codes, self.market)
            logger.info("从 DB 加载 %d 只股票名称", len(name_map))
        except Exception as e:
            logger.warning("从 DB 加载股票名称失败（不影响后续流程）: %s", e)

        # ── Step 3: 组装白名单 ──
        watchlist = self._build_watchlist(trend_passed, name_map)
        result["stats"]["output_count"] = len(watchlist)

        # ── Step 3.5: 补充行业/题材/主营/资金流向（仅 A 股）──
        if watchlist and not self.dry_run:
            step_start = time.time()
            try:
                from .enricher import enrich_watchlist
                watchlist = await enrich_watchlist(watchlist, market=self.market)
                logger.info("Step 3.5 数据补充完成 [%.1fs]", time.time() - step_start)
            except Exception as e:
                logger.warning("Step 3.5 数据补充异常（不影响后续流程）: %s", e)

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
        logger.info("Trend Screener 完成 | 耗时 %.1fs | 白名单 %d 只", duration, len(watchlist))
        logger.info("=" * 60)

        return result

    def _build_watchlist(
        self,
        trend_df: pd.DataFrame,
        name_map: dict[str, str] | None = None,
    ) -> list[dict]:
        """组装最终白名单输出。

        输出字段：
            ticker, name, current_price, ma20, ma50, adx, rsi,
            volume_ratio, trend_score
        """
        if name_map is None:
            name_map = {}
        watchlist = []

        for _, row in trend_df.iterrows():
            ts_code = row["ts_code"]
            entry = {
                "ticker": ts_code,
                "name": name_map.get(ts_code, ""),
                "current_price": round(float(row["latest_close"]), 2) if pd.notna(row.get("latest_close")) else None,
                "ma20": row.get("ma20"),
                "ma50": row.get("ma50"),
                "adx": row.get("adx"),
                "rsi": row.get("rsi"),
                "volume_ratio": row.get("volume_ratio_val"),
                "trend_score": row.get("trend_score"),
            }
            watchlist.append(entry)

        # 已经按 trend_score 降序（在 TrendScreener.apply 内排序）
        return watchlist

    def _save_output(self, watchlist: list[dict], date_str: str):
        """保存白名单到 JSON 文件。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"trend_watchlist_{date_str.replace('-', '')}.json"
        filepath = self.output_dir / filename

        output = {
            "date": date_str,
            "generated_at": datetime.now().isoformat(),
            "count": len(watchlist),
            "watchlist": watchlist,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info("趋势白名单已保存: %s (%d 只)", filepath, len(watchlist))

    async def _save_to_db(self, result: dict, pipeline_start: float, duration: float):
        """将运行记录和白名单写入数据库。

        同一天重跑策略：
          - trend_screener_runs: 始终追加（审计记录）
          - trend_watchlist_daily: 先删当天旧数据再写入
          - 同一事务内原子操作
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
                # 写入运行记录
                run = TrendScreenerRun(
                    run_date=today,
                    market=self.market,
                    started_at=started,
                    finished_at=finished,
                    duration_sec=round(duration, 1),
                    total_input=stats.get("total_input", 0) or stats.get("ohlcv_stocks", 0),
                    trend_passed=stats.get("trend_passed", 0),
                    final_count=len(watchlist),
                    stats=stats,
                    errors=errors,
                    status=status,
                )
                db.add(run)
                await db.flush()  # 获取 run.id

                # 清除当天旧白名单
                deleted = await db.execute(
                    delete(TrendWatchlistDaily).where(
                        TrendWatchlistDaily.run_date == today,
                        TrendWatchlistDaily.market == self.market,
                    )
                )
                if deleted.rowcount:
                    logger.info("清除当天旧趋势白名单: %d 条", deleted.rowcount)

                # 写入白名单条目
                for item in watchlist:
                    entry = TrendWatchlistDaily(
                        run_date=today,
                        market=self.market,
                        ts_code=item["ticker"],
                        name=item.get("name"),
                        current_price=item.get("current_price"),
                        ma20=item.get("ma20"),
                        ma50=item.get("ma50"),
                        adx=item.get("adx"),
                        rsi=item.get("rsi"),
                        volume_ratio=item.get("volume_ratio"),
                        trend_score=item.get("trend_score"),
                        industry=item.get("industry"),
                        concepts=item.get("concepts"),
                        main_business=item.get("main_business"),
                        fund_flow_net=item.get("fund_flow_net"),
                        run_id=run.id,
                    )
                    db.add(entry)

                await db.commit()
                logger.info("已写入数据库: TrendScreenerRun#%d + %d 条白名单", run.id, len(watchlist))

        except Exception as e:
            logger.error("数据库写入失败（不影响 pipeline 结果）: %s", e, exc_info=True)

    def _print_summary(self, result: dict):
        """打印漏斗过滤汇总到控制台。"""
        stats = result["stats"]
        watchlist = result["watchlist"]

        print("\n" + "═" * 60)
        print(f"  Trend Screener | {result['date']}")
        print("═" * 60)

        # 漏斗统计
        funnel = [
            ("全市场输入", stats.get("total_input", "-")),
            ("剔除ST", f'-{stats["st_removed"]}' if stats.get("st_removed") else "0"),
            ("日均成交额>2000万", stats.get("amount_filter", "-")),
            ("数据新鲜度", stats.get("freshness_filter", "-")),
            ("T1 MA双线多头排列", stats.get("T1_ma_alignment", "-")),
            ("T2 ADX趋势强度>25", stats.get("T2_adx_strength", "-")),
            ("T3 当日创20日新高", stats.get("T3_breakout", "-")),
            ("T4 近3天放量≥1.5x", stats.get("T4_volume_surge", "-")),
            ("T5 RSI动量(50-80)", stats.get("T5_rsi_momentum", "-")),
        ]
        print("\n  ┌─ 趋势量化漏斗 ──────────────────┐")
        for name, count in funnel:
            bar = "█" * min(int(count / max(stats.get("total_input", 1), 1) * 30), 30) if isinstance(count, int) else ""
            print(f"  │ {name:<18s} {str(count):>6s} {bar}")
        print(f"  └─ 最终白名单: {len(watchlist):>4d} 只 ──────────┘")

        # Top 20 白名单
        if watchlist:
            print("\n  ┌─ Top 20 趋势白名单 ────────────────────────────────────┐")
            print(f"  │ {'Ticker':<10s} {'Price':>8s} {'Score':>6s} {'ADX':>6s} {'RSI':>6s} {'VolR':>6s} │")
            print(f"  │ {'─' * 48} │")
            for item in watchlist[:20]:
                ticker = item["ticker"]
                price = f"{item['current_price']:.2f}" if item.get("current_price") else "-"
                score = f"{item['trend_score']:.3f}" if item.get("trend_score") else "-"
                adx = f"{item['adx']:.1f}" if item.get("adx") else "-"
                rsi = f"{item['rsi']:.1f}" if item.get("rsi") else "-"
                vol_r = f"{item['volume_ratio']:.1f}" if item.get("volume_ratio") else "-"
                print(f"  │ {ticker:<10s} {price:>8s} {score:>6s} {adx:>6s} {rsi:>6s} {vol_r:>6s} │")
            print(f"  └──────────────────────────────────────────────────────┘")

        if result["errors"]:
            print(f"\n  ⚠️  Errors: {result['errors']}")
        print()
