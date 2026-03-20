"""Daily Briefing Service — 每日综合分析报告生成。

盘后自动聚合多维数据，调用 DeepSeek 生成含交易建议的分析报告：
  1. VCP 策略白名单（收敛形态股 + 技术面/基本面）
  2. 右侧趋势白名单（趋势突破股 + ADX/RSI/放量）
  3. 价投观察池（长期跟踪标的 + 当日行情）
  4. 新闻概览（morning + midday + evening 摘要）
  5. 模拟仓净值/盈亏

节省 tokens 策略：
  - 每只股票只传关键指标（不传全部字段）
  - 新闻概览只传 content 前 300 字
  - System Prompt 精简但专业
  - 限制 max_tokens=3000
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import httpx
import pytz
from sqlalchemy import select, and_, func, desc

from app.config import settings
from app.database import async_session
from app.models.daily_briefing import DailyBriefing
from app.models.news_digest import NewsDigest
from app.models.sandbox import SandboxNav, SandboxStock
from app.models.screener import WatchlistDaily, TrendWatchlistDaily
from app.models.stock import StockDailyQuote, StockRSRating

logger = logging.getLogger("alphareader.briefing")

_TZ = pytz.timezone(settings.TIMEZONE)

# ── System Prompt ──

BRIEFING_SYSTEM_PROMPT = """\
你是一位专业的 A 股投资分析师，擅长技术分析和量化策略解读。
请根据以下多维数据（策略选股结果、行情数据、新闻概览、模拟仓状态），生成一份结构化的每日投资分析报告（Markdown 格式）。

## 报告要求

1. **大盘概况**：根据新闻和整体数据，简述今日市场情绪和关键事件
2. **VCP 策略标的分析**：逐一分析 VCP 白名单中的股票，结合价格、成交量、技术指标给出操作建议
3. **趋势策略标的分析**：逐一分析趋势白名单中的股票，结合 ADX/RSI/放量信号给出操作建议
4. **价投观察池追踪**：更新价投标的的最新行情和估值变化
5. **模拟仓回顾**：简述当前净值和仓位表现
6. **明日关注要点**：总结需要重点跟踪的标的和事件

