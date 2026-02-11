"""定时调度器 — 基于 APScheduler 的周期性 Pipeline 执行。

调度策略：
  - 每 PIPELINE_INTERVAL_MINUTES 分钟执行一次（默认 15 分钟，即每小时 4 次）
  - 运行时间范围：PIPELINE_START_HOUR ~ PIPELINE_END_HOUR（默认全天 0~23）
  - 时区：Asia/Shanghai

关键配置：
  - misfire_grace_time = 600 秒（10 分钟）
    APScheduler 默认只容忍 1 秒延迟就跳过任务，600 秒可以容忍容器启动慢、
    数据库健康检查、瞬时负载高峰等情况，避免静默跳过任务
  - max_instances = 1，防止上一轮未完成时重复触发
  - 启动时立即执行一次（next_run_time=now），不等到下一个调度点

告警集成：
  - 任务失败/异常/跳过时，通过 notifier 发送 Webhook 告警
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

# ── 延迟容忍配置 ──
# 允许最多 10 分钟的延迟，超过后才视为"错过"（misfire）
# 覆盖场景：容器冷启动慢、DB/Redis 健康检查等待、瞬时负载高峰
MISFIRE_GRACE_TIME = 60 * 10  # 600 秒

scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)


def _fire_alert(title: str, message: str) -> None:
    """异步发送告警，不阻塞调度器的监听回调。

    检测当前事件循环状态：若已运行则 create_task，否则 asyncio.run。
    发送失败不抛异常，仅记录 debug 日志。
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(send_alert(title, message))
        else:
            asyncio.run(send_alert(title, message))
    except Exception:
        logger.debug("Could not schedule alert send", exc_info=True)


def _scheduler_listener(event):
    """调度器事件监听器 — 记录日志并在失败/跳过时发送告警。

    监听三种事件：
      - EVENT_JOB_MISSED:   任务被跳过（延迟超过 misfire_grace_time）
      - EVENT_JOB_ERROR:    任务执行出错
      - EVENT_JOB_EXECUTED: 任务成功执行（仅记录日志）
    """
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
    """Pipeline 执行包装器 — 捕获异常以确保调度器不会崩溃。

    异常处理策略：
      1. 捕获异常 → 记录完整堆栈 → 发送告警
      2. 重新抛出 → 让 APScheduler 记录为 EVENT_JOB_ERROR
    """
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
    """注册 Cron 定时任务并启动调度器。

    - 每 PIPELINE_INTERVAL_MINUTES 分钟执行一次（默认 15 分钟）
    - 运行时间范围：PIPELINE_START_HOUR ~ PIPELINE_END_HOUR
    - 启动时立即执行一次（next_run_time=now），不等待下一个调度点
    - max_instances=1 防止任务堆叠
    """
    start_h = settings.PIPELINE_START_HOUR
    end_h = settings.PIPELINE_END_HOUR
    interval = settings.PIPELINE_INTERVAL_MINUTES

    # Build hour range: e.g. "7-23" means 7,8,...,23
    # If end_h == 24 (midnight), use 23 as the last hour (cron 0-23 range)
    cron_end = min(end_h, 23)
    hour_expr = f"{start_h}-{cron_end}"

    # Build minute expression: e.g. interval=15 → "0,15,30,45"
    minute_expr = ",".join(str(m) for m in range(0, 60, interval))

    # Register event listener for missed/error/executed events
    scheduler.add_listener(_scheduler_listener, EVENT_JOB_MISSED | EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    scheduler.add_job(
        _pipeline_job,
        trigger=CronTrigger(
            hour=hour_expr,
            minute=minute_expr,
            timezone=settings.TIMEZONE,
        ),
        id="news_pipeline",
        name=f"News Pipeline (every {interval}min, {start_h}:00–{end_h}:00 {settings.TIMEZONE})",
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
        "Scheduler started — pipeline runs every %dmin, %d:00–%d:00 (%s), "
        "misfire_grace_time=%ds, alerts=%s, next run: %s",
        interval, start_h, end_h, settings.TIMEZONE, MISFIRE_GRACE_TIME, alert_status, next_fire,
    )


def stop_scheduler():
    """优雅关闭调度器（不等待正在执行的任务）。"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
