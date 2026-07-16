"""VCP 算法结果批量回填脚本。

将 VCP 形态识别结果写入 sepa_watchlist_items.vcp_auto 列（不写库行情，仅读
stock_daily_quote；与人工 vcp_confirmed 决策独立）。

运行（容器内）：
  docker compose run --rm -v /home/Alphareader/backend:/app web \\
      python scripts/refresh_vcp.py
  docker compose run --rm -v /home/Alphareader/backend:/app web \\
      python scripts/refresh_vcp.py --market CN --force
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from app.services.sepa_service import refresh_vcp_watchlist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("refresh_vcp")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default=None, help="仅回填该市场（CN/HK/US），留空全市场")
    ap.add_argument("--force", action="store_true",
                    help="全量重算（默认跳过已有 vcp_auto 的标的）")
    args = ap.parse_args()

    summary = await refresh_vcp_watchlist(market=args.market, force=args.force)
    logger.info("VCP 批量回填完成: %s", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
