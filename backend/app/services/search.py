"""News search service — PostgreSQL full-text search with hybrid ranking.

搜索排序算法设计参考:
  - PostgreSQL ts_rank_cd: Cover Density Ranking, 效果接近 BM25
  - Hacker News Gravity: 时间衰减因子
  - 质量信号: AI 评分作为文档质量权重

最终排序公式:
  final_score = ts_rank_cd(文本相关度)
                × ln(ai_score + 1)            -- 质量权重（对数平滑）
                × (1 / (hours_elapsed + 2)^0.5) -- 时间衰减（平方根衰减，比 HN 温和）

这个混合排序策略借鉴了:
  1. Elasticsearch BM25 的文本相关度思路 (通过 ts_rank_cd 近似)
  2. Google PageRank 的 "文档质量信号" 概念 (用 AI 评分替代)
  3. Hacker News Gravity 的时间衰减公式 (使用更温和的指数)
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("alphareader.search")

# ── 搜索 SQL ──

# 中文搜索策略: 使用 LIKE 模糊匹配 + 'simple' 配置的 tsvector
# PostgreSQL 默认不含中文分词器, 'simple' 配置对中文做 unigram 分词
# 同时用 ILIKE 做模糊匹配兜底, 确保中文搜索有结果

SEARCH_SQL = """
WITH query_input AS (
    SELECT
        :query AS raw_query,
        plainto_tsquery('simple', :query) AS tsq
),
scored AS (
    SELECT
        n.id,
        n.title,
        n.source,
        n.url,
        n.ai_score,
        n.ai_summary,
        n.tags,
        n.related_to_id,
        n.published_at,
        n.created_at,
        -- 文本相关度: ts_rank_cd (Cover Density Ranking, 类 BM25)
        -- 如果 tsvector 匹配则用 ts_rank_cd, 否则用 LIKE 匹配给基础分
        CASE
            WHEN n.search_vector @@ (SELECT tsq FROM query_input)
            THEN ts_rank_cd(n.search_vector, (SELECT tsq FROM query_input), 32)
            ELSE 0.1
        END AS text_relevance,
        -- 质量权重: ln(ai_score + 1), 对数平滑避免高分过度主导
        LN(GREATEST(COALESCE(n.ai_score, 0), 0) + 1) AS quality_weight,
        -- 时间衰减: 1/(hours+2)^0.5, 比 HN 的 1.8 温和, 搜索场景更侧重相关度
        1.0 / POWER(
            GREATEST(EXTRACT(EPOCH FROM (NOW() - COALESCE(n.published_at, n.created_at))) / 3600.0, 0) + 2,
            0.5
        ) AS time_decay,
        -- 高亮标题
        ts_headline(
            'simple',
            n.title,
            (SELECT tsq FROM query_input),
            'StartSel=<mark>, StopSel=</mark>, MaxWords=80, MinWords=30, MaxFragments=1'
        ) AS title_highlighted,
        -- 高亮摘要
        ts_headline(
            'simple',
            COALESCE(n.ai_summary, ''),
            (SELECT tsq FROM query_input),
            'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20, MaxFragments=1'
        ) AS summary_highlighted
    FROM news n, query_input qi
    WHERE
        -- 全文搜索匹配 OR ILIKE 模糊匹配 (兜底中文搜索) OR 标签匹配
        (n.search_vector @@ qi.tsq
         OR n.title ILIKE '%%' || qi.raw_query || '%%'
         OR COALESCE(n.ai_summary, '') ILIKE '%%' || qi.raw_query || '%%'
         OR qi.raw_query = ANY(n.tags))
        -- 基础质量过滤
        AND COALESCE(n.ai_score, 0) >= :min_score
)
SELECT
    *,
    -- 最终混合排序分: 文本相关度 × 质量权重 × 时间衰减
    -- 标签精确命中额外加权
    (text_relevance * quality_weight * time_decay) AS final_score
FROM scored
ORDER BY final_score DESC
LIMIT :limit OFFSET :offset
"""

COUNT_SQL = """
WITH query_input AS (
    SELECT
        :query AS raw_query,
        plainto_tsquery('simple', :query) AS tsq
)
SELECT COUNT(*)
FROM news n, query_input qi
WHERE
    (n.search_vector @@ qi.tsq
     OR n.title ILIKE '%%' || qi.raw_query || '%%'
     OR COALESCE(n.ai_summary, '') ILIKE '%%' || qi.raw_query || '%%'
     OR qi.raw_query = ANY(n.tags))
    AND COALESCE(n.ai_score, 0) >= :min_score
