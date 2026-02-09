"""APScheduler integration — periodic pipeline execution."""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.services.pipeline import run_pipeline

logger = logging.getLogger("alphareader.scheduler")

scheduler = AsyncIOScheduler()


async def _pipeline_job():
    """Wrapper to catch exceptions so the scheduler keeps running."""
    try:
        result = await run_pipeline()
        logger.info("Scheduled pipeline result: %s", result)
    except Exception as e:
        logger.exception("Pipeline job failed: %s", e)


def start_scheduler():
    """Register jobs and start the scheduler."""
    scheduler.add_job(
        _pipeline_job,
        trigger=IntervalTrigger(hours=settings.PIPELINE_INTERVAL_HOURS),
        id="news_pipeline",
        name=f"News Pipeline (every {settings.PIPELINE_INTERVAL_HOURS}h)",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(),  # run immediately on startup
    )
    scheduler.start()
    logger.info(
        "Scheduler started — pipeline runs every %dh (first run: now)",
        settings.PIPELINE_INTERVAL_HOURS,
    )


def stop_scheduler():
    """Gracefully shutdown the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
