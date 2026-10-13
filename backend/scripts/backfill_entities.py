"""回填历史新闻的 entities / entity_types（世界线 P0 实体层）。

背景：早期 pipeline 未落实体字段，存量新闻的 entities 为 NULL，
导致事件合成阶段 _collect_cluster_entities 读不到实体、entities 表为空。
本脚本用 DeepSeek 对历史新闻重新抽取实体，补齐 news.entities / news.entity_types
两个字段（与增量链路逐位对齐）。

复用 llm_news_filter 的 _ensure_entity_pairs / _normalize_entity_type，
保证回填结果与线上增量抽取的规范化逻辑完全一致。

在容器内运行：python scripts/backfill_entities.py
"""

import asyncio
import json
import logging
import os
import sys

# 将后端根目录加入路径（兼容容器内 /app 与本地 backend/ 两种布局）
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ── 可调参数 ──
BATCH_SIZE = 20          # 日志分批粒度
MIN_SCORE = 6            # 仅回填 ai_score >= 6（5 分新闻在增量链路本就不抽实体）
MAX_CONCURRENCY = 5      # LLM 并发上限
MAX_ITEMS = 5            # 每条新闻最多实体数（与 ENTITY_EXTRACTION_MAX_ITEMS 一致）

SYSTEM_PROMPT = """你是一名金融信息抽取引擎。从给定新闻中抽取3—5个核心实体。

输出严格为 JSON：{"entities":[{"name":"...","type":"..."}]}

规则：
- name 为实体常用名（公司、机构、人物、地点、商品、资产的常用名），须为原文明确出现的具体名词
- type 取值仅限 org（机构/公司）、person（人物）、place（地点）、asset（资产）、commodity（商品）、concept（概念）六者之一，无法判定时填 null
- 禁止泛称（市场、行业、全球、整体）
- 禁止推断或补充原文未出现的实体
- 禁止输出股票代码
- 按与该事件的相关度降序
- 可为空数组
不要输出任何额外文字。"""


def _build_user_prompt(row) -> str:
    parts = [f"标题：{row['title']}"]
    if row.get("ai_summary"):
        parts.append(f"摘要：{row['ai_summary']}")
    if row.get("tags"):
        tags = row["tags"] if isinstance(row["tags"], list) else list(row["tags"])
        parts.append(f"标签：{'、'.join(str(t) for t in tags)}")
    return "\n".join(parts)


async def _extract_entities(client, settings, row):
    """调用 DeepSeek 抽取实体，返回 (names, types)；失败返回 (None, None)。"""
    payload = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(row)},
        ],
        "thinking": {"type": "disabled"},
        "temperature": 0.1,
        "max_tokens": 256,
    }
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        resp = await client.post(
            settings.LLM_API_URL, json=payload, headers=headers, timeout=30.0
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        raw = data.get("entities") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 抽取失败 id=%s: %s", row["id"], e)
        return None, None

    # 复用线上规范化逻辑，保证与增量链路一致
    from app.services.llm_news_filter import _ensure_entity_pairs
    names, types = _ensure_entity_pairs(raw, max_items=MAX_ITEMS)
    return names, types


async def backfill() -> None:
    from app.database import async_session
    from app.config import settings
    import httpx

    if not settings.LLM_API_KEY:
        logger.error("LLM_API_KEY 未配置，无法回填")
        return

    # 1) 取出待回填行
    async with async_session() as session:
        result = await session.execute(text("""
            SELECT id, title, ai_summary, tags
            FROM news
            WHERE (entities IS NULL OR array_length(entities, 1) IS NULL)
              AND ai_score >= :min_score
              AND title IS NOT NULL
            ORDER BY created_at DESC
        """), {"min_score": MIN_SCORE})
        rows = [dict(r._mapping) for r in result.fetchall()]

    logger.info("待回填新闻数：%d（ai_score>=%d）", len(rows), MIN_SCORE)
    if not rows:
        logger.info("无需回填，结束。")
        return

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    updated = 0
    failed = 0
    empty = 0

    async def _worker(row):
        nonlocal updated, failed, empty
        async with sem:
            async with httpx.AsyncClient() as client:
                names, types = await _extract_entities(client, settings, row)
        if names is None:
            failed += 1
            return
        if not names:
            empty += 1
        async with async_session() as s:
            await s.execute(
                text("""
                    UPDATE news
                    SET entities = :names, entity_types = :types
                    WHERE id = :id
                """),
                {"names": names, "types": types, "id": str(row["id"])},
            )
            await s.commit()
        updated += 1
        if updated % BATCH_SIZE == 0:
            logger.info("进度：已更新 %d / %d", updated, len(rows))

    await asyncio.gather(*[_worker(r) for r in rows])

    logger.info(
        "回填完成：成功 %d，LLM 失败 %d，无实体 %d，总计 %d",
        updated, failed, empty, len(rows),
    )


if __name__ == "__main__":
    asyncio.run(backfill())
