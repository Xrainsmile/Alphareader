"""DeepSeek Filter Service — batch scoring via DeepSeek-V3 API.

Strategy (from spec):
  - Buffer news items, send in batches of up to 20.
  - System prompt instructs the model to act as a senior financial analyst.
  - For English content: translate title + summary to Chinese in a single pass.
  - Response: JSON array of {id, score, reason, summary, tags, ...}.
  - Discard items with score < 6.
  - Retry up to 2 times on transient failures.

Robustness:
  - No response_format constraint (DeepSeek compatibility).
  - Multi-layer JSON extraction: direct parse → code fence strip → regex fallback.
  - Per-item error tolerance: bad items are skipped, not fatal.
  - Smart error handling: "Content Exists Risk" (400) → skip batch, no retry.
  - 5xx / 429 / timeout → exponential backoff retry.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

import httpx
from langdetect import detect, LangDetectException

from app.config import settings
from app.services.rss_fetcher import RawNewsItem
from app.utils.json_extractor import extract_json_from_deepseek

logger = logging.getLogger("alphareader.deepseek")

# Non-retryable error signatures from DeepSeek Trust & Safety
_CONTENT_RISK_KEYWORDS = ("Content Exists Risk", "content_filter", "content_policy")

# ── System Prompt: Chinese news ──
SYSTEM_PROMPT_CN = """你是一个资深金融分析师。我会给你一批新闻标题和摘要。
请判断哪些新闻对「A股/港股/美股」市场有实质性财务影响。

判断标准：
- 保留：含具体财务数据（营收、净利、增长率）、重大政策变动、央行动作、行业重大事件
- 丢弃：口水文、政策喊话无数据、娱乐八卦、推广软文、无实质信息的评论

⚠️ 输出格式要求（极其重要）：
- 仅返回原始 JSON 数组，不要输出任何其他内容。
- 禁止使用 <think> 标签或任何 XML 标签。
- 禁止使用 Markdown 代码块（```）包裹。
- 禁止在 JSON 前后添加解释文字、开场白或总结。

JSON 格式：
[{"id": 1, "score": 8, "reason": "含具体营收数据", "summary": "一句话摘要不超过50字", "tags": ["新能源", "财报"]}, ...]

规则：
- id 对应新闻编号（从1开始）
- score 范围 0-10，10 为最高价值
- summary 不超过 50 字
- tags 提取 1-3 个行业/板块标签
- 每条新闻都必须评分，即使是低分"""

# ── System Prompt: English news (translation-enhanced) ──
SYSTEM_PROMPT_EN = """你是一位资深全球宏观分析师，同时精通中英双语金融翻译。
输入：一批原始的英文财经新闻片段。
任务：

1. 分析每条新闻对「中国/美国/香港市场」的金融影响。
2. 如果新闻是无关的噪音（广告、轻微的人事变动、软文），返回该条的 score 为 0。
3. **每条新闻都必须翻译标题和摘要为简体中文**，包括低分新闻。

翻译要求（极其重要）：
- chinese_title 和 chinese_summary 必须是 **纯简体中文**，绝对不可包含任何英文单词或字母。
- 公司名称必须翻译为中文通用译名（NVIDIA → 英伟达，Apple → 苹果，Tesla → 特斯拉，Microsoft → 微软，Google → 谷歌，Amazon → 亚马逊，Meta → Meta/脸书，Goldman Sachs → 高盛，JPMorgan → 摩根大通，Morgan Stanley → 摩根士丹利）。
- 股票代码仅放在 relevant_tickers 字段中，不要出现在 chinese_title 里。
- 使用专业中文金融术语：
  Earnings → 财报 | Beat → 超预期 | Miss → 不及预期 | Guidance → 业绩指引 |
  Rally → 大涨 | Selloff → 抛售 | Yield → 收益率 | Hawkish → 鹰派 |
  Dovish → 鸽派 | Revenue → 营收 | EPS → 每股收益 | IPO → 首次公开募股 |
  Buyback → 回购 | Dividend → 股息 | Short Squeeze → 轧空 |
  Fed → 美联储 | ECB → 欧央行 | BOJ → 日本央行 | CPI → 消费者物价指数 |
  PPI → 生产者物价指数 | GDP → 国内生产总值 | PCE → 个人消费支出 |
  Non-Farm Payrolls → 非农就业 | Layoffs → 裁员 | M&A → 并购 |
  Market Cap → 市值 | P/E → 市盈率 | Downgrade → 下调评级 | Upgrade → 上调评级

⚠️ 输出格式要求（极其重要）：
- 仅返回原始 JSON 数组，不要输出任何其他内容。
- 禁止使用 <think> 标签或任何 XML 标签。
- 禁止使用 Markdown 代码块（```）包裹。
- 禁止在 JSON 前后添加解释文字、开场白或总结。

JSON 格式：
[{"id": 1, "score": 9, "chinese_title": "英伟达第三季度财报超预期，盘后大涨", "chinese_summary": "英伟达公布第三季度营收350亿美元，同比增长94%，超出市场预期", "tags": ["人工智能", "半导体"], "relevant_tickers": ["NVDA"]}, ...]

