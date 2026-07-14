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
from app.services.indicators import compute_and_save_rs_rating
from app.services.data_fetcher import incremental_update_quotes
from app.services.sandbox_nav import compute_nav_core
from app.services.screener.pipeline import ScreenerPipeline
from app.services.screener.trend_pipeline import TrendPipeline
from app.services.briefing_service import generate_briefing
from app.services.catalyst_aggregator import run_catalyst_aggregation
from app.services.digest_service import generate_digest

logger = logging.getLogger("alphareader.scheduler")

# ── 分布式调度锁（多 worker 场景）──
# gunicorn 多 worker 时，每个 worker 都会启动自己的 AsyncIOScheduler。
# 若不加锁，多个 worker 会各自独立跑 pipeline，造成重复抓取 / 重复入库。
# 用 Redis SET NX 保证同一时刻只有一个 worker 持有调度权。
# 锁带 TTL：持有锁的 worker 异常退出后，其他 worker 能在 TTL 内接管。
SCHEDULER_LOCK_KEY = "alphareader:scheduler_lock"
SCHEDULER_LOCK_TTL = 3600  # 1 小时


async def _try_acquire_scheduler_lock() -> bool:
    """尝试获取分布式调度锁（Redis SET NX）。

    Returns:
        True  → 本 worker 成功获取锁，应启动调度器
        False → 锁已被其他 worker 持有，本 worker 不应启动调度器
    """
    try:
        from app.redis import get_redis
        r = get_redis()
        acquired = await r.set(SCHEDULER_LOCK_KEY, "1", nx=True, ex=SCHEDULER_LOCK_TTL)
        return bool(acquired)
    except Exception as e:
        # Redis 不可用等异常 → fail-open：仍启动调度器（pipeline 去重层会兜住重复）
        logger.warning("[scheduler] 获取调度锁失败（fail-open，仍启动调度器）: %s", e)
        return True


def _release_scheduler_lock_bg():
    """后台线程释放调度锁，避免 shutdown 时阻塞事件循环。"""
    try:
        import redis
        from app.config import settings
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.delete(SCHEDULER_LOCK_KEY)
    except Exception:
        pass


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


