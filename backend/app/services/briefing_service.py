"""Daily Briefing Service — 每日综合分析报告生成（v2）。

两阶段 pipeline：
  Stage 1  LLM 判断：将今日新闻摘要 × 合并股票池（VCP + 趋势 + 价投）发给
           DeepSeek，让它判定每只股票受哪些新闻 "利好催化 / 中性 / 利空风险"。
           输出 JSON，不生成任何文字报告。
  Stage 2  代码渲染：根据 JSON 分类结果 + 行情数据，用 Python 拼接出精美、
           格式固定的 Markdown 研报。格式完全可控，无 LLM 幻觉。

节省 tokens 策略：
  - LLM 只做判断不做写作 → 输出 ~500 tokens（原 3000）
  - 新闻摘要只传 content 前 500 字
  - 限制 max_tokens=1500
"""

from __future__ import annotations

import json as _json
import logging
import re
import time
from datetime import date, datetime, timedelta

import pytz
from sqlalchemy import select, and_

from app.config import settings
from app.database import async_session
from app.models.daily_briefing import DailyBriefing
from app.models.news import News
from app.models.news_digest import NewsDigest
from app.models.screener import WatchlistDaily, TrendWatchlistDaily
from app.models.stock import StockDailyQuote, StockRSRating
from app.services.llm_client import stream_chat

logger = logging.getLogger("alphareader.briefing")

_TZ = pytz.timezone(settings.TIMEZONE)

# ═══════════════════════════════════════════════════════════
#  Stage 1 — LLM Prompt（新闻 × 股票关联判断）
# ═══════════════════════════════════════════════════════════

CATALYST_SYSTEM_PROMPT = """\
你是 A 股短线交易助手。你的任务是：根据今日新闻摘要，判定给定股票池中每只股票与新闻的关联程度。

## 输入
- 今日新闻摘要（按时段分组）
- 统一股票池（包含 VCP / 趋势 / 价投 三种策略来源的股票）

## 判定规则
对每只股票，判定其属于以下 3 个分类之一：

**S（重点狙击）**：该股票被今日新闻中至少一条消息 **明确利好/催化**。
  例如：公司发布超预期业绩、获重大合同、所在行业受政策扶持、产品涨价等。
  → 必须附上 1 句话催化逻辑。

**A（常规盯防）**：无明显新闻关联，或新闻与该股票/行业无直接关系。

**X（风险剔除）**：该股票命中今日新闻中的 **明确利空/风险**。
  例如：股东减持、业绩不及预期、行业利空政策、重大诉讼等。
  → 必须附上 1 句话风险提示。

## 输出格式（严格 JSON，不要附加任何文字）

```json
{
  "market_sentiment": "偏多|中性|偏空",
  "market_summary": "1-2句话概括今日市场核心主线",
  "tiers": {
    "S": [
      {"code": "000001.SZ", "reason": "催化逻辑..."}
    ],
    "A": [
      {"code": "600519.SH"}
    ],
    "X": [
      {"code": "300750.SZ", "reason": "风险提示..."}
    ]
  }
}
```

## ⚠️ 严格约束（违反将导致输出无效）
- code **必须**使用输入"统一股票池"中给出的完整 ts_code（如 000001.SZ），**禁止**使用任何不在输入列表中的 code
- **所有** 输入股票必须出现在输出的 S / A / X 三个列表之一中，不可遗漏
- S + A + X 的 code 总数必须等于输入股票池总数
- 没有理由强行归入 S 或 X，宁可放入 A
- 只输出 JSON，不要有任何其他文字、解释、markdown
"""


# ═══════════════════════════════════════════════════════════
#  数据收集
# ═══════════════════════════════════════════════════════════

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
            "strategy": "VCP",
            "price": r.current_price,
            "score": r.vcp_score,
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
            "strategy": "趋势",
            "price": r.current_price,
            "score": r.trend_score,
            "ma20": r.ma20,
            "ma50": r.ma50,
            "adx": r.adx,
            "rsi": r.rsi,
            "volume_ratio": r.volume_ratio,
            "industry": r.industry,
            "concepts": (r.concepts or "")[:100],
            "fund_flow": r.fund_flow_net,
        }
        for r in rows
    ]


async def _fetch_value_stocks(target_date: date) -> list[dict]:
    """获取价投观察池中状态为 watching/holding 的标的。"""
    from app.models.sandbox import SandboxStock

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
            "strategy": "价投",
            "industry": "",
            "concepts": "",
        }
        for r in rows
    ]


