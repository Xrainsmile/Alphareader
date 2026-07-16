"""港股历史日K线回补脚本。

默认抓取 SEPA 股池中所有 HK 标的；也可用 --codes 指定。
幂等（upsert），可反复运行。

运行（容器内）：
  docker compose run --rm -v /home/Alphareader/backend:/app web \\
      python scripts/backfill_hk_kline.py
  docker compose run --rm -v /home/Alphareader/backend:/app web \\
      python scripts/backfill_hk_kline.py --codes 00700,09988,03690
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.services.hk_data_fetcher import refresh_hk_quotes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_hk_kline")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="", help="逗号分隔的港股代码，如 00700,09988")
    args = ap.parse_args()

    extra = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else None
    written = await refresh_hk_quotes(extra_codes=extra)
    logger.info("港股历史回补完成，写入 %d 条记录", written)


if __name__ == "__main__":
    asyncio.run(main())
