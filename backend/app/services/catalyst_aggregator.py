"""催化剂标的聚合服务 — 每日新闻催化剂 × 技术面交叉验证。

流程：
  1. 收集当日 ai_score >= 7 的高分新闻
  2. 提取新闻中的 A 股标的（从 tags / sentiment_entity 中解析公司名）
  3. 调用 LLM 将公司名批量映射为 A 股 ts_code（如"宁德时代" → "300750.SZ"）
  4. 按 ts_code 聚合催化剂信息（出现次数、最高分、催化剂类型等）
  5. 与当日 VCP / 趋势白名单 + RS Rating 交叉验证
  6. 计算催化剂热度评分并分类（双确认 / 强RS / 仅催化剂）
  7. 写入 news_catalyst_stocks 表

定时触发：工作日 08:45 和 15:50（在 Briefing 之前跑完）。
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytz
from sqlalchemy import select, and_, delete

from app.config import settings
from app.database import async_session
from app.models.catalyst import NewsCatalystStock
from app.models.news import News
from app.models.screener import WatchlistDaily, TrendWatchlistDaily
from app.models.stock import StockRSRating

logger = logging.getLogger("alphareader.catalyst")

_TZ = pytz.timezone(settings.TIMEZONE)

# A 股代码正则：6 位数字 + .SZ/.SH
_TS_CODE_PATTERN = re.compile(r"\b(\d{6})\.(SZ|SH|BJ)\b", re.IGNORECASE)
# 6 位纯数字代码
_PURE_CODE_PATTERN = re.compile(r"\b(\d{6})\b")


# ═══════════════════════════════════════════════════════════
#  LLM Prompt — 公司名 → A 股代码批量映射
# ═══════════════════════════════════════════════════════════

TICKER_MAPPING_PROMPT = """\
你是 A 股市场专家。请将以下公司名/实体名映射到对应的 A 股代码。

## 规则
1. 只映射 A 股上市公司（上交所 .SH、深交所 .SZ、北交所 .BJ）
2. 非上市公司、港股、美股、行业名、宏观概念 → 输出 null
3. 如果一个名称可能对应多家上市公司，选择市值最大/最知名的那家
4. 使用标准 ts_code 格式，如 "300750.SZ"、"600519.SH"

## 输出格式（严格 JSON，不要附加任何文字）
```json
{
  "公司名1": "300750.SZ",
  "公司名2": "600519.SH",
  "非上市实体": null
}
```

