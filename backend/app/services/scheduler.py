"""APScheduler integration — periodic pipeline execution.

Schedule: Every hour from PIPELINE_START_HOUR to PIPELINE_END_HOUR (Asia/Shanghai).
Default:  07:00 ~ 23:00 (=00:00), i.e. 7, 8, 9, ..., 22, 23 → 17 runs/day.
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.pipeline import run_pipeline

logger = logging.getLogger("alphareader.scheduler")

scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)


async def _pipeline_job():
    """Wrapper to catch exceptions so the scheduler keeps running."""
    try:
        logger.info("Pipeline job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        result = await run_pipeline()
        logger.info("Scheduled pipeline result: %s", result)
    except Exception as e:
        logger.exception("Pipeline job failed: %s", e)


def start_scheduler():
    """Register cron job and start the scheduler.

    Runs pipeline every hour between PIPELINE_START_HOUR and PIPELINE_END_HOUR.
    Also runs once immediately on startup (next_run_time=now).
    """
    start_h = settings.PIPELINE_START_HOUR
    end_h = settings.PIPELINE_END_HOUR

    # Build hour range: e.g. "7-23" means 7,8,...,23
    # If end_h == 24 (midnight), use 23 as the last hour (cron 0-23 range)
    cron_end = min(end_h, 23)
    hour_expr = f"{start_h}-{cron_end}"

    scheduler.add_job(
        _pipeline_job,
        trigger=CronTrigger(
            hour=hour_expr,
            minute=0,
            timezone=settings.TIMEZONE,
        ),
        id="news_pipeline",
        name=f"News Pipeline (hourly {start_h}:00–{end_h}:00 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(),  # run immediately on startup
    )
    scheduler.start()

    job = scheduler.get_job("news_pipeline")
    next_fire = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if job and job.next_run_time else "N/A"
    logger.info(
        "Scheduler started — pipeline runs hourly %d:00–%d:00 (%s), next run: %s",
        start_h, end_h, settings.TIMEZONE, next_fire,
    )


def stop_scheduler():
    """Gracefully shutdown the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