async def _fetch_stock_quotes(ts_codes: list[str], target_date: date) -> dict[str, dict]:
    """批量获取指定股票的当日行情。"""
    if not ts_codes:
        return {}

    async with async_session() as db:
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
            "content": (r.content or "")[:500],
        }
        for r in rows
    ]


async def _fetch_high_score_news(target_date: date, min_score: int = 6) -> list[dict]:
    """获取当日高评分原始新闻（用于更精确的关联分析）。"""
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
            .limit(30)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    return [
        {
            "title": r.title,
            "summary": (r.ai_summary or r.title)[:200],
            "score": r.ai_score,
            "catalyst_type": r.catalyst_type or "",
            "sentiment_entity": r.sentiment_entity or "",
            "tags": r.tags or [],
        }
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════
#  Stage 1 — LLM 调用（新闻×股票关联判断）
# ═══════════════════════════════════════════════════════════

def _build_catalyst_prompt(
    target_date: date,
    pool: list[dict],
    digests: list[dict],
    top_news: list[dict],
) -> str:
    """构建 Stage 1 的 user prompt。"""
    parts = [f"# 日期: {target_date}\n"]

    # 新闻部分
    parts.append("## 今日新闻摘要\n")
    if digests:
        for d in digests:
            parts.append(f"### {d['period']}（{d['news_count']}条）")
            parts.append(d["content"])
            parts.append("")

    if top_news:
        parts.append("### 高分新闻速报")
        for n in top_news:
            tags_str = ", ".join(n["tags"][:5]) if n["tags"] else ""
            entity = f" [{n['sentiment_entity']}]" if n["sentiment_entity"] else ""
            parts.append(
                f"- 【{n['score']}分】{n['title']}{entity}"
                + (f" — {tags_str}" if tags_str else "")
            )
        parts.append("")

    # 股票池部分
    parts.append(f"## 统一股票池（{len(pool)} 只）\n")
    # 先列出所有合法 code，让 LLM 明确知道只能用这些
    all_codes = [s['ts_code'] for s in pool]
    parts.append(f"**合法 code 列表（输出中只允许使用以下 code）：** {', '.join(all_codes)}\n")
    for s in pool:
        line = f"- {s['name']}（{s['ts_code']}）| 策略:{s['strategy']} | 行业:{s.get('industry', 'N/A')}"
        concepts = s.get("concepts", "")
        if concepts:
            line += f" | 题材:{concepts[:60]}"
        parts.append(line)

    parts.append("\n请按照 system prompt 的要求，输出 JSON 判定结果。")
    return "\n".join(parts)


async def _call_deepseek_catalyst(user_prompt: str) -> dict | None:
    """调用 DeepSeek 做新闻-股票关联判断，返回解析后的 dict。

    流式调用由 llm_client.stream_chat 统一封装（含重试）；本函数负责 JSON 提取与校验。
    """
    raw = await stream_chat(
        [
            {"role": "system", "content": CATALYST_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1500,
        log_tag="Catalyst",
    )

    if not raw:
        return None

    # 提取 JSON（LLM 可能包裹在 ```json ... ``` 中）
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        logger.warning("No JSON found in catalyst response: %s", raw[:300])
        return None

    try:
        result = _json.loads(json_match.group())
    except _json.JSONDecodeError as e:
        logger.error("Catalyst JSON parse error: %s", e)
        return None

    logger.info("Catalyst analysis complete: S=%d, A=%d, X=%d",
                len(result.get("tiers", {}).get("S", [])),
                len(result.get("tiers", {}).get("A", [])),
                len(result.get("tiers", {}).get("X", [])))
    return result


def _normalize_tier_codes(catalyst: dict, pool_map: dict[str, dict]) -> dict:
    """标准化 LLM 返回的 tiers 中的 code，使其匹配 pool_map 的 key。

    LLM 可能返回 '000001.SZ'（完整）、'000001'（无后缀）、'000001.sz'（小写后缀）等，
    需要统一映射到 pool_map 中的实际 key（如 '000001.SZ'）。
    """
    # 构建反向索引：纯数字 code → 完整 ts_code
    code_index: dict[str, str] = {}
    for full_code in pool_map:
        code_index[full_code] = full_code
        code_index[full_code.upper()] = full_code
        code_index[full_code.lower()] = full_code
        base = full_code.split(".")[0]
        code_index[base] = full_code

    tiers = catalyst.get("tiers", {})
    normalized_count = 0
    for tier_key in ("S", "A", "X"):
        items = tiers.get(tier_key, [])
        for item in items:
            raw_code = item.get("code", "")
            if raw_code not in pool_map:
                mapped = (
                    code_index.get(raw_code)
                    or code_index.get(raw_code.upper())
                    or code_index.get(raw_code.lower())
                )
                if mapped:
                    item["code"] = mapped
                    normalized_count += 1
                else:
                    logger.warning("Unknown code in tier %s: %s (not in pool_map)", tier_key, raw_code)

    if normalized_count:
        logger.info("Normalized %d tier codes to match pool_map", normalized_count)

    return catalyst


def _validate_and_fix_tiers(catalyst: dict, pool_map: dict[str, dict]) -> dict:
    """校验 LLM 返回的 tiers 结果，确保所有 pool_map 中的股票都被覆盖。

    修正策略：
    1. 移除 LLM 编造的、不在 pool_map 中的 code
    2. pool_map 中未被覆盖的股票自动补入 Tier A
    """
    tiers = catalyst.get("tiers", {})
    all_pool_codes = set(pool_map.keys())

    # 收集 LLM 覆盖的有效 codes，同时清理无效 codes
    covered_codes: set[str] = set()
    for tier_key in ("S", "A", "X"):
        items = tiers.get(tier_key, [])
        valid_items = []
        for item in items:
            code = item.get("code", "")
            if code in all_pool_codes:
                valid_items.append(item)
                covered_codes.add(code)
            else:
                logger.warning("Removing invalid code from tier %s: %s", tier_key, code)
        tiers[tier_key] = valid_items

    # 找出未被覆盖的股票，补入 Tier A
    missing_codes = all_pool_codes - covered_codes
    if missing_codes:
        logger.warning(
            "LLM missed %d/%d stocks, auto-adding to Tier A: %s",
            len(missing_codes), len(all_pool_codes),
            ", ".join(sorted(missing_codes)[:10]),
        )
        a_items = tiers.get("A", [])
        for code in sorted(missing_codes):
            a_items.append({"code": code})
        tiers["A"] = a_items

    catalyst["tiers"] = tiers

    logger.info(
        "Tiers after validation: S=%d, A=%d, X=%d (pool=%d)",
        len(tiers.get("S", [])), len(tiers.get("A", [])),
        len(tiers.get("X", [])), len(all_pool_codes),
    )
    return catalyst


# ═══════════════════════════════════════════════════════════
#  Stage 2 — 代码渲染精美 Markdown 研报
# ═══════════════════════════════════════════════════════════

def _fmt(val, fmt_str: str = ".2f", fallback: str = "—") -> str:
    """安全格式化数值。"""
    if val is None:
        return fallback
    try:
        return f"{val:{fmt_str}}"
    except (ValueError, TypeError):
        return fallback


def _pct_badge(pct) -> str:
    """涨跌幅格式化（带 emoji）。"""
    if pct is None:
        return "—"
    if pct > 0:
        return f"🔴 +{pct:.2f}%"
    elif pct < 0:
        return f"🟢 {pct:.2f}%"
    return f"⚪ {pct:.2f}%"


def _render_stock_row(
    s: dict,
    quote: dict,
    rs: int | str,
    reason: str | None = None,
) -> str:
    """渲染单只股票的 Markdown 段落。"""
    code = s["ts_code"]
    name = s["name"]
    strategy = s.get("strategy", "")
    price = _fmt(quote.get("close") or s.get("price"), ".2f")
    pct = _pct_badge(quote.get("pct_change"))
    amount = quote.get("amount")
    amount_str = f"{amount / 10000:.0f}万" if amount else "—"
    turnover = _fmt(quote.get("turnover"), ".1f")
    industry = s.get("industry", "—") or "—"

    # 构建指标行
    if strategy == "VCP":
        score_label = f"VCP {_fmt(s.get('score'), '.1f')}"
        tech = f"EMA20 {_fmt(s.get('ema20'), '.2f')} / EMA50 {_fmt(s.get('ema50'), '.2f')}"
    elif strategy == "趋势":
        score_label = f"趋势 {_fmt(s.get('score'), '.1f')}"
        adx = _fmt(s.get('adx'), '.1f')
        rsi = _fmt(s.get('rsi'), '.1f')
        vr = _fmt(s.get('volume_ratio'), '.1f')
        tech = f"ADX {adx} / RSI {rsi} / 放量 {vr}x"
    else:
        score_label = strategy
        tech = ""

    lines = [
        f"**{name}** `{code}`",
        f"",
        f"| 指标 | 数值 |",
        f"|:---|:---|",
        f"| 策略来源 | {score_label} |",
        f"| 最新价 | {price} |",
        f"| 今日涨跌 | {pct} |",
        f"| RS 评分 | {rs} |",
        f"| 行业 | {industry} |",
    ]
    if tech:
        lines.append(f"| 技术指标 | {tech} |")
    lines.append(f"| 成交额 | {amount_str} |")
    lines.append(f"| 换手率 | {turnover}% |")

    if reason:
        lines.append(f"")
        lines.append(f"> {reason}")

    return "\n".join(lines)


def _render_briefing_markdown(
    target_date: date,
    catalyst: dict,
    pool_map: dict[str, dict],
    quotes: dict[str, dict],
    rs_ratings: dict[str, int],
    digests: list[dict],
    top_news: list[dict],
    pool_stats: dict,
) -> str:
    """Stage 2：根据 LLM 判定结果 + 数据，拼接精美 Markdown 研报。"""

    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    wd = weekdays[target_date.weekday()]
    date_str = f"{target_date.year}年{target_date.month}月{target_date.day}日"

    tiers = catalyst.get("tiers", {})
    tier_s = tiers.get("S", [])
    tier_a = tiers.get("A", [])
    tier_x = tiers.get("X", [])

    # 构建 reason 映射
    s_reasons = {item["code"]: item.get("reason", "") for item in tier_s}
    x_reasons = {item["code"]: item.get("reason", "") for item in tier_x}
    s_codes = set(s_reasons.keys())
    a_codes = {item["code"] for item in tier_a}
    x_codes = set(x_reasons.keys())

    sentiment = catalyst.get("market_sentiment", "中性")
    market_summary = catalyst.get("market_summary", "")

    # 情绪 emoji
    sentiment_emoji = {"偏多": "🟢", "中性": "🟡", "偏空": "🔴"}.get(sentiment, "🟡")

    sections = []

    # ── 标题 ──
    sections.append(f"# 📊 每日投资研报")
    sections.append(f"")
    sections.append(f"> **{date_str} {wd}** · 股票池 {len(pool_map)} 只 · VCP {pool_stats.get('vcp', 0)} / 趋势 {pool_stats.get('trend', 0)} / 价投 {pool_stats.get('value', 0)}")
    sections.append(f"")

    # ── 市场情绪 ──
    sections.append(f"## {sentiment_emoji} 市场情绪：{sentiment}")
    sections.append(f"")
    if market_summary:
        sections.append(f"{market_summary}")
        sections.append(f"")

    # ── 今日要闻速报 ──
    if top_news:
        sections.append(f"## 📰 今日要闻速报")
        sections.append(f"")
        for n in top_news[:10]:
            score = n["score"]
            # 评分对应的 emoji
            if score >= 8:
                icon = "🔥"
            elif score >= 6:
                icon = "📌"
            else:
                icon = "📋"
            entity = f" `{n['sentiment_entity']}`" if n.get("sentiment_entity") else ""
            sections.append(f"- {icon} **{n['title']}**{entity}")
        sections.append(f"")

    # ── Tier S：重点狙击 ──
    sections.append(f"---")
    sections.append(f"")
    sections.append(f"## 🎯 Tier S · 重点狙击")
    sections.append(f"")
    if tier_s:
        sections.append(f"> 命中今日消息面明确利好催化的标的，建议重点关注。")
        sections.append(f"")
        for item in tier_s:
            code = item["code"]
            s = pool_map.get(code)
            if not s:
                continue
            q = quotes.get(code, {})
            rs = rs_ratings.get(code, "—")
            reason = item.get("reason", "")
            sections.append(_render_stock_row(s, q, rs, f"🔥 **催化逻辑**：{reason}" if reason else None))
            sections.append(f"")
    else:
        sections.append(f"*今日无明确利好催化命中，全部标的归入常规盯防。*")
        sections.append(f"")

    # ── Tier A：常规盯防 ──
    sections.append(f"---")
    sections.append(f"")
    sections.append(f"## 📋 Tier A · 常规盯防")
    sections.append(f"")
    if tier_a:
        sections.append(f"> 无明显消息关联的标的，按原有策略信号跟踪。")
        sections.append(f"")
        # Tier A 用简洁表格展示
        sections.append(f"| 股票 | 策略 | 最新价 | 涨跌 | RS | 行业 | 成交额 |")
        sections.append(f"|:---|:---|---:|:---|---:|:---|---:|")
        for item in tier_a:
            code = item["code"]
            s = pool_map.get(code)
            if not s:
                continue
            q = quotes.get(code, {})
            rs = rs_ratings.get(code, "—")
            price = _fmt(q.get("close") or s.get("price"), ".2f")
            pct_raw = q.get("pct_change")
            if pct_raw is not None:
                pct_str = f"+{pct_raw:.2f}%" if pct_raw > 0 else f"{pct_raw:.2f}%"
            else:
                pct_str = "—"
            amount = q.get("amount")
            amount_str = f"{amount / 10000:.0f}万" if amount else "—"
            industry = s.get("industry", "—") or "—"
            sections.append(
                f"| **{s['name']}** `{code}` | {s.get('strategy', '')} | {price} | {pct_str} | {rs} | {industry} | {amount_str} |"
            )
        sections.append(f"")
    else:
        sections.append(f"*所有标的已被分入 Tier S 或 Tier X。*")
        sections.append(f"")

    # ── Tier X：风险剔除 ──
    sections.append(f"---")
    sections.append(f"")
    sections.append(f"## ⚠️ Tier X · 风险剔除")
    sections.append(f"")
    if tier_x:
        sections.append(f"> 命中今日消息面利空信号，建议规避或减仓。")
        sections.append(f"")
        for item in tier_x:
            code = item["code"]
            s = pool_map.get(code)
            if not s:
                continue
            q = quotes.get(code, {})
            rs = rs_ratings.get(code, "—")
            reason = item.get("reason", "")
            sections.append(_render_stock_row(s, q, rs, f"⚠️ **风险提示**：{reason}" if reason else None))
            sections.append(f"")
    else:
        sections.append(f"*今日无利空信号命中，股票池整体安全。* ✅")
        sections.append(f"")

    # ── Tier 统计概览 ──
    sections.append(f"---")
    sections.append(f"")
    sections.append(f"## 📈 Tier 分布概览")
    sections.append(f"")
    total = len(tier_s) + len(tier_a) + len(tier_x)
    if total > 0:
        s_pct = len(tier_s) / total * 100
        a_pct = len(tier_a) / total * 100
        x_pct = len(tier_x) / total * 100
        sections.append(f"| Tier | 数量 | 占比 | 含义 |")
        sections.append(f"|:---|---:|---:|:---|")
        sections.append(f"| 🎯 **S** | {len(tier_s)} | {s_pct:.0f}% | 重点狙击 |")
        sections.append(f"| 📋 **A** | {len(tier_a)} | {a_pct:.0f}% | 常规盯防 |")
        sections.append(f"| ⚠️ **X** | {len(tier_x)} | {x_pct:.0f}% | 风险剔除 |")
        sections.append(f"| **合计** | **{total}** | 100% | |")
    sections.append(f"")

    # ── 免责声明 ──
    sections.append(f"---")
    sections.append(f"")
    sections.append(f"*本报告由 AlphaReader AI 自动生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。*")

    return "\n".join(sections)


def _render_fallback_briefing(
    target_date: date,
    pool_map: dict[str, dict],
    quotes: dict[str, dict],
    rs_ratings: dict[str, int],
    pool_stats: dict,
) -> str:
    """LLM 分析失败时的兜底：所有股票归入 Tier A，不做新闻关联。"""
    # 构建一个全 A 的 catalyst 结果
    fallback_catalyst = {
        "market_sentiment": "中性",
        "market_summary": "AI 新闻关联分析暂不可用，所有标的按常规盯防处理。",
        "tiers": {
            "S": [],
            "A": [{"code": code} for code in pool_map.keys()],
            "X": [],
        },
    }
    return _render_briefing_markdown(
        target_date, fallback_catalyst, pool_map, quotes, rs_ratings, [], [], pool_stats,
    )


# ═══════════════════════════════════════════════════════════
#  存储
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

async def generate_briefing(target_date: date | None = None) -> dict:
    """生成每日综合分析报告（v2 两阶段 pipeline）。

    Returns:
        {"status": "ok"/"empty"/"failed", "tier_s": N, "tier_a": N, "tier_x": N, ...}
    """
    if target_date is None:
        target_date = datetime.now(_TZ).date()

    logger.info("Generating daily briefing (v2) for %s", target_date)
    t0 = time.monotonic()

    # ── 1. 并行收集所有数据 ──
    import asyncio

    vcp_task = asyncio.create_task(_fetch_vcp_watchlist(target_date))
    trend_task = asyncio.create_task(_fetch_trend_watchlist(target_date))
    value_task = asyncio.create_task(_fetch_value_stocks(target_date))
    digest_task = asyncio.create_task(_fetch_news_digests(target_date))
    news_task = asyncio.create_task(_fetch_high_score_news(target_date))

    vcp_list = await vcp_task
    trend_list = await trend_task
    value_list = await value_task
    digests = await digest_task
    top_news = await news_task

    # 合并统一股票池（去重，VCP 优先）
    pool_map: dict[str, dict] = {}
    for s in vcp_list:
        pool_map[s["ts_code"]] = s
    for s in trend_list:
        if s["ts_code"] not in pool_map:
            pool_map[s["ts_code"]] = s
    for s in value_list:
        if s["ts_code"] not in pool_map:
            pool_map[s["ts_code"]] = s

    pool_list = list(pool_map.values())

    all_codes = list(pool_map.keys())

    quotes_task = asyncio.create_task(_fetch_stock_quotes(all_codes, target_date))
    rs_task = asyncio.create_task(_fetch_rs_ratings(all_codes, target_date))
    quotes = await quotes_task
    rs_ratings = await rs_task

    pool_stats = {
        "vcp": len(vcp_list),
        "trend": len(trend_list),
        "value": len(value_list),
    }

    logger.info(
        "Data collected: VCP=%d, Trend=%d, Value=%d, Pool=%d, Digests=%d, TopNews=%d",
        len(vcp_list), len(trend_list), len(value_list),
        len(pool_map), len(digests), len(top_news),
    )

    # 如果股票池为空且无新闻，跳过
    if len(pool_map) == 0 and len(digests) == 0:
        logger.info("No data available for briefing on %s, skipping", target_date)
        await _save_briefing(target_date, "今日无可用数据，跳过分析报告生成。", {}, 0, 0, "empty")
        return {"status": "empty", "tier_s": 0, "tier_a": 0, "tier_x": 0}

    # ── 2. Stage 1：LLM 新闻-股票关联判断 ──
    catalyst_prompt = _build_catalyst_prompt(target_date, pool_list, digests, top_news)
    prompt_tokens_est = len(catalyst_prompt) // 2

    logger.info("Catalyst prompt: ~%d chars, ~%d tokens est.", len(catalyst_prompt), prompt_tokens_est)

    catalyst = await _call_deepseek_catalyst(catalyst_prompt)

    # ── 2.5 标准化 + 校验 LLM 返回的 tiers ──
    if catalyst:
        catalyst = _normalize_tier_codes(catalyst, pool_map)
        catalyst = _validate_and_fix_tiers(catalyst, pool_map)

    # ── 3. Stage 2：代码渲染 Markdown ──
    if catalyst:
        content = _render_briefing_markdown(
            target_date, catalyst, pool_map, quotes, rs_ratings, digests, top_news, pool_stats,
        )
    else:
        logger.warning("Catalyst analysis failed, using fallback rendering")
        content = _render_fallback_briefing(
            target_date, pool_map, quotes, rs_ratings, pool_stats,
        )

    generation_sec = time.monotonic() - t0

    tiers = catalyst.get("tiers", {}) if catalyst else {}
    tier_s_count = len(tiers.get("S", []))
    tier_a_count = len(tiers.get("A", []))
    tier_x_count = len(tiers.get("X", []))

    meta = {
        "vcp_count": len(vcp_list),
        "trend_count": len(trend_list),
        "value_count": len(value_list),
        "pool_count": len(pool_map),
        "digest_count": len(digests),
        "tier_s": tier_s_count,
        "tier_a": tier_a_count,
        "tier_x": tier_x_count,
        "market_sentiment": catalyst.get("market_sentiment", "中性") if catalyst else "中性",
    }

    # 保存
    await _save_briefing(target_date, content, meta, prompt_tokens_est, generation_sec, "ok")

    logger.info(
        "Briefing saved: %s, %d chars, %.1fs, S=%d A=%d X=%d",
        target_date, len(content), generation_sec,
        tier_s_count, tier_a_count, tier_x_count,
    )
    return {
        "status": "ok",
        "content_length": len(content),
        "generation_sec": round(generation_sec, 1),
        **meta,
    }
