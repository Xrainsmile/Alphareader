"""News Digest Service — 收集时段新闻并调用 DeepSeek 生成摘要。

定时任务调用此服务，在指定时间段内：
  1. 从 news 表查询该时段发布的新闻（按 ai_score 倒序取 top N）
  2. 拼接标题+摘要，发送给 DeepSeek API 生成 Markdown 总结
  3. 写入 news_digests 表（upsert：重复时段覆盖）

节省 tokens 策略：
  - 只传标题+ai_summary（不传 content 全文）
  - System Prompt 极简（~150 tokens）
  - 限制 max_tokens=1500
  - temperature=0.3
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

import httpx
import pytz
from sqlalchemy import select, and_

from app.config import settings
from app.database import async_session
from app.models.news import News
from app.models.news_digest import NewsDigest

logger = logging.getLogger("alphareader.digest")

# 时区
_TZ = pytz.timezone(settings.TIMEZONE)

# DeepSeek 新闻总结的 System Prompt（精简版，节省 tokens）
DIGEST_SYSTEM_PROMPT = (
    "你是金融和科技咨询编辑。将输入的新闻列表总结为一份简洁的中文市场简报（Markdown）。\n"
    "要求：按重要性分类组织（如"宏观政策"、"公司动态"、"科技前沿"等），每条1-2句话概括要点，标注来源。\n"
    "如果某个分类没有相关新闻则跳过。总字数控制在500字以内。"
)

# 时段配置：label → (start_hour, start_minute, end_hour, end_minute)
PERIOD_CONFIG = {
    "morning": (0, 0, 8, 30),    # 00:00 ~ 08:30
    "midday":  (8, 30, 12, 0),   # 08:30 ~ 12:00
    "evening": (12, 0, 18, 0),   # 12:00 ~ 18:00
    "night":   (18, 0, 23, 59),  # 18:00 ~ 24:00 (用 23:59:59 表示当天结束)
}

# 时段中文标签（前端展示用）
PERIOD_LABELS = {
    "morning": "早间概览",
    "midday":  "午间概览",
    "evening": "傍晚概览",
    "night":   "夜间概览",
}

# 时段图标
PERIOD_ICONS = {
    "morning": "🌅",
    "midday":  "☀️",
    "evening": "🌇",
    "night":   "🌙",
}


def _get_period_range(period_label: str, target_date: date) -> tuple[datetime, datetime]:
    """根据 period_label 和日期，返回 (start_dt, end_dt) 时区感知时间。"""
    sh, sm, eh, em = PERIOD_CONFIG[period_label]

    start_dt = _TZ.localize(datetime.combine(target_date, time(sh, sm, 0)))

    if eh == 23 and em == 59:
        # night 时段结束于次日 00:00
        end_dt = _TZ.localize(datetime.combine(target_date + timedelta(days=1), time(0, 0, 0)))
    else:
        end_dt = _TZ.localize(datetime.combine(target_date, time(eh, em, 0)))

    return start_dt, end_dt


async def _fetch_period_news(
    period_start: datetime,
    period_end: datetime,
    max_items: int = 50,
) -> list[dict]:
    """从 news 表查询指定时间段内的新闻，返回精简字段列表。

    按 ai_score 倒序排列，最多取 max_items 条。
    只取需要的字段：title, ai_summary, source。
    """
    async with async_session() as db:
        stmt = (
            select(News.title, News.ai_summary, News.source)
            .where(
                and_(
                    News.published_at >= period_start,
                    News.published_at < period_end,
                    News.ai_score >= settings.DEEPSEEK_SCORE_THRESHOLD,
                )
            )
            .order_by(News.ai_score.desc(), News.published_at.desc())
            .limit(max_items)
        )
        result = await db.execute(stmt)
        rows = result.all()

    return [
        {
            "title": row.title,
            "summary": row.ai_summary or "",
            "source": row.source,
        }
        for row in rows
    ]


def _build_digest_prompt(news_list: list[dict], period_label: str, target_date: date) -> str:
    """构建发送给 DeepSeek 的 user prompt。

    格式：
      以下是 2026-03-20 00:00~08:30 共 15 条新闻：
      1. [财联社] 标题：xxx | 摘要：xxx
    """
    sh, sm, eh, em = PERIOD_CONFIG[period_label]

    # night 时段特殊处理显示
    end_display = "24:00" if period_label == "night" else f"{eh:02d}:{em:02d}"
    header = f"以下是 {target_date} {sh:02d}:{sm:02d}~{end_display} 共 {len(news_list)} 条新闻：\n"

    lines = []
    for i, item in enumerate(news_list, 1):
        summary_text = item["summary"][:100] if item["summary"] else "无摘要"
        lines.append(f"{i}. [{item['source']}] 标题：{item['title']} | 摘要：{summary_text}")

    return header + "\n".join(lines)


async def _call_deepseek_digest(user_prompt: str) -> str:
    """调用 DeepSeek API 生成新闻总结，返回 Markdown 文本。"""
    if not settings.DEEPSEEK_API_KEY or settings.DEEPSEEK_API_KEY.startswith("sk-your"):
        logger.warning("DeepSeek API key not configured, returning empty digest")
        return ""

    payload = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 1500,
    }

    headers = {
        "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        for attempt in range(1, settings.DEEPSEEK_MAX_RETRIES + 1):
            try:
                resp = await client.post(
                    settings.DEEPSEEK_API_URL, json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                logger.info("Digest generated: %d chars", len(content))
                return content.strip()
            except Exception as e:
                logger.error(
                    "Digest DeepSeek API error (attempt %d/%d): %s",
                    attempt, settings.DEEPSEEK_MAX_RETRIES, e,
                )
                if attempt < settings.DEEPSEEK_MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(3 * attempt)
                    continue
                return ""

    return ""


async def generate_digest(period_label: str, target_date: date | None = None) -> dict:
    """生成指定时段的新闻概览摘要。

    Args:
        period_label: "morning" / "midday" / "evening" / "night"
        target_date: 目标日期（默认今天）。night 时段在次日 00:00 触发时，
                     传入前一天日期。

    Returns:
        {"status": "ok"/"skip"/"error", "news_count": N, ...}
    """
    if target_date is None:
        now = datetime.now(_TZ)
        # night 时段在次日 00:00 触发，所以 target_date 是昨天
        if period_label == "night" and now.hour < 1:
            target_date = (now - timedelta(days=1)).date()
        else:
            target_date = now.date()

    if period_label not in PERIOD_CONFIG:
        raise ValueError(f"Invalid period_label: {period_label}")

    period_start, period_end = _get_period_range(period_label, target_date)
    logger.info(
        "Generating digest: %s %s (%s ~ %s)",
        target_date, period_label, period_start, period_end,
    )

    # 1. 查询时段新闻
    news_list = await _fetch_period_news(period_start, period_end)
    news_count = len(news_list)

    if news_count == 0:
        logger.info("No news found for %s %s, skipping digest", target_date, period_label)
        # 仍然写入一条记录（标记无新闻），避免重复触发
        await _save_digest(target_date, period_label, period_start, period_end, 0, "该时段暂无重要新闻。")
        return {"status": "skip", "news_count": 0}

    # 2. 构建 prompt 并调用 DeepSeek
    user_prompt = _build_digest_prompt(news_list, period_label, target_date)
    logger.info("Digest prompt: %d news, ~%d chars", news_count, len(user_prompt))

    content = await _call_deepseek_digest(user_prompt)

    if not content:
        logger.warning("DeepSeek returned empty content for %s %s", target_date, period_label)
        content = "AI 摘要生成失败，请稍后重试。"

    # 3. 存入数据库（upsert）
    await _save_digest(target_date, period_label, period_start, period_end, news_count, content)

    logger.info(
        "Digest saved: %s %s, %d news, %d chars",
        target_date, period_label, news_count, len(content),
    )
    return {"status": "ok", "news_count": news_count, "content_length": len(content)}


async def _save_digest(
    digest_date: date,
    period_label: str,
    period_start: datetime,
    period_end: datetime,
    news_count: int,
    content: str,
) -> None:
    """Upsert digest record — 同一天同一时段只保留最新版本。"""
    async with async_session() as db:
        stmt = select(NewsDigest).where(
            and_(
                NewsDigest.digest_date == digest_date,
                NewsDigest.period_label == period_label,
            )
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.period_start = period_start
            existing.period_end = period_end
            existing.news_count = news_count
            existing.content = content
        else:
            digest = NewsDigest(
                digest_date=digest_date,
                period_label=period_label,
                period_start=period_start,
                period_end=period_end,
                news_count=news_count,
                content=content,
            )
            db.add(digest)

        await db.commit()