## 待映射的公司名列表
"""


async def _map_entities_to_tickers(entities: list[str]) -> dict[str, str | None]:
    """调用 LLM 将公司名/实体名批量映射为 A 股 ts_code。

    使用 SiliconFlow 免费模型（Qwen3-8B），成本极低。
    """
    if not entities:
        return {}

    # 去重
    unique_entities = list(set(entities))

    # 如果数量过大，分批处理（每批最多 50 个）
    all_results: dict[str, str | None] = {}
    batch_size = 50

    for i in range(0, len(unique_entities), batch_size):
        batch = unique_entities[i:i + batch_size]
        result = await _call_ticker_mapping_llm(batch)
        all_results.update(result)

    return all_results


async def _call_ticker_mapping_llm(entities: list[str]) -> dict[str, str | None]:
    """单次 LLM 调用，映射一批公司名。"""
    if not settings.SILICONFLOW_API_KEY:
        logger.warning("SiliconFlow API key not configured, skipping ticker mapping")
        return {}

    entity_list = "\n".join(f"- {e}" for e in entities)
    user_prompt = TICKER_MAPPING_PROMPT + entity_list

    payload = {
        "model": settings.SILICONFLOW_LLM_MODEL,
        "messages": [
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }

    headers = {
        "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0)) as client:
                resp = await client.post(
                    settings.SILICONFLOW_API_URL,
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            raw = data["choices"][0]["message"]["content"].strip()

            # 提取 JSON
            # LLM 可能会在 JSON 前后输出 <think>...</think> 标签或 markdown
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if not json_match:
                logger.warning("No JSON in ticker mapping response (attempt %d): %s", attempt, raw[:200])
                continue

            result = _json.loads(json_match.group())

            # 验证格式
            clean: dict[str, str | None] = {}
            for entity, code in result.items():
                if code is None:
                    clean[entity] = None
                elif isinstance(code, str) and _TS_CODE_PATTERN.match(code):
                    clean[entity] = code.upper()
                elif isinstance(code, str) and _PURE_CODE_PATTERN.match(code):
                    # 补全后缀
                    digits = code[:6]
                    suffix = "SH" if digits.startswith("6") else "SZ"
                    clean[entity] = f"{digits}.{suffix}"
                else:
                    clean[entity] = None

            logger.info(
                "Ticker mapping: %d entities → %d mapped",
                len(entities),
                sum(1 for v in clean.values() if v is not None),
            )
            return clean

        except httpx.HTTPStatusError as e:
            logger.error("Ticker mapping HTTP %s (attempt %d): %s",
                         e.response.status_code, attempt, e.response.text[:300])
        except _json.JSONDecodeError as e:
            logger.error("Ticker mapping JSON error (attempt %d): %s", attempt, e)
        except Exception as e:
            logger.error("Ticker mapping error (attempt %d): %r", attempt, e)

        if attempt < 3:
            await asyncio.sleep(2 * attempt)

    return {}


# ═══════════════════════════════════════════════════════════
#  数据收集
# ═══════════════════════════════════════════════════════════

async def _fetch_high_score_news(target_date: date, min_score: int = 7) -> list[dict]:
    """获取当日高评分新闻（ai_score >= 7）。"""
    async with async_session() as db:
        day_start = datetime.combine(target_date, datetime.min.time()).replace(
            tzinfo=pytz.UTC
        )
        day_end = day_start + timedelta(days=1)

        stmt = (
            select(News)
            .where(
                and_(
                    News.created_at >= day_start,
                    News.created_at < day_end,
                    News.ai_score >= min_score,
                )
            )
            .order_by(News.ai_score.desc())
            .limit(100)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    return [
        {
            "title": r.title,
            "ai_score": r.ai_score,
            "tags": r.tags or [],
            "sentiment_entity": r.sentiment_entity or "",
            "catalyst_type": r.catalyst_type or "",
            "sentiment_score": r.sentiment_score,
            "ai_summary": r.ai_summary or "",
        }
        for r in rows
    ]


async def _fetch_vcp_map(target_date: date) -> dict[str, dict]:
    """获取当日 VCP 白名单（ts_code → 详情 dict）。"""
    async with async_session() as db:
        stmt = select(WatchlistDaily).where(WatchlistDaily.run_date == target_date)
        result = await db.execute(stmt)
        rows = result.scalars().all()

    return {
        r.ts_code: {
            "name": r.name,
            "vcp_score": r.vcp_score,
            "industry": r.industry,
        }
        for r in rows
    }


async def _fetch_trend_map(target_date: date) -> dict[str, dict]:
    """获取当日趋势白名单（ts_code → 详情 dict）。"""
    async with async_session() as db:
        stmt = select(TrendWatchlistDaily).where(TrendWatchlistDaily.run_date == target_date)
        result = await db.execute(stmt)
        rows = result.scalars().all()

    return {
        r.ts_code: {
            "name": r.name,
            "trend_score": r.trend_score,
            "industry": r.industry,
        }
        for r in rows
    }


async def _fetch_rs_map(target_date: date) -> dict[str, int]:
    """获取最新 RS Rating（ts_code → rs_rating）。"""
    async with async_session() as db:
        lookback = target_date - timedelta(days=5)
        stmt = (
            select(StockRSRating.ts_code, StockRSRating.rs_rating)
            .where(
                and_(
                    StockRSRating.trade_date >= lookback,
                    StockRSRating.trade_date <= target_date,
                )
            )
            .order_by(StockRSRating.ts_code, StockRSRating.trade_date.desc())
        )
        result = await db.execute(stmt)
        rows = result.all()

    rs_map: dict[str, int] = {}
    for ts_code, rs_rating in rows:
        if ts_code not in rs_map:
            rs_map[ts_code] = rs_rating
    return rs_map


# ═══════════════════════════════════════════════════════════
#  实体提取 + 聚合
# ═══════════════════════════════════════════════════════════

def _extract_entities_from_news(news_list: list[dict]) -> list[str]:
    """从高分新闻中提取所有可能的公司名/实体名。

    来源：
      - tags 数组中的每个标签
      - sentiment_entity 字段
    过滤：
      - 排除纯数字、太短（<2字符）、明显非公司名的标签
    """
    # 已知非公司名的关键词集合（过滤用）
    _EXCLUDE_KEYWORDS = {
        "A股", "港股", "美股", "沪深", "创业板", "科创板", "北交所",
        "利好", "利空", "涨停", "跌停", "大盘", "行情", "机构",
        "基金", "ETF", "央行", "财政部", "证监会", "交易所",
        "宏观", "GDP", "CPI", "PMI", "LPR", "MLF",
    }

    entities: list[str] = []
    seen: set[str] = set()

    for news in news_list:
        # 从 tags 中提取
        for tag in news.get("tags", []):
            tag = tag.strip()
            if (
                len(tag) >= 2
                and tag not in _EXCLUDE_KEYWORDS
                and not tag.isdigit()
                and tag not in seen
            ):
                # 排除纯英文短标签（大概率是分类标签）
                if len(tag) <= 3 and tag.isascii():
                    continue
                seen.add(tag)
                entities.append(tag)

        # 从 sentiment_entity 中提取
        entity = news.get("sentiment_entity", "").strip()
        if entity and entity not in seen and len(entity) >= 2 and entity not in _EXCLUDE_KEYWORDS:
            seen.add(entity)
            entities.append(entity)

    return entities


def _aggregate_by_ticker(
    news_list: list[dict],
    entity_ticker_map: dict[str, str | None],
) -> dict[str, dict]:
    """按 ts_code 聚合催化剂信息。

    Returns:
        {ts_code: {news_count, top_score, total_score, catalyst_types, titles, sentiments}}
    """
    agg: dict[str, dict] = defaultdict(lambda: {
        "news_count": 0,
        "top_score": 0,
        "total_score": 0,
        "catalyst_types": set(),
        "titles": [],
        "sentiments": [],
    })

    for news in news_list:
        # 找出这条新闻匹配到的所有 ts_code
        matched_codes: set[str] = set()

        # 从 tags 中匹配
        for tag in news.get("tags", []):
            tag = tag.strip()
            code = entity_ticker_map.get(tag)
            if code:
                matched_codes.add(code)

        # 从 sentiment_entity 中匹配
        entity = news.get("sentiment_entity", "").strip()
        if entity:
            code = entity_ticker_map.get(entity)
            if code:
                matched_codes.add(code)

        # 如果新闻标题或 tags 中直接包含 A 股代码，也匹配
        for tag in news.get("tags", []):
            m = _TS_CODE_PATTERN.search(tag)
            if m:
                matched_codes.add(f"{m.group(1)}.{m.group(2).upper()}")

        # 聚合到每个匹配的 ts_code
        for code in matched_codes:
            entry = agg[code]
            entry["news_count"] += 1
            entry["top_score"] = max(entry["top_score"], news.get("ai_score", 0))
            entry["total_score"] += news.get("ai_score", 0)
            if news.get("catalyst_type"):
                entry["catalyst_types"].add(news["catalyst_type"])
            entry["titles"].append(news["title"][:80])
            if news.get("sentiment_score") is not None:
                entry["sentiments"].append(news["sentiment_score"])

    return dict(agg)


# ═══════════════════════════════════════════════════════════
#  交叉验证 + 写入
# ═══════════════════════════════════════════════════════════

def _compute_heat_score(news_count: int, top_score: int, avg_sentiment: float) -> float:
    """计算催化剂热度评分。

    公式：news_count × top_score + sentiment_bonus
    sentiment_bonus: 正面情绪加分（avg_sentiment > 0 时 × 2）
    """
    base = news_count * top_score
    sentiment_bonus = max(avg_sentiment, 0) * 2 if avg_sentiment else 0
    return round(base + sentiment_bonus, 2)


def _determine_confirm_level(
    in_vcp: bool, in_trend: bool, rs_rating: int | None
) -> str:
    """确定交叉验证分类。"""
    if in_vcp or in_trend:
        return "double_confirmed"
    if rs_rating is not None and rs_rating >= 80:
        return "strong_rs"
    return "catalyst_only"


async def _save_catalyst_stocks(
    target_date: date,
    stocks: list[dict],
) -> int:
    """写入催化剂标的到数据库（upsert 模式，同一天同一只票只保留最新）。"""
    if not stocks:
        return 0

    async with async_session() as db:
        # 先删除当日旧数据
        await db.execute(
            delete(NewsCatalystStock).where(
                NewsCatalystStock.catalyst_date == target_date
            )
        )

        # 批量插入
        for s in stocks:
            record = NewsCatalystStock(
                catalyst_date=target_date,
                ts_code=s["ts_code"],
                name=s.get("name"),
                news_count=s["news_count"],
                top_score=s["top_score"],
                avg_score=s["avg_score"],
                catalyst_types=s.get("catalyst_types"),
                catalyst_summary=s.get("catalyst_summary"),
                avg_sentiment=s.get("avg_sentiment"),
                news_titles=s.get("news_titles"),
                in_vcp=s.get("in_vcp", False),
                vcp_score=s.get("vcp_score"),
                in_trend=s.get("in_trend", False),
                trend_score=s.get("trend_score"),
                rs_rating=s.get("rs_rating"),
                heat_score=s["heat_score"],
                confirm_level=s["confirm_level"],
            )
            db.add(record)

        await db.commit()

    return len(stocks)


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

async def run_catalyst_aggregation(target_date: date | None = None) -> dict:
    """执行催化剂标的聚合 pipeline。

    Returns:
        {"status": "ok"/"empty", "total": N, "double_confirmed": N, ...}
    """
    if target_date is None:
        target_date = datetime.now(_TZ).date()

    logger.info("Catalyst aggregation started for %s", target_date)
    t0 = time.monotonic()

    # ── 1. 收集高分新闻 ──
    news_list = await _fetch_high_score_news(target_date)
    if not news_list:
        logger.info("No high-score news for %s, skipping catalyst aggregation", target_date)
        # 清空当日数据
        async with async_session() as db:
            await db.execute(
                delete(NewsCatalystStock).where(
                    NewsCatalystStock.catalyst_date == target_date
                )
            )
            await db.commit()
        return {"status": "empty", "total": 0}

    logger.info("Found %d high-score news for catalyst extraction", len(news_list))

    # ── 2. 提取实体名 ──
    entities = _extract_entities_from_news(news_list)
    logger.info("Extracted %d unique entities from news", len(entities))

    if not entities:
        logger.info("No entities extracted, skipping")
        return {"status": "empty", "total": 0}

    # ── 3. LLM 映射公司名 → ts_code ──
    entity_ticker_map = await _map_entities_to_tickers(entities)
    mapped_count = sum(1 for v in entity_ticker_map.values() if v is not None)
    logger.info("Entity-to-ticker mapping: %d/%d mapped", mapped_count, len(entities))

    # ── 4. 按 ts_code 聚合 ──
    aggregated = _aggregate_by_ticker(news_list, entity_ticker_map)
    if not aggregated:
        logger.info("No A-share stocks aggregated from news, skipping")
        return {"status": "empty", "total": 0}

    logger.info("Aggregated %d unique A-share stocks from news", len(aggregated))

    # ── 5. 并行获取交叉验证数据 ──
    vcp_task = asyncio.create_task(_fetch_vcp_map(target_date))
    trend_task = asyncio.create_task(_fetch_trend_map(target_date))
    rs_task = asyncio.create_task(_fetch_rs_map(target_date))

    vcp_map = await vcp_task
    trend_map = await trend_task
    rs_map = await rs_task

    logger.info("Cross-validation data: VCP=%d, Trend=%d, RS=%d",
                len(vcp_map), len(trend_map), len(rs_map))

    # ── 6. 构建催化剂标的列表 ──
    catalyst_stocks: list[dict] = []

    for ts_code, agg_data in aggregated.items():
        # 基本聚合指标
        news_count = agg_data["news_count"]
        top_score = agg_data["top_score"]
        avg_score = round(agg_data["total_score"] / news_count, 1) if news_count else 0
        catalyst_types = sorted(agg_data["catalyst_types"]) if agg_data["catalyst_types"] else None
        titles = agg_data["titles"][:5]  # 最多保留 5 条标题
        sentiments = agg_data["sentiments"]
        avg_sentiment = round(sum(sentiments) / len(sentiments), 1) if sentiments else None

        # 交叉验证
        in_vcp = ts_code in vcp_map
        vcp_score_val = vcp_map[ts_code]["vcp_score"] if in_vcp else None
        in_trend = ts_code in trend_map
        trend_score_val = trend_map[ts_code]["trend_score"] if in_trend else None
        rs_val = rs_map.get(ts_code)

        # 股票名称（优先从白名单获取）
        name = None
        if in_vcp:
            name = vcp_map[ts_code].get("name")
        elif in_trend:
            name = trend_map[ts_code].get("name")

        # 催化剂热度
        heat = _compute_heat_score(news_count, top_score, avg_sentiment or 0)
        confirm = _determine_confirm_level(in_vcp, in_trend, rs_val)

        # 催化剂摘要（取第一条新闻标题作为简要概述）
        summary = titles[0] if titles else None

        catalyst_stocks.append({
            "ts_code": ts_code,
            "name": name,
            "news_count": news_count,
            "top_score": top_score,
            "avg_score": avg_score,
            "catalyst_types": catalyst_types,
            "catalyst_summary": summary,
            "avg_sentiment": avg_sentiment,
            "news_titles": titles,
            "in_vcp": in_vcp,
            "vcp_score": vcp_score_val,
            "in_trend": in_trend,
            "trend_score": trend_score_val,
            "rs_rating": rs_val,
            "heat_score": heat,
            "confirm_level": confirm,
        })

    # 按热度降序排序
    catalyst_stocks.sort(key=lambda x: x["heat_score"], reverse=True)

    # ── 7. 写入数据库 ──
    saved = await _save_catalyst_stocks(target_date, catalyst_stocks)

    elapsed = time.monotonic() - t0

    # 统计
    double_confirmed = sum(1 for s in catalyst_stocks if s["confirm_level"] == "double_confirmed")
    strong_rs = sum(1 for s in catalyst_stocks if s["confirm_level"] == "strong_rs")
    catalyst_only = sum(1 for s in catalyst_stocks if s["confirm_level"] == "catalyst_only")

    logger.info(
        "Catalyst aggregation done: %d stocks (🔥 double=%d, 💪 strong_rs=%d, 👀 only=%d), %.1fs",
        saved, double_confirmed, strong_rs, catalyst_only, elapsed,
    )

    return {
        "status": "ok",
        "total": saved,
        "double_confirmed": double_confirmed,
        "strong_rs": strong_rs,
        "catalyst_only": catalyst_only,
        "elapsed_sec": round(elapsed, 1),
        "news_count": len(news_list),
        "entities_extracted": len(entities),
        "entities_mapped": mapped_count,
    }
