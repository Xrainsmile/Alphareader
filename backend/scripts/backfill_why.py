"""回填历史新闻的 why_it_matters（推荐理由）。

背景：早期版本的 pipeline 没有把评分 reason 落库，因此存量新闻的
why_it_matters 列为 NULL。本脚本用 SiliconFlow 对高价值历史新闻重新生成
一句话"推荐理由"，补齐该字段（新新闻在跑批时会自动生成，无需回填）。

仅处理 why_it_matters IS NULL 且 ai_score >= MIN_SCORE 的行，分批并发调用，
控制 API 成本。在容器内运行：python scripts/backfill_why.py
"""

import asyncio
import json
import logging
import os
import sys

# 将后端根目录加入 import 路径（兼容容器内 /app 与本地 backend/ 两种布局）
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ── 可调参数 ──
BATCH_SIZE = 20          # 每批并发条数
MIN_SCORE = 6            # 仅回填高价值新闻，控制成本
WINDOW_DAYS = 30         # 仅回填最近 N 天，更早的新闻意义有限
MAX_CONCURRENCY = 5      # LLM 并发上限

SYSTEM_PROMPT = """你是一位资深金融编辑。请基于给定新闻，用一句话（不超过40字）告诉投资者"为什么值得关注这条新闻"，要结合催化类型与预期差，语气专业克制。只输出 JSON：{"why_it_matters": "..."}，不要任何额外文字。"""


def _build_user_prompt(row) -> str:
    parts = [f"标题：{row['title']}"]
    if row["ai_summary"]:
        parts.append(f"摘要：{row['ai_summary']}")
    if row["tags"]:
        tags = row["tags"] if isinstance(row["tags"], list) else list(row["tags"])
        parts.append(f"标签：{'、'.join(tags)}")
    if row["catalyst_type"]:
        parts.append(f"催化类型：{row['catalyst_type']}")
    if row["sentiment_score"] is not None:
        parts.append(f"情绪分：{row['sentiment_score']}")
    if row["surprise_factor"] is not None:
        parts.append(f"预期差：{row['surprise_factor']}")
    return "\n".join(parts)


async def _generate_why(client, settings, row) -> str | None:
    """调用 SiliconFlow 生成单条 why_it_matters，失败返回 None。"""
    payload = {
        "model": settings.SILICONFLOW_LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(row)},
        ],
        "temperature": 0.2,
        "max_tokens": 128,
        "enable_thinking": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        resp = await client.post(settings.SILICONFLOW_API_URL, json=payload, headers=headers, timeout=30.0)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        return str(data.get("why_it_matters", "")).strip()[:256] or None
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 生成失败 id=%s: %s", row["id"], e)
        return None


async def backfill() -> None:
    from app.database import async_session
    from app.config import settings
    import httpx

    if not settings.SILICONFLOW_API_KEY:
        logger.error("SILICONFLOW_API_KEY 未配置，无法回填")
        return

    # 1) 取出待回填行
    async with async_session() as session:
        # 注意：asyncpg 对 `:window || ' days'` 这种字符串拼接要求参数是 str，
        # 直接传 int 会 DataError。改用 make_interval(days := :window) 更稳。
        result = await session.execute(text("""
            SELECT id, title, ai_summary, tags, catalyst_type,
                   sentiment_score, surprise_factor
            FROM news
            WHERE why_it_matters IS NULL
              AND ai_score >= :min_score
              AND created_at > NOW() - make_interval(days => :window)
            ORDER BY created_at DESC
        """), {"min_score": MIN_SCORE, "window": WINDOW_DAYS})
        rows = [dict(r._mapping) for r in result.fetchall()]

    logger.info("待回填新闻数：%d（ai_score>=%d，最近%d天）", len(rows), MIN_SCORE, WINDOW_DAYS)
    if not rows:
        logger.info("无需回填，结束。")
        return

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    updated = 0
    failed = 0

    async def _worker(row):
        nonlocal updated, failed
        async with sem:
            async with httpx.AsyncClient() as client:
                why = await _generate_why(client, settings, row)
            if not why:
                failed += 1
                return
            async with async_session() as s:
                await s.execute(
                    text("UPDATE news SET why_it_matters = :v WHERE id = :id"),
                    {"v": why, "id": str(row["id"])},
                )
                await s.commit()
            updated += 1
            if updated % 25 == 0:
                logger.info("进度：已更新 %d / %d", updated, len(rows))

    await asyncio.gather(*[_worker(r) for r in rows])
    logger.info("回填完成：成功 %d，失败 %d，总计 %d", updated, failed, len(rows))


if __name__ == "__main__":
    asyncio.run(backfill())
