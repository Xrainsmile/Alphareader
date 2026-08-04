"""手动推送最新阶段简报（Reports：早间/午间/傍晚/夜间）到企微群机器人。

从 news_digests 表读取指定日期/时段的简报 structured_content，
构建企微纯文本摘要（含原文链接）并推送。用于补推或验证。

用法（容器内）：
  docker compose run -e PYTHONPATH=/app web python scripts/push_latest_digest.py
  docker compose run -e PYTHONPATH=/app web python scripts/push_latest_digest.py --period morning
  docker compose run -e PYTHONPATH=/app web python scripts/push_latest_digest.py --date 2026-08-04 --period evening

前置：.env 已配置 ALERT_WEBHOOK_URL 为企微群机器人 webhook。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.news_digest import NewsDigest
from app.services.digest_service import build_wecom_digest_summary
from app.services.notifier import send_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("push_latest_digest")

PERIODS = ["morning", "midday", "evening", "night"]


async def _push_one(d: NewsDigest) -> bool:
    if not d.structured_content:
        logger.warning("digest id=%s 无 structured_content，跳过", d.id)
        return False
    text = build_wecom_digest_summary(d.structured_content, d.period_label, d.id)
    await send_report(text)
    return True


async def main(date_str: str | None, period: str | None) -> None:
    if not settings.ALERT_WEBHOOK_URL:
        logger.error("ALERT_WEBHOOK_URL 未配置，无法推送。请先在 .env 设置企微群机器人 webhook。")
        return
    target = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    periods = [period] if period else PERIODS
    async with async_session() as db:
        for p in periods:
            stmt = (
                select(NewsDigest)
                .where(NewsDigest.digest_date == target, NewsDigest.period_label == p)
                .order_by(NewsDigest.id.desc())
            )
            d = (await db.execute(stmt)).scalar_one_or_none()
            if not d:
                logger.warning("%s %s 无简报，跳过", target, p)
                continue
            ok = await _push_one(d)
            if ok:
                logger.info("已推送 %s %s (digest id=%s)", target, p, d.id)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="推送最新阶段简报到企微群机器人")
    ap.add_argument("--date", help="指定日期 YYYY-MM-DD，默认今天")
    ap.add_argument("--period", choices=PERIODS, help="只推送某个时段")
    args = ap.parse_args()
    asyncio.run(main(args.date, args.period))