async def _rs_rating_job():
    """RS Rating 定时计算 — 每个交易日 11:30 和 15:00 触发。

    流程：
      1. 先增量更新行情数据（只拉最近 10 天，~10 分钟）
      2. 再计算 RS Rating（SQL 模式，几秒完成）

    11:30: 午盘结束后计算（上午行情）
    15:00: 收盘后计算最终结果
    """
    try:
        logger.info("RS Rating job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # Step 1: 增量更新行情数据
        try:
            updated = await incremental_update_quotes(days=10)
            logger.info("行情增量更新完成: %d 条记录", updated)
        except Exception as e:
            logger.warning("行情增量更新失败（继续用已有数据计算）: %s", e)

        # Step 2: 计算 RS Rating
        df = await compute_and_save_rs_rating(force_refresh=True)
        logger.info("RS Rating job completed: %d stocks", len(df))
        return {"status": "ok", "count": len(df)}
    except Exception as e:
        logger.exception("RS Rating job failed: %s", e)
        await send_alert(
            "🔴 RS Rating Job Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _sandbox_nav_job():
    """模拟仓 NAV 计算 — 每个交易日 11:35 和 15:35 各触发一次。

    11:35：午盘收盘（11:30）后计算，反映半日行情变化。
    15:35：尾盘收盘（15:00）后计算，确保当日最终净值。
    执行前先更新观察池中 ETF 标的的行情数据。
    复用 sandbox API 中的核心计算函数，避免代码重复。
    """
    from datetime import date as date_type
    from app.database import async_session
    from app.services.data_fetcher import fetch_sandbox_etf_quotes

    try:
        logger.info("Sandbox NAV job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # 先更新 ETF 行情，确保 NAV 计算有最新数据
        try:
            etf_count = await fetch_sandbox_etf_quotes()
            if etf_count > 0:
                logger.info("ETF 行情已更新，共 %d 条记录", etf_count)
        except Exception as etf_err:
            logger.warning("ETF 行情更新失败（不影响 NAV 计算）: %s", etf_err)

        calc_date = date_type.today()

        async with async_session() as db:
            result = await compute_nav_core(db, calc_date, use_realtime=True)

        if result is None:
            logger.info("Sandbox NAV: No trades yet, skipping")
            return {"status": "skip", "reason": "no trades"}

        logger.info(
            "Sandbox NAV computed: date=%s, nav=%.4f, pnl=%.2f%%",
            calc_date, result["nav"], result["total_pnl"],
        )
        return {"status": "ok", "nav": result["nav"], "pnl": result["total_pnl"]}

    except Exception as e:
        logger.exception("Sandbox NAV job failed: %s", e)
        await send_alert(
            "🔴 Sandbox NAV Job Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _screener_job():
    """Screener 每日选股 — 每个交易日 15:40 触发。

    比 sandbox_nav (15:35) 延后 5 分钟，避免同时占用资源。
    结果自动写入数据库（ScreenerRun + WatchlistDaily）。
    """
    try:
        logger.info("Screener job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        pipeline = ScreenerPipeline()
        result = await pipeline.run()

        final_count = result.get("stats", {}).get("final_count", 0)
        logger.info("Screener job completed: %d stocks in watchlist", final_count)
        return {"status": "ok", "count": final_count}
    except Exception as e:
        logger.exception("Screener job failed: %s", e)
        await send_alert(
            "🔴 Screener Job Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _trend_screener_job():
    """右侧趋势 Screener 每日选股 — 每个交易日 15:45 触发。

    比 VCP Screener (15:40) 延后 5 分钟，避免同时占用资源。
    结果自动写入数据库（TrendScreenerRun + TrendWatchlistDaily）。
    """
    try:
        logger.info("Trend Screener job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        pipeline = TrendPipeline()
        result = await pipeline.run()

        final_count = len(result.get("watchlist", []))
        logger.info("Trend Screener job completed: %d stocks in watchlist", final_count)
        return {"status": "ok", "count": final_count}
    except Exception as e:
        logger.exception("Trend Screener job failed: %s", e)
        await send_alert(
            "🔴 Trend Screener Job Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _digest_job(period_label: str):
    """新闻概览摘要生成任务 — 收集指定时段新闻并调用 DeepSeek 总结。

    四个时段：
      - morning (08:30): 收集 00:00~08:30 新闻
      - midday  (12:00): 收集 08:30~12:00 新闻
      - evening (18:00): 收集 12:00~18:00 新闻
      - night   (00:00): 收集 18:00~24:00 新闻（次日凌晨触发）
    """
    try:
        logger.info("Digest job [%s] triggered at %s", period_label, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        result = await generate_digest(period_label)
        logger.info("Digest job [%s] completed: %s", period_label, result)
        return result
    except Exception as e:
        logger.exception("Digest job [%s] failed: %s", period_label, e)
        await send_alert(
            f"🔴 Digest Job [{period_label}] Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _briefing_job():
    """每日综合分析报告 — 工作日 16:00 触发（所有 screener 跑完后）。

    聚合 VCP/趋势白名单 + 行情 + 新闻概览 + 模拟仓，
    调用 DeepSeek 生成含交易建议的分析报告。
    """
    try:
        logger.info("Briefing job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        result = await generate_briefing()
        logger.info("Briefing job completed: %s", result)
        return result
    except Exception as e:
        logger.exception("Briefing job failed: %s", e)
        await send_alert(
            "🔴 Daily Briefing Job Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _us_quotes_job():
    """美股行情增量更新 — 每天 05:30（北京时间）触发。

    对应美东 16:30 盘后，确保当天收盘数据可用。
    数据源：腾讯财经（主力）+ yfinance（fallback）+ 交叉验证。
    """
    try:
        from app.services.us_data_fetcher import incremental_update_us_quotes, get_all_us_stock_data, has_us_today_data

        logger.info("US Quotes job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # 检查 DB 是否已有美股基础数据
        has_data = await has_us_today_data(min_stocks=50)
        if has_data:
            # 增量更新
            count = await incremental_update_us_quotes(days=10)
            logger.info("US Quotes incremental update: %d records", count)
        else:
            # 首次或数据缺失：全量下载
            df = await get_all_us_stock_data(force_refresh=True)
            logger.info("US Quotes full download: %d records", len(df))

        return {"status": "ok"}
    except Exception as e:
        logger.exception("US Quotes job failed: %s", e)
        await send_alert(
            "🔴 US Quotes Job Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _us_screener_job():
    """美股 VCP Screener — 每天 05:40（北京时间）触发。

    在美股行情更新（05:30）完成后运行。
    使用 market='US' 的 ScreenerPipeline。
    """
    try:
        logger.info("US Screener job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        pipeline = ScreenerPipeline(market="US")
        result = await pipeline.run()

        final_count = result.get("stats", {}).get("final_count", 0)
        logger.info("US Screener job completed: %d stocks in watchlist", final_count)
        return {"status": "ok", "count": final_count}
    except Exception as e:
        logger.exception("US Screener job failed: %s", e)
        await send_alert(
            "🔴 US Screener Job Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _us_trend_screener_job():
    """美股趋势 Screener — 每天 05:45（北京时间）触发。

    在美股 VCP Screener（05:40）之后运行。
    使用 market='US' 的 TrendPipeline。
    """
    try:
        logger.info("US Trend Screener job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        pipeline = TrendPipeline(market="US")
        result = await pipeline.run()

        final_count = len(result.get("watchlist", []))
        logger.info("US Trend Screener job completed: %d stocks in watchlist", final_count)
        return {"status": "ok", "count": final_count}
    except Exception as e:
        logger.exception("US Trend Screener job failed: %s", e)
        await send_alert(
            "🔴 US Trend Screener Job Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _catalyst_job():
    """催化剂标的聚合 — 工作日 08:45 和 15:50 触发。

    08:45: 盘前，基于隔夜+早间新闻提取催化剂标的
    15:50: 盘后，基于全天新闻更新催化剂标的（在 Briefing 16:00 之前跑完）

    聚合高分新闻中的 A 股标的，与 VCP/趋势白名单交叉验证。
    """
    try:
        logger.info("Catalyst aggregation job triggered at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        result = await run_catalyst_aggregation()
        logger.info("Catalyst aggregation job completed: %s", result)
        return result
    except Exception as e:
        logger.exception("Catalyst aggregation job failed: %s", e)
        await send_alert(
            "🔴 Catalyst Aggregation Job Failed",
            f"{type(e).__name__}: {e}",
        )
        raise


async def _index_fetch_job(market: str):
    """指数日行情采集 — 行情更新后触发，写入 index_daily。

    失败不阻断：适配度服务在指数缺失时自动改用合成代理。
    """
    try:
        logger.info("指数采集任务触发（market=%s）at %s", market,
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        from app.services.index_fetcher import fetch_indices
        summary = await fetch_indices(market)
        logger.info("指数采集(%s)完成: %s", market, summary)
        return summary
    except Exception as e:
        logger.exception("指数采集(%s)失败: %s", market, e)
        await send_alert("🔴 Index Fetch Job Failed", f"market={market} {type(e).__name__}: {e}")
        raise


async def _vcp_suitability_job(market: str):
    """VCP 市场适配度日终计算 — 写入 market_adaptability。"""
    try:
        logger.info("VCP 适配度计算触发（market=%s）at %s", market,
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        from app.services.vcp_suitability import compute_vcp_adaptability
        from datetime import date as _date
        result = await compute_vcp_adaptability(market, _date.today(), save=True)
        logger.info("VCP 适配度(%s)完成: level=%s score=%s",
                    market, result["level"], result["total_score"])
        return result
    except Exception as e:
        logger.exception("VCP 适配度计算(%s)失败: %s", market, e)
        await send_alert("🔴 VCP Suitability Job Failed", f"market={market} {type(e).__name__}: {e}")
        raise


async def start_scheduler():
    """注册 Cron 定时任务并启动调度器。

    - 每 PIPELINE_INTERVAL_MINUTES 分钟执行一次（默认 15 分钟）
    - 运行时间范围：PIPELINE_START_HOUR ~ PIPELINE_END_HOUR
    - 启动时立即执行一次（next_run_time=now），不等待下一个调度点
    - max_instances=1 防止任务堆叠

    多 worker 场景：只有成功获取 Redis 调度锁的 worker 才真正启动调度器，
    其余 worker 仅承担 API 请求处理，避免重复跑 pipeline 并防止 pipeline
    跑批时阻塞全部 worker 导致 API 超时。
    """
    # ── 分布式锁：仅一个 worker 拥有调度权 ──
    try:
        acquired = await _try_acquire_scheduler_lock()
    except Exception:
        acquired = True  # 极端情况下 fail-open

    if not acquired:
        logger.info(
            "[scheduler] 本 worker 未获取调度锁（其他 worker 已持有），"
            "跳过调度器启动，仅处理 API 请求"
        )
        return

    logger.info("[scheduler] 本 worker 已获取调度锁，启动定时任务调度器")

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

    # ── RS Rating 定时计算（交易日 11:30 和 15:00）──
    # 拆为两个独立 job，避免 hour+minute 组合产生意外触发点
    scheduler.add_job(
        _rs_rating_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="11",
            minute="30",
            timezone=settings.TIMEZONE,
        ),
        id="rs_rating_1130",
        name=f"RS Rating (Mon-Fri 11:30 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    scheduler.add_job(
        _rs_rating_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="15",
            minute="0",
            timezone=settings.TIMEZONE,
        ),
        id="rs_rating_1500",
        name=f"RS Rating (Mon-Fri 15:00 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── 模拟仓 NAV 计算（交易日 11:35 午盘 + 15:35 尾盘）──
    scheduler.add_job(
        _sandbox_nav_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="11",
            minute="35",
            timezone=settings.TIMEZONE,
        ),
        id="sandbox_nav_1135",
        name=f"Sandbox NAV (Mon-Fri 11:35 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    scheduler.add_job(
        _sandbox_nav_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="15",
            minute="35",
            timezone=settings.TIMEZONE,
        ),
        id="sandbox_nav_1535",
        name=f"Sandbox NAV (Mon-Fri 15:35 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── Screener 每日选股（交易日 15:40，比 NAV 晚 5 分钟）──
    scheduler.add_job(
        _screener_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="15",
            minute="40",
            timezone=settings.TIMEZONE,
        ),
        id="screener_daily",
        name=f"Daily Screener (Mon-Fri 15:40 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── 右侧趋势 Screener（交易日 15:45，比 VCP Screener 晚 5 分钟）──
    scheduler.add_job(
        _trend_screener_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="15",
            minute="45",
            timezone=settings.TIMEZONE,
        ),
        id="trend_screener_daily",
        name=f"Trend Screener (Mon-Fri 15:45 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── 新闻概览 Digest（每天 4 个时段，全天候运行）──
    # 08:30 早间：收集 00:00~08:30
    scheduler.add_job(
        _digest_job,
        args=["morning"],
        trigger=CronTrigger(
            hour="8",
            minute="30",
            timezone=settings.TIMEZONE,
        ),
        id="digest_morning",
        name=f"News Digest Morning (08:30 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # 12:00 午间：收集 08:30~12:00
    scheduler.add_job(
        _digest_job,
        args=["midday"],
        trigger=CronTrigger(
            hour="12",
            minute="0",
            timezone=settings.TIMEZONE,
        ),
        id="digest_midday",
        name=f"News Digest Midday (12:00 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # 18:00 傍晚：收集 12:00~18:00
    scheduler.add_job(
        _digest_job,
        args=["evening"],
        trigger=CronTrigger(
            hour="18",
            minute="0",
            timezone=settings.TIMEZONE,
        ),
        id="digest_evening",
        name=f"News Digest Evening (18:00 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # 00:00 夜间：收集 18:00~24:00（次日凌晨触发）
    scheduler.add_job(
        _digest_job,
        args=["night"],
        trigger=CronTrigger(
            hour="0",
            minute="0",
            timezone=settings.TIMEZONE,
        ),
        id="digest_night",
        name=f"News Digest Night (00:00 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── 美股行情增量更新（每天 05:30 北京时间 ≈ 美东 16:30 盘后）──
    scheduler.add_job(
        _us_quotes_job,
        trigger=CronTrigger(
            hour="5",
            minute="30",
            timezone=settings.TIMEZONE,
        ),
        id="us_quotes_daily",
        name=f"US Quotes Update (Daily 05:30 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── 美股 VCP Screener（每天 05:40，行情更新后）──
    scheduler.add_job(
        _us_screener_job,
        trigger=CronTrigger(
            hour="5",
            minute="40",
            timezone=settings.TIMEZONE,
        ),
        id="us_screener_daily",
        name=f"US VCP Screener (Daily 05:40 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── 美股趋势 Screener（每天 05:45，VCP 之后）──
    scheduler.add_job(
        _us_trend_screener_job,
        trigger=CronTrigger(
            hour="5",
            minute="45",
            timezone=settings.TIMEZONE,
        ),
        id="us_trend_screener_daily",
        name=f"US Trend Screener (Daily 05:45 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── 指数日行情采集（A 股收盘后 15:50 / 美股盘后 05:50）──
    scheduler.add_job(
        _index_fetch_job,
        args=["CN"],
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="15",
            minute="50",
            timezone=settings.TIMEZONE,
        ),
        id="index_fetch_cn",
        name=f"Index Fetch CN (Mon-Fri 15:50 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    scheduler.add_job(
        _index_fetch_job,
        args=["US"],
        trigger=CronTrigger(
            hour="5",
            minute="50",
            timezone=settings.TIMEZONE,
        ),
        id="index_fetch_us",
        name=f"Index Fetch US (Daily 05:50 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── VCP 市场适配度日终计算（A 股 16:10 / 美股 06:10，行情与指数采集之后）──
    scheduler.add_job(
        _vcp_suitability_job,
        args=["CN"],
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="16",
            minute="10",
            timezone=settings.TIMEZONE,
        ),
        id="vcp_suitability_cn",
        name=f"VCP Suitability CN (Mon-Fri 16:10 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    scheduler.add_job(
        _vcp_suitability_job,
        args=["US"],
        trigger=CronTrigger(
            hour="6",
            minute="10",
            timezone=settings.TIMEZONE,
        ),
        id="vcp_suitability_us",
        name=f"VCP Suitability US (Daily 06:10 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── 催化剂标的聚合（工作日 08:45 盘前 + 15:50 盘后，在 Briefing 之前）──
    # 08:45 盘前：基于隔夜+早间新闻提取催化剂标的
    scheduler.add_job(
        _catalyst_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="8",
            minute="45",
            timezone=settings.TIMEZONE,
        ),
        id="catalyst_0845",
        name=f"Catalyst Aggregation AM (Mon-Fri 08:45 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # 15:50 盘后：基于全天新闻更新催化剂标的（在 Briefing 16:00 之前跑完）
    scheduler.add_job(
        _catalyst_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="15",
            minute="50",
            timezone=settings.TIMEZONE,
        ),
        id="catalyst_1550",
        name=f"Catalyst Aggregation PM (Mon-Fri 15:50 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # ── 每日综合分析报告（工作日 09:00 盘前 + 16:00 盘后）──
    # 09:00 盘前研报：基于隔夜新闻 + 前一日选股结果
    scheduler.add_job(
        _briefing_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9",
            minute="0",
            timezone=settings.TIMEZONE,
        ),
        id="daily_briefing_0900",
        name=f"Daily Briefing AM (Mon-Fri 09:00 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    # 16:00 盘后研报：基于全天新闻 + 当日选股结果
    scheduler.add_job(
        _briefing_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="16",
            minute="0",
            timezone=settings.TIMEZONE,
        ),
        id="daily_briefing",
        name=f"Daily Briefing PM (Mon-Fri 16:00 {settings.TIMEZONE})",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_TIME,
    )

    scheduler.start()

    alert_status = "enabled" if settings.ALERT_WEBHOOK_URL else "disabled"
    job = scheduler.get_job("news_pipeline")
    next_fire = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if job and job.next_run_time else "N/A"
    rs_job1 = scheduler.get_job("rs_rating_1130")
    rs_next1 = rs_job1.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if rs_job1 and rs_job1.next_run_time else "N/A"
    rs_job2 = scheduler.get_job("rs_rating_1500")
    rs_next2 = rs_job2.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if rs_job2 and rs_job2.next_run_time else "N/A"
    logger.info(
        "Scheduler started — pipeline runs every %dmin, %d:00–%d:00 (%s), "
        "misfire_grace_time=%ds, alerts=%s, next run: %s",
        interval, start_h, end_h, settings.TIMEZONE, MISFIRE_GRACE_TIME, alert_status, next_fire,
    )
    logger.info("RS Rating scheduled Mon-Fri 11:30 (next: %s) & 15:00 (next: %s)", rs_next1, rs_next2)

    sb_job1 = scheduler.get_job("sandbox_nav_1135")
    sb_next1 = sb_job1.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if sb_job1 and sb_job1.next_run_time else "N/A"
    sb_job2 = scheduler.get_job("sandbox_nav_1535")
    sb_next2 = sb_job2.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if sb_job2 and sb_job2.next_run_time else "N/A"
    logger.info("Sandbox NAV scheduled Mon-Fri 11:35 (next: %s) & 15:35 (next: %s)", sb_next1, sb_next2)

    sc_job = scheduler.get_job("screener_daily")
    sc_next = sc_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if sc_job and sc_job.next_run_time else "N/A"
    logger.info("Screener scheduled Mon-Fri 15:40 (next: %s)", sc_next)

    # Digest jobs status
    for label, desc in [("digest_morning", "08:30"), ("digest_midday", "12:00"),
                        ("digest_evening", "18:00"), ("digest_night", "00:00")]:
        dj = scheduler.get_job(label)
        dn = dj.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if dj and dj.next_run_time else "N/A"
        logger.info("Digest %s scheduled daily %s (next: %s)", label, desc, dn)

    # Daily Briefing status
    bj_am = scheduler.get_job("daily_briefing_0900")
    bn_am = bj_am.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if bj_am and bj_am.next_run_time else "N/A"
    bj_pm = scheduler.get_job("daily_briefing")
    bn_pm = bj_pm.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if bj_pm and bj_pm.next_run_time else "N/A"
    logger.info("Daily Briefing scheduled Mon-Fri 09:00 (next: %s) & 16:00 (next: %s)", bn_am, bn_pm)

    # Catalyst Aggregation status
    cat_am = scheduler.get_job("catalyst_0845")
    cat_am_next = cat_am.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if cat_am and cat_am.next_run_time else "N/A"
    cat_pm = scheduler.get_job("catalyst_1550")
    cat_pm_next = cat_pm.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if cat_pm and cat_pm.next_run_time else "N/A"
    logger.info("Catalyst Aggregation scheduled Mon-Fri 08:45 (next: %s) & 15:50 (next: %s)", cat_am_next, cat_pm_next)

    # US Market jobs status
    us_q = scheduler.get_job("us_quotes_daily")
    us_q_next = us_q.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if us_q and us_q.next_run_time else "N/A"
    us_s = scheduler.get_job("us_screener_daily")
    us_s_next = us_s.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if us_s and us_s.next_run_time else "N/A"
    us_t = scheduler.get_job("us_trend_screener_daily")
    us_t_next = us_t.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if us_t and us_t.next_run_time else "N/A"
    logger.info(
        "US Market scheduled daily: Quotes 05:30 (next: %s), VCP 05:40 (next: %s), Trend 05:45 (next: %s)",
        us_q_next, us_s_next, us_t_next,
    )


def stop_scheduler():
    """优雅关闭调度器（不等待正在执行的任务）。"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    # 释放调度锁，让其他 worker 可立即接管（后台线程执行，不阻塞事件循环）
    import threading
    threading.Thread(target=_release_scheduler_lock_bg, daemon=True).start()