规则：
- id 对应新闻编号（从1开始）
- score 范围 0-10，10 为最高价值
- chinese_title：【必填】不超过 30 字的纯中文翻译标题。⚠️ 严禁留空、严禁使用英文、严禁直接复制原标题
- chinese_summary：【必填】不超过 80 字的纯中文摘要。⚠️ 严禁留空、严禁使用英文
- tags 提取 1-3 个行业/板块标签（必须用中文）
- relevant_tickers 提取相关股票代码（可为空数组）
- 每条新闻都必须评分并翻译，即使是低分
- 所有字段都必须返回，不可省略任何字段"""


def _detect_is_english(text: str) -> bool:
    """Detect if text is primarily English using langdetect."""
    try:
        lang = detect(text)
        return lang == "en"
    except LangDetectException:
        return False


def _contains_chinese(text: str) -> bool:
    """Check if text contains at least some Chinese characters (CJK Unified Ideographs)."""
    return bool(re.search(r"[\u4e00-\u9fff]", text))


@dataclass
class ScoredNewsItem:
    """News item after DeepSeek scoring."""
    raw: RawNewsItem
    score: int
    reason: str
    summary: str
    tags: list[str]
    chinese_title: str = ""
    relevant_tickers: list[str] = field(default_factory=list)


def _build_user_prompt(batch: list[RawNewsItem], is_english: bool) -> str:
    """Build the user prompt from a batch of news items."""
    lines: list[str] = []
    for i, item in enumerate(batch, 1):
        content_preview = item.content[:200] if item.content else ("No content" if is_english else "无正文")
        if is_english:
            lines.append(
                f"[{i}] Title: {item.title}\n"
                f"    Content: {content_preview}\n"
                f"    Source: {item.source}"
            )
        else:
            lines.append(
                f"[{i}] 标题: {item.title}\n"
                f"    摘要: {content_preview}\n"
                f"    来源: {item.source}"
            )
    return "\n\n".join(lines)


def _extract_json_array(raw_text: str) -> list[dict] | None:
    """Extract a JSON array from DeepSeek LLM response.

    Delegates to the shared json_extractor utility which handles
    <think> tags, markdown fences, and filler text.
    """
    result = extract_json_from_deepseek(raw_text)

    if result is None:
        return None

    if isinstance(result, list):
        return result

    # Handle dict wrapper: {"results": [...]} etc.
    if isinstance(result, dict):
        for key in ("results", "data", "items", "news"):
            if key in result and isinstance(result[key], list):
                return result[key]
        if all(isinstance(v, dict) for v in result.values()):
            return list(result.values())

    logger.error("Extracted JSON is not an array: %s", type(result).__name__)
    return None


def _parse_response(raw_text: str, batch: list[RawNewsItem], is_english: bool) -> list[ScoredNewsItem]:
    """Parse DeepSeek response into scored items with robust error handling."""
    results = _extract_json_array(raw_text)
    if results is None:
        return []

    scored: list[ScoredNewsItem] = []
    for item in results:
        try:
            idx = int(item.get("id", 0)) - 1  # 1-indexed to 0-indexed
            if idx < 0 or idx >= len(batch):
                continue

            score = int(item.get("score", 0))
            if score < settings.DEEPSEEK_SCORE_THRESHOLD:
                continue

            if is_english:
                chinese_title = str(item.get("chinese_title", ""))[:60]
                chinese_summary = str(item.get("chinese_summary", ""))[:200]
                tickers = [str(t) for t in item.get("relevant_tickers", []) if t][:5]

                # Validate chinese_title is actually Chinese (contains CJK chars)
                if chinese_title and not _contains_chinese(chinese_title):
                    logger.warning("chinese_title is not Chinese, discarding: %s", chinese_title[:50])
                    chinese_title = ""

                if chinese_summary and not _contains_chinese(chinese_summary):
                    logger.warning("chinese_summary is not Chinese, discarding: %s", chinese_summary[:50])
                    chinese_summary = ""

                scored.append(ScoredNewsItem(
                    raw=batch[idx],
                    score=min(score, 10),
                    reason="",
                    summary=chinese_summary or str(item.get("summary", ""))[:100],
                    tags=[str(t) for t in item.get("tags", []) if t][:5],
                    chinese_title=chinese_title,
                    relevant_tickers=tickers,
                ))
            else:
                scored.append(ScoredNewsItem(
                    raw=batch[idx],
                    score=min(score, 10),
                    reason=str(item.get("reason", "")),
                    summary=str(item.get("summary", ""))[:100],
                    tags=[str(t) for t in item.get("tags", []) if t][:5],
                ))
        except (ValueError, TypeError) as e:
            logger.warning("Skipping malformed item in DeepSeek response: %s (%s)", item, e)
            continue

    return scored


async def filter_batch(
    batch: list[RawNewsItem],
    is_english: bool = False,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ScoredNewsItem]:
    """Send a single batch (<=20 items) to DeepSeek for scoring with retry.

    Args:
        client: Optional shared httpx.AsyncClient. If provided, the caller
                is responsible for its lifecycle. If None, a temporary client
                is created (backward-compatible but less efficient).

    Error strategy:
      - 400 + "Content Exists Risk" → skip entire batch (no retry).
      - 429 / 5xx / timeout → exponential backoff retry.
    """
    if not batch:
        return []

    if not settings.DEEPSEEK_API_KEY or settings.DEEPSEEK_API_KEY.startswith("sk-your"):
        logger.warning("DeepSeek API key not configured, skipping AI scoring")
        return []

    system_prompt = SYSTEM_PROMPT_EN if is_english else SYSTEM_PROMPT_CN
    user_prompt = _build_user_prompt(batch, is_english)

    payload = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    headers = {
        "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    # Use shared client if provided; otherwise create a temporary one
    _owns_client = client is None
    if _owns_client:
        client = httpx.AsyncClient(timeout=90.0)

    try:
        for attempt in range(1, settings.DEEPSEEK_MAX_RETRIES + 1):
            try:
                resp = await client.post(settings.DEEPSEEK_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text[:500]

                # ── Content safety filter → skip immediately, no retry ──
                if status == 400 and any(kw in body for kw in _CONTENT_RISK_KEYWORDS):
                    titles = [it.title[:40] for it in batch[:3]]
                    logger.warning(
                        "⚠️ DeepSeek content safety triggered — skipping batch "
                        "(%d items, first titles: %s)",
                        len(batch), titles,
                    )
                    return []

                logger.error(
                    "DeepSeek API HTTP %s (attempt %d/%d): %s",
                    status, attempt, MAX_RETRIES, body,
                )

                # Retryable server / rate-limit errors
                if attempt < MAX_RETRIES and status in (429, 500, 502, 503):
                    await asyncio.sleep(3 * attempt)
                    continue
                return []
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.error(
                    "DeepSeek network error (attempt %d/%d): %s", attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(3 * attempt)
                    continue
                return []
            except Exception as e:
                logger.error("DeepSeek request failed (attempt %d/%d): %s", attempt, MAX_RETRIES, e)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(3 * attempt)
                    continue
                return []

            try:
                raw_text = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                logger.error("Unexpected DeepSeek response structure: %s", e)
                return []

            scored = _parse_response(raw_text, batch, is_english)

            # If we got zero results but had items, might be a bad response — retry
            if not scored and len(batch) > 3 and attempt < MAX_RETRIES:
                logger.warning(
                    "DeepSeek returned 0 scored items for %d inputs (attempt %d/%d), "
                    "retrying...\n── Raw response (%d chars) ──\n%s",
                    len(batch), attempt, MAX_RETRIES, len(raw_text), raw_text[:1500],
                )
                await asyncio.sleep(2 * attempt)
                continue

            logger.info("DeepSeek scored batch: %d/%d passed threshold (>=%d)",
                         len(scored), len(batch), SCORE_THRESHOLD)
            return scored
    finally:
        if _owns_client:
            await client.aclose()

    return []


async def filter_news(items: list[RawNewsItem]) -> list[ScoredNewsItem]:
    """Process all items in batches, return high-scoring items.

    Splits items into Chinese and English batches based on title language,
    applying the appropriate system prompt for each.

    Uses a single shared httpx.AsyncClient for all batches to reuse TCP
    connections and avoid repeated TLS handshakes.

    A failure in any single batch is logged and skipped — the pipeline
    continues processing remaining batches.
    """
    batch_size = settings.DEEPSEEK_BATCH_SIZE
    cn_items: list[RawNewsItem] = []
    en_items: list[RawNewsItem] = []

    for item in items:
        if _detect_is_english(item.title):
            en_items.append(item)
        else:
            cn_items.append(item)

    logger.info("Language split: %d Chinese, %d English items", len(cn_items), len(en_items))

    all_scored: list[ScoredNewsItem] = []
    skipped_batches = 0

    async with httpx.AsyncClient(timeout=90.0) as client:
        # Process Chinese batches
        for i in range(0, len(cn_items), BATCH_SIZE):
            batch = cn_items[i : i + BATCH_SIZE]
            try:
                scored = await filter_batch(batch, is_english=False, client=client)
                all_scored.extend(scored)
            except Exception as e:
                skipped_batches += 1
                logger.error("CN batch %d-%d failed, skipping: %s", i, i + len(batch), e)

        # Process English batches
        for i in range(0, len(en_items), batch_size):
            batch = en_items[i : i + batch_size]
            try:
                scored = await filter_batch(batch, is_english=True, client=client)
                all_scored.extend(scored)
            except Exception as e:
                skipped_batches += 1
                logger.error("EN batch %d-%d failed, skipping: %s", i, i + len(batch), e)

    if skipped_batches:
        logger.warning("⚠️ %d batch(es) skipped due to errors", skipped_batches)
    logger.info("Total items passing DeepSeek filter: %d / %d", len(all_scored), len(items))
    return all_scored
