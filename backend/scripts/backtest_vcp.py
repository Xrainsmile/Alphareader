"""VCP 算法回测脚本（P2：阈值校准）。

对 stock_daily_quote 中每个市场、每个标的、过去 N 个交易日，
用滑动窗口跑 detect_vcp，统计「命中 VCP」后 5/10/20/60 日收益分布，
并与「随机买入」基准对比，用于校准宽松阈值。

运行（容器内）：
  docker compose run --rm -v /home/Alphareader/backend:/app web \\
      python scripts/backtest_vcp.py --market CN --max-symbols 200 --step 5

可选参数：
  --market {CN,US,HK,ALL}   回测市场（默认 ALL，HK 无数据则跳过）
  --start-date YYYY-MM-DD   起始日（默认 2 年前）
  --max-symbols N           限制标的数量（抽样，加速），0=全部
  --step N                  每隔 N 个交易日评估一次（默认 5，减少计算量）
  --window N                分析窗口交易日数（默认 90）
  --out PATH                CSV 输出路径（默认 /tmp/vcp_backtest.csv）
  --sensitivity            额外跑阈值敏感性扫描（较慢）
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import statistics
from datetime import date, datetime, timedelta

from sqlalchemy import select, text

from app.database import async_session
from app.models.stock import StockDailyQuote
from app.services.vcp_detector import (
    detect_vcp,
    ZIGZAG_THRESHOLD, AMP_DECAY_RATIO, LAST_AMP_MAX,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backtest_vcp")

WINDOW = 90
HORIZONS = (5, 10, 20, 60)


async def load_market_bars(market: str, start_date: date, max_symbols: int) -> dict[str, list[dict]]:
    """加载某市场全部标的的日K线（按代码分组、按日期升序）。"""
    async with async_session() as session:
        # 先取有数据的代码（限定 start_date 之后）
        codes_res = await session.execute(
            select(StockDailyQuote.ts_code)
            .where(StockDailyQuote.market == market)
            .where(StockDailyQuote.trade_date >= start_date)
            .distinct()
        )
        codes = [r[0] for r in codes_res.all()]
    if max_symbols and max_symbols > 0:
        codes = codes[:max_symbols]
    if not codes:
        return {}

    out: dict[str, list[dict]] = {}
    # 分批避免单条 SQL 过大
    for i in range(0, len(codes), 200):
        batch = codes[i: i + 200]
        async with async_session() as session:
            res = await session.execute(
                select(
                    StockDailyQuote.ts_code, StockDailyQuote.trade_date,
                    StockDailyQuote.open, StockDailyQuote.high,
                    StockDailyQuote.low, StockDailyQuote.close, StockDailyQuote.volume,
                ).where(StockDailyQuote.market == market)
                .where(StockDailyQuote.ts_code.in_(batch))
                .where(StockDailyQuote.trade_date >= start_date)
                .order_by(StockDailyQuote.ts_code, StockDailyQuote.trade_date)
            )
            for ts_code, td, o, h, l, c, v in res.all():
                out.setdefault(ts_code, []).append({
                    "date": td,
                    "open": float(o) if o is not None else 0.0,
                    "high": float(h) if h is not None else 0.0,
                    "low": float(l) if l is not None else 0.0,
                    "close": float(c) if c is not None else 0.0,
                    "volume": float(v) if v is not None else 0.0,
                })
    logger.info("市场 %s 加载 %d 只标的", market, len(out))
    return out


def _forward_returns(bars: list[dict], d: int) -> dict[int, float]:
    today = bars[d]["close"]
    if today <= 0:
        return {}
    out = {}
    for k in HORIZONS:
        if d + k < len(bars):
            out[k] = (bars[d + k]["close"] - today) / today
    return out


async def run_backtest(market: str, start_date: date, max_symbols: int, step: int,
                       window: int, params: dict | None = None,
                       collect_baseline: bool = True) -> list[dict]:
    bars_by_code = await load_market_bars(market, start_date, max_symbols)
    hits: list[dict] = []
    baseline: list[float] = []  # 随机买入基准（所有评估日的 20 日收益）

    for code, bars in bars_by_code.items():
        n = len(bars)
        # 从第 window 根起，每隔 step 评估一次
        for d in range(window - 1, n, step):
            window_bars = bars[max(0, d - window + 1): d + 1]
            if len(window_bars) < window * 0.6:
                continue
            # 基准：所有评估日的 20 日收益（随机抽样对照）
            if collect_baseline and 20 in _forward_returns(bars, d):
                baseline.append(_forward_returns(bars, d)[20])
            res = detect_vcp(window_bars, params=params)
            if not res.get("vcp_detected"):
                continue
            fwd = _forward_returns(bars, d)
            if not fwd:
                continue
            hits.append({
                "market": market, "ts_code": code,
                "date": bars[d]["date"].isoformat(),
                "pivot": res.get("pivot_suggested"),
                "contractions": res.get("contractions"),
                "near_pivot": res.get("near_pivot"),
                "fwd5": round(fwd.get(5, 0.0) * 100, 2),
                "fwd10": round(fwd.get(10, 0.0) * 100, 2),
                "fwd20": round(fwd.get(20, 0.0) * 100, 2),
                "fwd60": round(fwd.get(60, 0.0) * 100, 2) if 60 in fwd else None,
            })

    if baseline:
        base_median = statistics.median(baseline)
        base_win = sum(1 for x in baseline if x > 0) / len(baseline)
        logger.info("市场 %s 基准(随机买入20日): 中位=%.2f%% 胜率=%.1f%% n=%d",
                    market, base_median * 100, base_win * 100, len(baseline))
    return hits


def _summarize(market: str, hits: list[dict]) -> dict:
    if not hits:
        return {"market": market, "hits": 0}
    stats = {"market": market, "hits": len(hits)}
    for k in HORIZONS:
        col = f"fwd{k}"
        vals = [h[col] for h in hits if h.get(col) is not None]
        if vals:
            stats[f"fwd{k}_median"] = round(statistics.median(vals), 2)
            stats[f"fwd{k}_mean"] = round(statistics.mean(vals), 2)
            stats[f"fwd{k}_win"] = round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)
    near = [h for h in hits if h.get("near_pivot")]
    stats["near_pivot_hits"] = len(near)
    return stats


async def _sensitivity(market: str, start_date: date, max_symbols: int, step: int, window: int):
    """扫描关键阈值对 20 日胜率的影响。"""
    variants = [
        ("relaxed(zig=2%,amp≤90%)", {"zigzag": 0.02, "amp_decay": 0.90, "last_amp": 0.08}),
        ("mid(zig=3%,amp≤85%)", {"zigzag": 0.03, "amp_decay": 0.85, "last_amp": 0.05}),
        ("strict(zig=3%,amp≤80%)", {"zigzag": 0.03, "amp_decay": 0.80, "last_amp": 0.04}),
    ]
    print("\n=== 阈值敏感性（市场 %s，20日胜率）===" % market)
    for name, params in variants:
        hits = await run_backtest(market, start_date, max_symbols, step, window,
                                  params=params, collect_baseline=False)
        s = _summarize(market, hits)
        print(f"  {name:28s} 命中={s['hits']:5d}  20日胜率={s.get('fwd20_win','-')}%  "
              f"20日中位={s.get('fwd20_median','-')}%")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="ALL", choices=["CN", "US", "HK", "ALL"])
    ap.add_argument("--start-date", default=None)
    ap.add_argument("--max-symbols", type=int, default=0)
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--out", default="/tmp/vcp_backtest.csv")
    ap.add_argument("--sensitivity", action="store_true")
    args = ap.parse_args()

    if args.start_date:
        start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    else:
        start = date.today() - timedelta(days=730)

    markets = ["CN", "US", "HK"] if args.market == "ALL" else [args.market]
    all_hits: list[dict] = []
    for m in markets:
        logger.info("=== 回测市场 %s ===", m)
        if args.sensitivity:
            await _sensitivity(m, start, args.max_symbols or 100, args.step, args.window)
        hits = await run_backtest(m, start, args.max_symbols, args.step, args.window)
        s = _summarize(m, hits)
        logger.info("市场 %s 汇总: %s", m, s)
        all_hits.extend(hits)

    if all_hits:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            cols = ["market", "ts_code", "date", "pivot", "contractions",
                    "near_pivot", "fwd5", "fwd10", "fwd20", "fwd60"]
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(all_hits)
        logger.info("CSV 已写出: %s (%d 条命中)", args.out, len(all_hits))
    else:
        logger.warning("无任何 VCP 命中，请检查数据或放宽阈值")


if __name__ == "__main__":
    asyncio.run(main())