## 风格要求
- 用数据说话，避免空洞的套话
- 每只股票给出明确的操作建议（买入/加仓/持有/观望/减仓/止损）
- 标注关键价位（支撑位、压力位、止损位）
- 中文输出，专业但易读
- 总字数控制在 2000 字以内
"""


# ── 数据收集 ──

async def _fetch_vcp_watchlist(target_date: date) -> list[dict]:
    """获取当日 VCP 策略白名单。"""
    async with async_session() as db:
        stmt = (
            select(WatchlistDaily)
            .where(WatchlistDaily.run_date == target_date)
            .order_by(WatchlistDaily.vcp_score.desc())
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    return [
        {
            "ts_code": r.ts_code,
            "name": r.name or r.ts_code,
            "price": r.current_price,
            "vcp_score": r.vcp_score,
            "ema20": r.ema20,
            "ema50": r.ema50,
            "ema120": r.ema120,
            "eps_growth": r.eps_growth,
            "revenue_yoy": r.revenue_yoy,
            "industry": r.industry,
            "concepts": (r.concepts or "")[:100],
            "fund_flow": r.fund_flow_net,
        }
        for r in rows
    ]


async def _fetch_trend_watchlist(target_date: date) -> list[dict]:
    """获取当日趋势策略白名单。"""
    async with async_session() as db:
        stmt = (
            select(TrendWatchlistDaily)
            .where(TrendWatchlistDaily.run_date == target_date)
            .order_by(TrendWatchlistDaily.trend_score.desc())
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    return [
        {
            "ts_code": r.ts_code,
            "name": r.name or r.ts_code,
            "price": r.current_price,
            "ma20": r.ma20,
            "ma50": r.ma50,
            "adx": r.adx,
            "rsi": r.rsi,
            "volume_ratio": r.volume_ratio,
            "trend_score": r.trend_score,
            "industry": r.industry,
            "concepts": (r.concepts or "")[:100],
            "fund_flow": r.fund_flow_net,
        }
        for r in rows
    ]


async def _fetch_value_stocks() -> list[dict]:
    """获取价投观察池中状态为 watching/holding 的标的。"""
    async with async_session() as db:
        stmt = (
            select(SandboxStock)
            .where(
                and_(
                    SandboxStock.strategy == "value",
                    SandboxStock.status.in_(["watching", "holding"]),
                )
            )
            .order_by(SandboxStock.added_at.desc())
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    return [
        {
            "ts_code": r.ts_code,
            "name": r.name,
            "status": r.status,
            "reason": (r.reason or "")[:100],
        }
        for r in rows
    ]


async def _fetch_stock_quotes(ts_codes: list[str], target_date: date) -> dict[str, dict]:
    """批量获取指定股票的当日行情（如果当日无数据，取最近一个交易日的）。"""
    if not ts_codes:
        return {}

    async with async_session() as db:
        # 先尝试 target_date，如果没有则回退到最近 5 天
        lookback = target_date - timedelta(days=5)
        stmt = (
            select(StockDailyQuote)
            .where(
                and_(
                    StockDailyQuote.ts_code.in_(ts_codes),
                    StockDailyQuote.trade_date >= lookback,
                    StockDailyQuote.trade_date <= target_date,
                )
            )
            .order_by(StockDailyQuote.ts_code, StockDailyQuote.trade_date.desc())
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    # 每只股票取最新一条
    quotes = {}
    for r in rows:
        if r.ts_code not in quotes:
            quotes[r.ts_code] = {
                "close": r.close,
                "pct_change": r.pct_change,
                "volume": r.volume,
                "amount": r.amount,
                "turnover": r.turnover,
                "trade_date": r.trade_date.isoformat(),
            }
    return quotes


async def _fetch_rs_ratings(ts_codes: list[str], target_date: date) -> dict[str, int]:
    """批量获取 RS Rating。"""
    if not ts_codes:
        return {}

    async with async_session() as db:
        lookback = target_date - timedelta(days=5)
        stmt = (
            select(StockRSRating.ts_code, StockRSRating.rs_rating)
            .where(
                and_(
                    StockRSRating.ts_code.in_(ts_codes),
                    StockRSRating.trade_date >= lookback,
                    StockRSRating.trade_date <= target_date,
                )
            )
            .order_by(StockRSRating.ts_code, StockRSRating.trade_date.desc())
        )
        result = await db.execute(stmt)
        rows = result.all()

    rs_map = {}
    for ts_code, rs_rating in rows:
        if ts_code not in rs_map:
            rs_map[ts_code] = rs_rating
    return rs_map


async def _fetch_news_digests(target_date: date) -> list[dict]:
    """获取当日所有新闻概览（按时段顺序）。"""
    async with async_session() as db:
        stmt = (
            select(NewsDigest)
            .where(NewsDigest.digest_date == target_date)
            .order_by(NewsDigest.period_start.asc())
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    return [
        {
            "period": r.period_label,
            "news_count": r.news_count,
            "content": (r.content or "")[:500],  # 截断节省 tokens
        }
        for r in rows
    ]


async def _fetch_nav(target_date: date) -> dict | None:
    """获取当日或最近的模拟仓净值。"""
    async with async_session() as db:
        stmt = (
            select(SandboxNav)
            .where(SandboxNav.trade_date <= target_date)
            .order_by(SandboxNav.trade_date.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        nav = result.scalar_one_or_none()

    if not nav:
        return None
    return {
        "trade_date": nav.trade_date.isoformat(),
        "nav": float(nav.nav),
        "total_pnl": float(nav.total_pnl),
        "total_market_value": float(nav.total_market_value),
        "cash": float(nav.cash),
    }


# ── Prompt 构建 ──

def _build_briefing_prompt(
    target_date: date,
    vcp_list: list[dict],
    trend_list: list[dict],
    value_list: list[dict],
    quotes: dict[str, dict],
    rs_ratings: dict[str, int],
    digests: list[dict],
    nav: dict | None,
) -> str:
    """拼装发送给 DeepSeek 的 user prompt。"""
    sections = []
    sections.append(f"# 每日数据概要 — {target_date}\n")

    # 1. 新闻概览
    if digests:
        sections.append("## 📰 今日新闻概览")
        for d in digests:
            sections.append(f"### {d['period']}（{d['news_count']}条新闻）")
            sections.append(d["content"])
        sections.append("")

    # 2. VCP 策略白名单
    sections.append(f"## 📊 VCP 策略白名单（{len(vcp_list)} 只）")
    if vcp_list:
        for s in vcp_list:
            code = s["ts_code"]
            q = quotes.get(code, {})
            rs = rs_ratings.get(code, "N/A")
            price = f"{s['price']:.2f}" if s.get("price") else "N/A"
            vcp = f"{s['vcp_score']:.1f}" if s.get("vcp_score") else "N/A"
            ema20 = f"{s['ema20']:.2f}" if s.get("ema20") else "N/A"
            ema50 = f"{s['ema50']:.2f}" if s.get("ema50") else "N/A"
            ema120 = f"{s['ema120']:.2f}" if s.get("ema120") else "N/A"
            pct_raw = q.get("pct_change")
            pct = f"{pct_raw:.2f}" if pct_raw is not None else "N/A"
            line = (
                f"- **{s['name']}** ({code}) | "
                f"价格:{price} | 涨跌:{pct}% | "
                f"VCP得分:{vcp} | RS:{rs} | "
                f"EMA20:{ema20} EMA50:{ema50} EMA120:{ema120} | "
                f"EPS增长:{s.get('eps_growth', 'N/A')}% 营收YoY:{s.get('revenue_yoy', 'N/A')}% | "
                f"行业:{s.get('industry', 'N/A')} | 资金流:{s.get('fund_flow', 'N/A')}"
            )
            if q.get("amount"):
                line += f" | 成交额:{q['amount']/10000:.0f}万"
            if q.get("turnover"):
                line += f" | 换手:{q['turnover']:.1f}%"
            sections.append(line)
    else:
        sections.append("今日无 VCP 策略入选标的。")
    sections.append("")

    # 3. 趋势策略白名单
    sections.append(f"## 📈 趋势策略白名单（{len(trend_list)} 只）")
    if trend_list:
        for s in trend_list:
            code = s["ts_code"]
            q = quotes.get(code, {})
            rs = rs_ratings.get(code, "N/A")
            price = f"{s['price']:.2f}" if s.get("price") else "N/A"
            tscore = f"{s['trend_score']:.1f}" if s.get("trend_score") else "N/A"
            adx = f"{s['adx']:.1f}" if s.get("adx") else "N/A"
            rsi = f"{s['rsi']:.1f}" if s.get("rsi") else "N/A"
            vratio = f"{s['volume_ratio']:.1f}" if s.get("volume_ratio") else "N/A"
            ma20 = f"{s['ma20']:.2f}" if s.get("ma20") else "N/A"
            ma50 = f"{s['ma50']:.2f}" if s.get("ma50") else "N/A"
            pct_raw = q.get("pct_change")
            pct = f"{pct_raw:.2f}" if pct_raw is not None else "N/A"
            line = (
                f"- **{s['name']}** ({code}) | "
                f"价格:{price} | 涨跌:{pct}% | "
                f"趋势得分:{tscore} | RS:{rs} | "
                f"ADX:{adx} RSI:{rsi} 放量倍数:{vratio} | "
                f"MA20:{ma20} MA50:{ma50} | "
                f"行业:{s.get('industry', 'N/A')} | 资金流:{s.get('fund_flow', 'N/A')}"
            )
            if q.get("amount"):
                line += f" | 成交额:{q['amount']/10000:.0f}万"
            if q.get("turnover"):
                line += f" | 换手:{q['turnover']:.1f}%"
            sections.append(line)
    else:
        sections.append("今日无趋势策略入选标的。")
    sections.append("")

    # 4. 价投观察池
    sections.append(f"## 💰 价投观察池（{len(value_list)} 只）")
    if value_list:
        for s in value_list:
            code = s["ts_code"]
            q = quotes.get(code, {})
            rs = rs_ratings.get(code, "N/A")
            pct_raw = q.get("pct_change")
            pct = f"{pct_raw:.2f}" if pct_raw is not None else "N/A"
            reason = s["reason"] or "暂无"
            line = (
                f"- **{s['name']}** ({code}) [{s['status']}] | "
                f"涨跌:{pct}% | RS:{rs} | "
                f"入选理由:{reason}"
            )
            if q.get("close"):
                line += f" | 收盘:{q['close']:.2f}"
            sections.append(line)
    else:
        sections.append("当前无价投观察标的。")
    sections.append("")

    # 5. 模拟仓
    sections.append("## 🏦 模拟仓状态")
    if nav:
        sections.append(
            f"- 净值: {nav['nav']:.4f} | 累计盈亏: {nav['total_pnl']:.2f}% | "
            f"市值: {nav['total_market_value']:.0f}元 | 现金: {nav['cash']:.0f}元 | "
            f"截至: {nav['trade_date']}"
        )
    else:
        sections.append("尚无模拟仓数据。")

    return "\n".join(sections)


# ── DeepSeek 调用 ──

async def _call_deepseek_briefing(user_prompt: str) -> str:
    """调用 DeepSeek API 生成分析报告。"""
    if not settings.DEEPSEEK_API_KEY or settings.DEEPSEEK_API_KEY.startswith("sk-your"):
        logger.warning("DeepSeek API key not configured, returning empty briefing")
        return ""

    payload = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 3000,
    }

    headers = {
        "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    max_retries = max(settings.DEEPSEEK_MAX_RETRIES, 3)

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.post(
                    settings.DEEPSEEK_API_URL, json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                logger.info("Briefing generated: %d chars", len(content))
                return content.strip()
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500] if e.response else "N/A"
                logger.error(
                    "Briefing DeepSeek API HTTP %s (attempt %d/%d): %s | body: %s",
                    e.response.status_code if e.response else "?",
                    attempt, max_retries, repr(e), body,
                )
            except Exception as e:
                logger.error(
                    "Briefing DeepSeek API error (attempt %d/%d): %r",
                    attempt, max_retries, e,
                )

            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(3 * attempt)
            else:
                return ""

    return ""


# ── 存储 ──

async def _save_briefing(
    briefing_date: date,
    content: str,
    meta: dict,
    prompt_tokens_est: int,
    generation_sec: float,
    status: str = "ok",
) -> None:
    """Upsert briefing — 同一天只保留最新版本。"""
    async with async_session() as db:
        stmt = select(DailyBriefing).where(DailyBriefing.briefing_date == briefing_date)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.content = content
            existing.meta = meta
            existing.prompt_tokens_est = prompt_tokens_est
            existing.generation_sec = generation_sec
            existing.status = status
        else:
            briefing = DailyBriefing(
                briefing_date=briefing_date,
                content=content,
                meta=meta,
                prompt_tokens_est=prompt_tokens_est,
                generation_sec=generation_sec,
                status=status,
            )
            db.add(briefing)

        await db.commit()


# ── 主入口 ──

async def generate_briefing(target_date: date | None = None) -> dict:
    """生成每日综合分析报告。

    Args:
        target_date: 目标日期（默认今天）。

    Returns:
        {"status": "ok"/"empty"/"failed", "vcp_count": N, "trend_count": N, ...}
    """
    if target_date is None:
        target_date = datetime.now(_TZ).date()

    logger.info("Generating daily briefing for %s", target_date)
    t0 = time.monotonic()

    # 1. 并行收集所有数据
    import asyncio

    vcp_task = asyncio.create_task(_fetch_vcp_watchlist(target_date))
    trend_task = asyncio.create_task(_fetch_trend_watchlist(target_date))
    value_task = asyncio.create_task(_fetch_value_stocks())
    digest_task = asyncio.create_task(_fetch_news_digests(target_date))
    nav_task = asyncio.create_task(_fetch_nav(target_date))

    vcp_list = await vcp_task
    trend_list = await trend_task
    value_list = await value_task
    digests = await digest_task
    nav = await nav_task

    # 收集所有需要查行情的股票代码
    all_codes = list(set(
        [s["ts_code"] for s in vcp_list]
        + [s["ts_code"] for s in trend_list]
        + [s["ts_code"] for s in value_list]
    ))

    quotes_task = asyncio.create_task(_fetch_stock_quotes(all_codes, target_date))
    rs_task = asyncio.create_task(_fetch_rs_ratings(all_codes, target_date))
    quotes = await quotes_task
    rs_ratings = await rs_task

    vcp_count = len(vcp_list)
    trend_count = len(trend_list)
    value_count = len(value_list)
    digest_count = len(digests)

    logger.info(
        "Briefing data collected: VCP=%d, Trend=%d, Value=%d, Digests=%d, Quotes=%d",
        vcp_count, trend_count, value_count, digest_count, len(quotes),
    )

    # 如果所有策略都没有数据且没有新闻，跳过
    if vcp_count == 0 and trend_count == 0 and value_count == 0 and digest_count == 0:
        logger.info("No data available for briefing on %s, skipping", target_date)
        await _save_briefing(target_date, "今日无可用数据，跳过分析报告生成。", {}, 0, 0, "empty")
        return {"status": "empty", "vcp_count": 0, "trend_count": 0}

    # 2. 构建 prompt
    user_prompt = _build_briefing_prompt(
        target_date, vcp_list, trend_list, value_list,
        quotes, rs_ratings, digests, nav,
    )
    prompt_tokens_est = len(user_prompt) // 2  # 粗略估算（中文约 2 字符/token）

    logger.info(
        "Briefing prompt built: ~%d chars, ~%d tokens est.",
        len(user_prompt), prompt_tokens_est,
    )

    # 3. 调用 DeepSeek
    content = await _call_deepseek_briefing(user_prompt)
    generation_sec = time.monotonic() - t0

    meta = {
        "vcp_count": vcp_count,
        "trend_count": trend_count,
        "value_count": value_count,
        "digest_count": digest_count,
        "quote_count": len(quotes),
    }

    if not content:
        logger.warning("DeepSeek returned empty content for briefing %s", target_date)
        content = "AI 分析报告生成失败，请稍后重试。"
        await _save_briefing(target_date, content, meta, prompt_tokens_est, generation_sec, "failed")
        return {"status": "failed", **meta, "generation_sec": round(generation_sec, 1)}

    # 4. 存入数据库
    await _save_briefing(target_date, content, meta, prompt_tokens_est, generation_sec, "ok")

    logger.info(
        "Briefing saved: %s, %d chars, %.1fs, VCP=%d Trend=%d",
        target_date, len(content), generation_sec, vcp_count, trend_count,
    )
    return {
        "status": "ok",
        "content_length": len(content),
        "generation_sec": round(generation_sec, 1),
        **meta,
    }
