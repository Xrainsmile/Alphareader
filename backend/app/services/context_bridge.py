"""Module C: Gemini Context Bridge — generate structured prompt context.

Endpoint: GET /api/v1/generate_prompt?sector=新能源&date=today
Logic:
  1. Query today's Top-N news for a given sector (by ai_score DESC).
  2. Format as structured Markdown prompt.
  3. Prepend a Meta-Prompt that guides Gemini's reasoning.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone, timedelta

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.news import News

logger = logging.getLogger("alphareader.bridge")

TOP_N = 10

# Fixed timezone for China (UTC+8), used for date boundary calculations.
# This avoids importing pytz/zoneinfo just for a fixed offset.
_CN_TZ = timezone(timedelta(hours=8))

META_PROMPT_TEMPLATE = """# Role: 资深金融分析助手
# Context: 以下是{date_str}「{sector}」板块经 AI 筛选的高价值新闻（按重要性排序）：

{news_block}

# Task:
请基于上述信息完成以下分析：
1. 总结该板块今日的核心主题和市场情绪（乐观/中性/悲观）。
2. 识别出最值得关注的 2-3 个投资信号，并说明理由。
3. 列出 3 个潜在风险点。
4. 给出下周该板块的短线情绪展望。

请用结构化的 Markdown 格式回答。"""


def _format_news_block(news_list: list[News]) -> str:
    """Format scored news into numbered Markdown block."""
    lines: list[str] = []
    for i, n in enumerate(news_list, 1):
        source_tag = f"(来源: {n.source})"
        score_tag = f"[评分: {n.ai_score}/10]"
        summary = n.ai_summary or n.title
        tags_str = ", ".join(n.tags) if n.tags else ""
        tag_display = f" #{tags_str}" if tags_str else ""

        lines.append(f"{i}. **{n.title}** {score_tag} {source_tag}{tag_display}")
        if n.ai_summary and n.ai_summary != n.title:
            lines.append(f"   > {n.ai_summary}")
        lines.append("")

    return "\n".join(lines)


async def generate_prompt_context(
    session: AsyncSession,
    sector: str | None = None,
    target_date: date | None = None,
    top_n: int = TOP_N,
) -> dict:
    """Generate Gemini-ready prompt context.

    Returns:
        dict with keys: prompt, news_count, sector, date
    """
    if target_date is None:
        target_date = datetime.now(_CN_TZ).date()

    # Build query: today's news, optionally filtered by sector tag
    # Use China timezone (UTC+8) for day boundaries to match user expectations
    day_start = datetime.combine(target_date, time.min).replace(tzinfo=_CN_TZ)
    day_end = datetime.combine(target_date, time.max).replace(tzinfo=_CN_TZ)

    conditions = [
        News.created_at >= day_start,
        News.created_at <= day_end,
        News.ai_score >= 6,
    ]

    if sector:
        # Filter by tag array contains sector
        conditions.append(News.tags.any(sector))

    stmt = (
        select(News)
        .where(and_(*conditions))
        .order_by(desc(News.ai_score), desc(News.published_at))
        .limit(top_n)
    )

    result = await session.execute(stmt)
    news_list = list(result.scalars().all())

    if not news_list:
        return {
            "prompt": f"今日「{sector or '全市场'}」暂无高价值新闻。",
            "news_count": 0,
            "sector": sector or "全市场",
            "date": target_date.isoformat(),
        }

    sector_display = sector or "全市场"
    date_str = target_date.strftime("%Y年%m月%d日")
    news_block = _format_news_block(news_list)

    prompt = META_PROMPT_TEMPLATE.format(
        date_str=date_str,
        sector=sector_display,
        news_block=news_block,
    )

    return {
        "prompt": prompt,
        "news_count": len(news_list),
        "sector": sector_display,
        "date": target_date.isoformat(),
    }
