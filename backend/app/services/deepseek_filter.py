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
SYSTEM_PROMPT_CN = """# Role

你是一位融合了 Mark Minervini（趋势交易）、Warren Buffett（护城河）与 Peter Lynch（基本面）逻辑的资深策略分析师。你的任务是将碎片化的新闻提炼为具有实战价值的投资情报。

# Judgment Criteria (MECE Logic)

请按照以下3个互斥且穷尽的维度对新闻进行评估评分（0-10分）：

1. 企业内生变量 (Internal Dynamics):
定义： 仅限公司主体发出的财务、业务或治理信息。
高分项： 营收/净利超预期（Earnings Surprise）、业绩指引（Guidance）上调、毛利结构性改善、核心产品技术突破。
逻辑： 对应 Lynch 的增长逻辑与 Minervini 的 VCP 爆发前兆。

2. 外部环境驱动 (External Drivers):
定义： 影响行业或市场的宏观、政策及产业链变动。
高分项： 央行利率/流动性实质变动、行业准入或补贴政策调整、地缘政治对供应链的实质冲击。
逻辑： 对应 Weinstein 的第二阶段趋势催化与宏观贝塔。

3. 非实质性杂音 (Non-Substantive Noise):
定义： 缺乏数据支撑或不具备行动指引意义的信息。
特征： 愿景口号、分析师个人观点、已定价的历史旧闻、不带数据的宏观评论、娱乐八卦。

# Output Constraints (Strict)

仅返回原始 JSON 数组。
严禁输出： Markdown 代码块符号（```）、<think> 标签、XML 标签、解释文字、开场白或总结。
摘要 (summary)： 必须包含核心定量数据（如"净利增 30%"），严禁纯定性描述，限 50 字以内。
原因 (reason)： 需明确指出触发了哪一维度的逻辑（如"内生变量：指引超预期"）。

规则：
- id 对应新闻编号（从1开始）
- score 范围 0-10，10 为最高价值
- summary 不超过 50 字
- tags 提取 1-3 个行业/板块标签
- 每条新闻都必须评分，即使是低分

# JSON Format Example

[{"id": 1, "score": 9, "reason": "内生变量：Q4净利增速超预期，毛利显著改善", "summary": "XX公司Q4净利增120%，毛利提升5%，创历史新高。", "tags": ["财报", "高增长"]}]"""

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
    use_mock: bool = False,
) -> list[ScoredNewsItem]:
    """Send a single batch (<=20 items) to DeepSeek for scoring with retry.

    Args:
        client: Optional shared httpx.AsyncClient. If provided, the caller
                is responsible for its lifecycle. If None, a temporary client
                is created (backward-compatible but less efficient).
        use_mock: If True, skip the real API call and return a response from
                  the local mock data pool instead. Useful for local debugging
                  and testing without consuming API credits.

    Error strategy:
      - 400 + "Content Exists Risk" → skip entire batch (no retry).
      - 429 / 5xx / timeout → exponential backoff retry.
    """
    if not batch:
        return []

    # ── Mock mode: use local data pool instead of real API ──
    if use_mock:
        return _filter_batch_mock(batch, is_english)

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

                max_retries = settings.DEEPSEEK_MAX_RETRIES
                logger.error(
                    "DeepSeek API HTTP %s (attempt %d/%d): %s",
                    status, attempt, max_retries, body,
                )

                # Retryable server / rate-limit errors
                if attempt < max_retries and status in (429, 500, 502, 503):
                    await asyncio.sleep(3 * attempt)
                    continue
                return []
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                max_retries = settings.DEEPSEEK_MAX_RETRIES
                logger.error(
                    "DeepSeek network error (attempt %d/%d): %s", attempt, max_retries, e,
                )
                if attempt < max_retries:
                    await asyncio.sleep(3 * attempt)
                    continue
                return []
            except Exception as e:
                max_retries = settings.DEEPSEEK_MAX_RETRIES
                logger.error("DeepSeek request failed (attempt %d/%d): %s", attempt, max_retries, e)
                if attempt < max_retries:
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
            max_retries = settings.DEEPSEEK_MAX_RETRIES
            if not scored and len(batch) > 3 and attempt < max_retries:
                logger.warning(
                    "DeepSeek returned 0 scored items for %d inputs (attempt %d/%d), "
                    "retrying...\n── Raw response (%d chars) ──\n%s",
                    len(batch), attempt, max_retries, len(raw_text), raw_text[:1500],
                )
                await asyncio.sleep(2 * attempt)
                continue

            logger.info("DeepSeek scored batch: %d/%d passed threshold (>=%d)",
                         len(scored), len(batch), settings.DEEPSEEK_SCORE_THRESHOLD)
            return scored
    finally:
        if _owns_client:
            await client.aclose()

    return []


def _filter_batch_mock(batch: list[RawNewsItem], is_english: bool) -> list[ScoredNewsItem]:
    """Return scored items from a randomly chosen mock response (no API call).

    Lazy-imports mock_responses to avoid loading test data in production.
    """
    import random
    try:
        from tests.mock_responses import CN_MOCK_POOL, EN_MOCK_POOL
    except ImportError:
        logger.error("Cannot import tests.mock_responses — is the tests package accessible?")
        return []

    pool = EN_MOCK_POOL if is_english else CN_MOCK_POOL
    desc, raw_text, _ = random.choice(pool)
    logger.info("🧪 [MOCK] Using mock response: %s", desc)

    return _parse_response(raw_text, batch, is_english)


@dataclass
class FilterResult:
    """Result of the filter_news stage, including error info for the pipeline."""
    scored: list[ScoredNewsItem]
    skipped_batches: int = 0
    total_batches: int = 0

    @property
    def had_errors(self) -> bool:
        return self.skipped_batches > 0

    @property
    def all_failed(self) -> bool:
        return self.total_batches > 0 and self.skipped_batches >= self.total_batches


async def filter_news(items: list[RawNewsItem]) -> FilterResult:
    """Process all items in batches, return high-scoring items with error info.

    Splits items into Chinese and English batches based on title language,
    applying the appropriate system prompt for each.

    Uses a single shared httpx.AsyncClient for all batches to reuse TCP
    connections and avoid repeated TLS handshakes.

    A failure in any single batch is logged and skipped — the pipeline
    continues processing remaining batches. The returned FilterResult
    carries skipped_batches count so the pipeline can decide whether
    to mark unscored URLs as "seen".
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
    total_batches = 0

    async with httpx.AsyncClient(timeout=90.0) as client:
        # Process Chinese batches
        for i in range(0, len(cn_items), batch_size):
            total_batches += 1
            batch = cn_items[i : i + batch_size]
            try:
                scored = await filter_batch(batch, is_english=False, client=client)
                all_scored.extend(scored)
            except Exception as e:
                skipped_batches += 1
                logger.error("CN batch %d-%d failed, skipping: %s", i, i + len(batch), e)

        # Process English batches
        for i in range(0, len(en_items), batch_size):
            total_batches += 1
            batch = en_items[i : i + batch_size]
            try:
                scored = await filter_batch(batch, is_english=True, client=client)
                all_scored.extend(scored)
            except Exception as e:
                skipped_batches += 1
                logger.error("EN batch %d-%d failed, skipping: %s", i, i + len(batch), e)

    if skipped_batches:
        logger.warning("⚠️ %d/%d batch(es) skipped due to errors", skipped_batches, total_batches)
    logger.info("Total items passing DeepSeek filter: %d / %d", len(all_scored), len(items))
    return FilterResult(scored=all_scored, skipped_batches=skipped_batches, total_batches=total_batches)