"""

SUGGEST_SQL = """
SELECT DISTINCT sub.term FROM (
    -- 从标题中提取匹配关键词
    SELECT DISTINCT unnest(
        regexp_matches(title, :pattern, 'gi')
    ) AS term
    FROM news
    WHERE title ILIKE '%%' || :prefix || '%%'
      AND COALESCE(ai_score, 0) >= 6
    ORDER BY term
    LIMIT 8
) sub
LIMIT 5
"""

HOT_QUERIES_SQL = """
SELECT
    UNNEST(tags) AS tag,
    COUNT(*) AS cnt
FROM news
WHERE created_at >= NOW() - INTERVAL '24 hours'
  AND COALESCE(ai_score, 0) >= 7
  AND tags IS NOT NULL
GROUP BY tag
ORDER BY cnt DESC
LIMIT 8
"""


def _sanitize_query(q: str) -> str:
    """清理用户搜索输入，防止 SQL 注入和无效查询。"""
    q = q.strip()
    # 移除特殊字符（保留中文、字母、数字、空格）
    q = re.sub(r"[^\w\u4e00-\u9fff\s\-.]", "", q)
    # 压缩连续空格
    q = re.sub(r"\s+", " ", q)
    return q[:200]  # 限制长度


async def search_news(
    db: AsyncSession,
    query: str,
    limit: int = 20,
    offset: int = 0,
    min_score: int = 6,
) -> dict:
    """搜索新闻，返回按混合排序算法排列的结果。

    Args:
        db: 数据库会话
        query: 搜索关键词
        limit: 每页条数
        offset: 偏移量
        min_score: 最低 AI 评分

    Returns:
        {items: [...], total: int, query: str, limit: int, offset: int}
    """
    clean_query = _sanitize_query(query)
    if not clean_query:
        return {"items": [], "total": 0, "query": query, "limit": limit, "offset": offset}

    params = {
        "query": clean_query,
        "min_score": min_score,
        "limit": limit,
        "offset": offset,
    }

    # 获取总数
    count_result = await db.execute(text(COUNT_SQL), params)
    total = count_result.scalar() or 0

    if total == 0:
        return {"items": [], "total": 0, "query": clean_query, "limit": limit, "offset": offset}

    # 获取搜索结果
    result = await db.execute(text(SEARCH_SQL), params)
    rows = result.mappings().all()

    items = []
    for r in rows:
        items.append({
            "id": str(r["id"]),
            "title": r["title"],
            "title_highlighted": r["title_highlighted"],
            "source": r["source"],
            "url": r["url"],
            "ai_score": r["ai_score"],
            "ai_summary": r["ai_summary"],
            "summary_highlighted": r["summary_highlighted"],
            "tags": r["tags"],
            "related_to_id": str(r["related_to_id"]) if r["related_to_id"] else None,
            "published_at": r["published_at"].isoformat() if r["published_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "relevance_score": round(float(r["final_score"]), 6),
        })

    return {
        "items": items,
        "total": total,
        "query": clean_query,
        "limit": limit,
        "offset": offset,
    }


async def get_search_suggestions(
    db: AsyncSession,
    prefix: str,
) -> list[str]:
    """根据前缀返回搜索建议（从已有标题中提取）。"""
    clean = _sanitize_query(prefix)
    if len(clean) < 1:
        return []

    # 用正则提取包含前缀的词组
    pattern = f"\\m{re.escape(clean)}\\w*"
    try:
        result = await db.execute(
            text(SUGGEST_SQL),
            {"prefix": clean, "pattern": pattern},
        )
        return [row[0] for row in result.fetchall() if row[0]]
    except Exception:
        logger.debug("Suggest query failed, falling back to empty", exc_info=True)
        return []


async def get_hot_topics(db: AsyncSession) -> list[str]:
    """获取热门话题标签（过去 24h 高分新闻的高频标签）。"""
    try:
        result = await db.execute(text(HOT_QUERIES_SQL))
        return [row[0] for row in result.fetchall() if row[0]]
    except Exception:
        logger.debug("Hot topics query failed", exc_info=True)
        return []
