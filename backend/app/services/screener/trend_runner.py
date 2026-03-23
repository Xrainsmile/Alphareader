#!/usr/bin/env python3
"""右侧趋势 Screener 入口脚本 — 每日收盘后运行的趋势突破白名单筛选。

使用方式：
    # 在项目根目录下执行（需要 .env 中的 DB 配置）
    cd /path/to/AlphaReader/backend
    python3 -m app.services.screener.trend_runner

    # 或者指定参数
    python3 -m app.services.screener.trend_runner --dry-run
    python3 -m app.services.screener.trend_runner --adx-threshold 20

    # 服务器上通过 Docker 运行
    docker compose run --rm web python3 -m app.services.screener.trend_runner

依赖说明：
    - 需要 PostgreSQL 中有最新的 stock_daily_quote 数据（由 data_fetcher 维护）
    - 不依赖 EMA Parquet 快照（SMA 直接从 OHLCV 计算）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# ── 确保项目根目录在 sys.path 中 ──
BACKEND_DIR = Path(__file__).resolve().parents[3]  # backend/
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def setup_logging(level: str = "INFO"):
    """配置日志格式。"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # 降低第三方库的日志噪音
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("akshare").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="AlphaReader Trend Screener — 右侧趋势突破白名单筛选",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印结果，不保存文件",
    )
    parser.add_argument(
        "--market",
        default="CN",
        choices=["CN", "US"],
        help="目标市场（默认 CN）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别（默认 INFO）",
    )

    # 基础筛选参数
    base = parser.add_argument_group("基础筛选参数")
    base.add_argument("--min-avg-amount", type=float, default=2e7,
                      help="日均成交额下限（默认 2000 万元）")

    # 趋势过滤器参数
    trend = parser.add_argument_group("趋势过滤器参数")
    trend.add_argument("--ma-short", type=int, default=20,
                       help="短期均线周期（默认 20）")
    trend.add_argument("--ma-long", type=int, default=50,
                       help="长期均线周期（默认 50）")
    trend.add_argument("--require-ma50-up", action="store_true", default=False,
                       help="是否要求 SMA50 也向上（默认 False）")
    trend.add_argument("--adx-threshold", type=float, default=20.0,
                       help="ADX 趋势强度下限（默认 20）")
    trend.add_argument("--breakout-window", type=int, default=10,
                       help="突破回溯窗口（默认 10 日）")
    trend.add_argument("--volume-ratio", type=float, default=1.2,
                       help="放量倍数（默认 1.2）")
    trend.add_argument("--rsi-lower", type=float, default=45.0,
                       help="RSI 下限（默认 45）")
    trend.add_argument("--rsi-upper", type=float, default=85.0,
                       help="RSI 上限（默认 85）")

    return parser.parse_args()


async def main():
    """异步主函数。"""
    args = parse_args()
    setup_logging(args.log_level)

    from app.services.screener.trend_filters import TrendFilterConfig
    from app.services.screener.trend_pipeline import TrendPipeline

    # 组装配置
    config = TrendFilterConfig(
        min_avg_amount=args.min_avg_amount,
        ma_short=args.ma_short,
        ma_long=args.ma_long,
        require_ma50_up=args.require_ma50_up,
        adx_threshold=args.adx_threshold,
        breakout_window=args.breakout_window,
        volume_ratio=args.volume_ratio,
        rsi_lower=args.rsi_lower,
        rsi_upper=args.rsi_upper,
    )

    pipeline = TrendPipeline(
        market=args.market,
        config=config,
        dry_run=args.dry_run,
    )

    result = await pipeline.run()

    # 设置退出码
    if result.get("errors") and not result.get("watchlist"):
        sys.exit(1)

    return result


if __name__ == "__main__":
    asyncio.run(main())
