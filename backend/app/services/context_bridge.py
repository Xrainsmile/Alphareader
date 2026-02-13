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

TOP_N = 66

# Fixed timezone for China (UTC+8), used for date boundary calculations.
# This avoids importing pytz/zoneinfo just for a fixed offset.
_CN_TZ = timezone(timedelta(hours=8))

META_PROMPT_TEMPLATE = """# Role
你是一位拥有 20 年经验、擅长"基本面+趋势分析"的对冲基金首席策略师。你具备极强的信息穿透力，能从碎片化的新闻中识别出影响市场估值和流动性的核心逻辑，并识别出隐藏在利好背后的潜在风险。

# Context
以下是 {date_str}「{sector}」板块高价值情报列表。这些数据已经过初步筛选，包含【标签】和【AI评分】。

{news_block}

# Investment Logic Framework
在分析时，请遵循以下分析框架：
1. 互联性分析：识别不同新闻之间是否存在因果、协同或对冲关系。
2. 预期差分析：判断该信息是已被市场充分定价，还是存在超预期空间。
3. 风险收益比：每一个机会点必须伴随对应的反面逻辑。

# Task
请基于上述情报生成一份深度分析报告（每日都会输出的报告），要求逻辑严密，专业性极强，可读性也很高，减少 AI 语气和措辞。

## 1. 市场图谱与情绪博弈
- **核心逻辑聚类**：用一句话概括今日市场的驱动力（如：流动性推动、避险情绪升温、政策转向等）。
- **情绪定性**：在 [极度悲观/悲观/中性/乐观/极度乐观] 中选一，并给出你的"盘感"理由。

## 2. 核心投资信号挖掘 (High-Conviction Signals)
请选出 2-3 个最有价值的信号，按以下格式输出：
- **【信号名称】**：(例如：半导体国产替代加速)
- **关联证据**：极简概括关联的新闻
- **影响深度**：分析该信号对相关板块是"短期刺激"还是"中长期逻辑改变"。
- **博弈核心**：当前市场在该信号上的分歧点在哪里？

## 3. 风险雷达 (Blind Spots)
- **显性风险**：情报中直接提到的负面因素。
- **隐性风险**：如果上述利好逻辑证伪，最坏的情况是什么？
- **合规/监管预警**：是否存在政策或外部环境（如反洗钱、制裁、监管趋严）的潜在冲击。

## 4. 短线情绪展望与行动建议
- **下周展望**：预测情绪的演变路径（是冲高回落还是底部震荡）。
- **观察哨位**：下周需要重点关注哪一个核心指标或事件来验证你的判断。

# Constraint
- 禁止模棱两可，必须给出明确的立场。
- 优先分析 AI 评分 > 8 的新闻。
- 输出格式：请使用清晰的 Markdown 标题和列表。"""


def _format_news_block(news_list: list[News]) -> str:
    """Format scored news into numbered Markdown block."""
    lines: list[str] = []
    for i, n in enumerate(news_list, 1):
        source_tag = f"(来源: {n.source})"
        score_tag = f"[评分: {n.ai_score}/10]"
        summary = n.ai_summary or n.title
        tags_str = " | ".join(n.tags) if n.tags else ""
        tag_display = f" 【{tags_str}】" if tags_str else ""

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
