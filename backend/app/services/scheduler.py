"""APScheduler integration — periodic pipeline execution.

Schedule: Every hour from PIPELINE_START_HOUR to PIPELINE_END_HOUR (Asia/Shanghai).
Default:  07:00 ~ 23:00 (=00:00), i.e. 7, 8, 9, ..., 22, 23 → 17 runs/day.

misfire_grace_time is set to 600s (10 min) so that jobs delayed by slow
container startup, DB health-checks, or transient load spikes are still
executed instead of silently skipped (APScheduler default is only 1s).
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_MISSED, EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from app.config import settings
from app.services.pipeline import run_pipeline
from app.services.notifier import send_alert

logger = logging.getLogger("alphareader.scheduler")

# ── Misfire tolerance ──
# Allow up to 10 minutes of delay before considering a job misfired.
# Covers: slow container boot, DB/Redis health-check waits, transient load.
MISFIRE_GRACE_TIME = 60 * 10  # 600 seconds

scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)


def _fire_alert(title: str, message: str) -> None:
    """Schedule an async alert without blocking the listener callback."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(send_alert(title, message))
        else:
            asyncio.run(send_alert(title, message))
    except Exception:
        logger.debug("Could not schedule alert send", exc_info=True)


def _scheduler_listener(event):
    """Log scheduler events and send alerts on failure/misfire."""
    if event.code == EVENT_JOB_MISSED:
        msg = (
            f"Job MISSED: job_id={event.job_id}, "
            f"scheduled={getattr(event, 'scheduled_run_time', 'N/A')}, "
            f"misfire_grace_time={MISFIRE_GRACE_TIME}s exceeded"
        )
        logger.warning(msg)
        _fire_alert("⚠️ Pipeline Job Missed", msg)

    elif event.code == EVENT_JOB_ERROR:
        exc_text = traceback.format_exception(
            type(event.exception), event.exception,
            event.exception.__traceback__,
        ) if event.exception else ["Unknown error"]
        msg = f"Job ERROR: job_id={event.job_id}\n{''.join(exc_text[-3:])}"
        logger.error(msg)
        _fire_alert("🔴 Pipeline Job Failed", msg)

    elif event.code == EVENT_JOB_EXECUTED:
        logger.info("Job EXECUTED: job_id=%s, retval=%s", event.job_id, event.retval)


async def _pipeline_job():
    """Wrapper to catch exceptions so the scheduler keeps running."""
    try:
        logger.info("Pipeline job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        result = await run_pipeline()
        logger.info("Scheduled pipeline result: %s", result)
        return result
    except Exception as e:
        logger.exception("Pipeline job failed: %s", e)
        # Also send alert directly for exceptions caught here
        await send_alert(
            "🔴 Pipeline Exception",
            f"{type(e).__name__}: {e}",
        )
        raise  # Re-raise so APScheduler records it as EVENT_JOB_ERROR


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

    # Register event listener for missed/error/executed events
    scheduler.add_listener(_scheduler_listener, EVENT_JOB_MISSED | EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

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
        misfire_grace_time=MISFIRE_GRACE_TIME,
        # Use timezone-aware "now" so it matches the scheduler's Asia/Shanghai clock
        next_run_time=datetime.now(tz=pytz.timezone(settings.TIMEZONE)),
    )
    scheduler.start()

    alert_status = "enabled" if settings.ALERT_WEBHOOK_URL else "disabled"
    job = scheduler.get_job("news_pipeline")
    next_fire = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if job and job.next_run_time else "N/A"
    logger.info(
        "Scheduler started — pipeline runs hourly %d:00–%d:00 (%s), "
        "misfire_grace_time=%ds, alerts=%s, next run: %s",
        start_h, end_h, settings.TIMEZONE, MISFIRE_GRACE_TIME, alert_status, next_fire,
    )


def stop_scheduler():
    """Gracefully shutdown the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
