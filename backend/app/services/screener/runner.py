#!/usr/bin/env python3
"""Daily Screener 入口脚本 — 每日收盘后 (15:35) 运行的白名单筛选。

使用方式：
    # 在项目根目录下执行（需要 .env 中的 DB 配置）
    cd /path/to/AlphaReader/backend
    python3 -m app.services.screener.runner

    # 或者指定参数
    python3 -m app.services.screener.runner --dry-run          # 仅打印不保存
    python3 -m app.services.screener.runner --volume-ratio 1.2  # 调整放量阈值

    # 服务器上通过 Docker 运行（推荐）
    docker compose run --rm web python3 -m app.services.screener.runner

定时任务（cron）：
    # 每个交易日 15:35 运行
    35 15 * * 1-5 cd /home/Alphareader && docker compose run --rm web python3 -m app.services.screener.runner >> /tmp/screener.log 2>&1

依赖说明：
    - 需要 PostgreSQL 中有最新的 stock_daily_quote 数据（由 data_fetcher 维护）
    - 需要 data/ema_snapshots/ 中有 EMA 快照（由 calculate_ema 工具维护）
    - akshare 用于拉取基本面数据（可选，无数据时跳过基本面过滤）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# ── 确保项目根目录在 sys.path 中 ──
# 当通过 `python3 -m app.services.screener.runner` 执行时，
# 工作目录应该是 backend/，sys.path 已正确。
# 当直接执行 runner.py 时，需手动添加。
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
        description="AlphaReader Daily Screener — Minervini Stage2 白名单筛选",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印结果，不保存文件",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别（默认 INFO）",
    )

    # Stage2 过滤器参数
    stage2 = parser.add_argument_group("Stage2 过滤器参数")
    stage2.add_argument("--volume-ratio", type=float, default=1.5,
                        help="放量倍数（默认 1.5）")
    stage2.add_argument("--vcp-contraction-ratio", type=float, default=0.6,
                        help="VCP 深度收敛比（默认 0.6，即短期振幅≤长期的60%%）")
    stage2.add_argument("--max-tightness", type=float, default=0.15,
                        help="VCP 微观紧凑极限（默认 0.15 = 15%%）")
    stage2.add_argument("--bottom-rebound", type=float, default=1.30,
                        help="脱离底部倍数（默认 1.30 = 30%%反弹）")
    stage2.add_argument("--near-high", type=float, default=0.85,
                        help="逼近前高比例（默认 0.85 = 15%%内）")
    stage2.add_argument("--yang-threshold", type=float, default=7.0,
                        help="大阳线涨幅阈值%%（默认 7.0）")

    # 基本面过滤器参数
    fund = parser.add_argument_group("基本面过滤器参数")
    fund.add_argument("--min-revenue-yoy", type=float, default=20.0,
                      help="最低营收同比增长%%（默认 20.0）")
    fund.add_argument("--no-eps-check", action="store_true",
                      help="禁用 EPS 环比加速检查")
    fund.add_argument("--no-fundamental", action="store_true",
                      help="完全跳过基本面过滤")

    return parser.parse_args()


async def main():
    """异步主函数。"""
    args = parse_args()
    setup_logging(args.log_level)

    from app.services.screener.filters import FundamentalFilterConfig, Stage2FilterConfig
    from app.services.screener.pipeline import ScreenerPipeline

    # 组装配置
    stage2_config = Stage2FilterConfig(
        volume_ratio=args.volume_ratio,
        vcp_contraction_ratio=args.vcp_contraction_ratio,
        max_tightness_threshold=args.max_tightness,
        bottom_rebound_pct=args.bottom_rebound,
        near_high_pct=args.near_high,
        big_yang_threshold=args.yang_threshold,
    )

    fundamental_config = FundamentalFilterConfig(
        min_revenue_yoy=args.min_revenue_yoy,
        eps_acceleration=not args.no_eps_check,
    )

    # 如果跳过基本面，设一个极宽松的配置
    if args.no_fundamental:
        fundamental_config.min_revenue_yoy = -9999
        fundamental_config.eps_acceleration = False

    pipeline = ScreenerPipeline(
        stage2_config=stage2_config,
        fundamental_config=fundamental_config,
        dry_run=args.dry_run,
    )

    result = await pipeline.run()

    # 设置退出码
    if result.get("errors") and not result.get("watchlist"):
        sys.exit(1)

    return result


if __name__ == "__main__":
    asyncio.run(main())
