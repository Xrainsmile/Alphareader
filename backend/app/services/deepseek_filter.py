"""AI 评分与翻译服务 (deepseek_filter.py)
====================================================
职责：调用 LLM API 对新闻进行批量评分和翻译。

模型选择（通过 config 切换）：
  - 评分/翻译：SiliconFlow Qwen3-8B（免费）
  - 摘要（digest_service）：DeepSeek-V3（付费，但调用量极小）

核心逻辑：
  1. 将新闻按语言分为中文组和英文组（使用 langdetect 自动检测）
  2. 每组按 batch_size=20 分批，发送给 SiliconFlow API
  3. 中文新闻：投资参考价值 + 催化剂/预期差评分框架
  4. 英文新闻：同评分框架 + 翻译标题和摘要为简体中文
  5. 丢弃 score < 5 的新闻，返回高分条目列表

评分核心（参考价值与催化剂）：
  - 0-2: 纯噪音（无信息量/重复旧闻/空洞评论）
  - 3-4: 低价值信息（画大饼/已消化旧闻/常规人事变动）
  - 5-6: 有参考价值（宏观数据/行业政策/常规财报/市场行情/机构观点）
  - 7-8: 强力催化剂/显著预期差（业绩惊喜/指引上调/供需逆转）
  - 9-10: 历史性拐点/颠覆性变量（爆炸性财报/技术颠覆/央行级政策转向）

错误处理：
  - 内容审查触发（Content Exists Risk）→ 跳过整个 batch，不重试
  - 429/5xx/超时 → 指数退避重试
  - 单 batch 失败不影响其他 batch
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

# DeepSeek 内容安全审查的关键词——匹配到这些关键词时跳过整个 batch，不重试
_CONTENT_RISK_KEYWORDS = ("Content Exists Risk", "content_filter", "content_policy")

# ── 中文新闻评分的 System Prompt ──
# Minervini SEPA / O'Neil CAN SLIM 预期差评分框架
SYSTEM_PROMPT_CN = """你是一位资深金融市场分析师，熟悉 Minervini SEPA 策略与 O'Neil CAN SLIM 体系。你的目标是：从碎片化的市场资讯中，筛选出对投资者有参考价值的信息，并识别其中的核心催化剂与预期差。

# 评分逻辑

请按以下【评分标尺】对新闻进行 0-10 分的评估。评分核心是：该信息对投资者的参考价值和对市场/股价的潜在影响力。

## 0-2分：纯噪音 (Pure Noise)
- 特征：完全无信息量的内容、重复旧闻、无任何数据支撑的空洞评论、与金融市场完全无关的内容。

## 3-4分：低价值信息 (Low Value)
- 特征：管理层画大饼/口号式愿景、分析师常规无新意的研报、已被市场充分消化的旧闻、常规人事变动、无实质约束力的合作意向。
- 逻辑：有一定信息量但对投资决策帮助极小。

## 5-6分：有参考价值的市场信息 (Informative)
- 特征：有具体数据的宏观经济指标发布（GDP/CPI/PMI/就业数据等）、行业政策落地、常规但有数据的财报（符合预期）、重要市场行情变动（大宗商品/汇率/指数涨跌）、央行官员表态、公司正式公告（回购/分红/并购意向）、知名机构的观点或评级变动。
- 逻辑：对投资者了解市场动态有实际帮助，值得阅读。

## 7-8分：强力催化剂/显著预期差 (Strong Catalysts)
- 特征：
  1. 【内生】：业绩大幅超预期（Earnings Surprise）、指引上调、毛利率拐点、高管大额增持。
  2. 【外生】：超预期的行业政策、核心产业链供需逆转（涨价潮/缺货潮）、重大并购交易落地。
- 逻辑：可能直接驱动股价趋势性变化。

## 9-10分：历史性拐点/颠覆性变量 (Transformative)
- 特征：远超预期的爆炸性财报、颠覆性技术突破、央行级别重大政策转向。
- 逻辑：极其罕见，可能改变整个板块或市场走向。

# 评分倾向指引（重要！请仔细遵守）
- 大多数有实质内容的财经新闻应落在 **6-7 分**区间，这是正常分布的中枢
- 只要新闻包含具体数据、具名公司、明确事件，**至少给 6 分**
- 5 分应该较少出现，仅用于信息量确实有限但不算纯噪音的内容
- 3-4 分仅用于明确的低价值内容（口号式愿景、无数据旧闻）
- 只有完全无价值的噪音才给 0-2 分
- **请注意：你有偏低打分的倾向，请有意识地校正，宁可略高不要略低**

# Output Constraints (Strict)

你必须且只能返回原始 JSON 数组。
严禁输出：Markdown 代码块符号（```）、<think> 标签、XML 标签、任何解释文字、开场白或总结。

JSON 字段及规则：
- id: 对应新闻编号（从1开始）
- score: 整数，范围 0-10（严格参考上述评分标尺）
- reason: 限 30 字以内，简述评分理由（例："Q4指引大幅上调，强力催化"或"常规合作意向，无数据支撑"）。
- tags: 提取 3-5 个核心标签，包含：① 所属板块（如"半导体"） ② 明确个股（如"宁德时代"，若无则省略） ③ 事件定性（如"业绩指引上调"、"宏观数据"、"行业政策"、"市场行情"）。
- relevant_tickers: 提取新闻中明确涉及的 A 股代码（6位纯数字，如 ["300750", "600519"]），仅限新闻正文中有明确提及的个股，没有则返回空数组 []。

# JSON Format Example
[
  {"id": 1, "score": 7, "reason": "CPI数据发布，具体数据对通胀判断有参考价值", "tags": ["宏观经济", "通胀", "宏观数据"], "relevant_tickers": []},
  {"id": 2, "score": 8, "reason": "Q4指引大幅上调，构成实质性盈余惊喜", "tags": ["AI算力", "宁德时代", "业绩指引上调", "核心催化"], "relevant_tickers": ["300750"]}
]"""

# ── 英文新闻评分+翻译的 System Prompt ──
# 同中文评分框架 + 额外翻译要求（标题/摘要翻译为纯简体中文）
SYSTEM_PROMPT_EN = """你是一位资深金融市场分析师，熟悉 Minervini SEPA 策略与 O'Neil CAN SLIM 体系，同时精通中英双语金融翻译。
输入：一批原始的英文财经新闻片段。
任务：

1. 筛选出对投资者有参考价值的信息，并识别其中的核心催化剂与预期差。
2. **每条新闻都必须翻译标题和摘要为简体中文**，包括低分新闻。

# 评分逻辑

请按以下【评分标尺】对新闻进行 0-10 分的评估。评分核心是：该信息对投资者的参考价值和对市场/股价的潜在影响力。

## 0-2分：纯噪音 (Pure Noise)
- 特征：完全无信息量的内容、重复旧闻、无任何数据支撑的空洞评论、与金融市场完全无关的内容。

## 3-4分：低价值信息 (Low Value)
- 特征：管理层画大饼/口号式愿景、分析师常规无新意的研报、已被市场充分消化的旧闻、常规人事变动、无实质约束力的合作意向。
- 逻辑：有一定信息量但对投资决策帮助极小。

## 5-6分：有参考价值的市场信息 (Informative)
- 特征：有具体数据的宏观经济指标发布（GDP/CPI/PMI/就业数据等）、行业政策落地、常规但有数据的财报（符合预期）、重要市场行情变动（大宗商品/汇率/指数涨跌）、央行官员表态、公司正式公告（回购/分红/并购意向）、知名机构的观点或评级变动。
- 逻辑：对投资者了解市场动态有实际帮助，值得阅读。

## 7-8分：强力催化剂/显著预期差 (Strong Catalysts)
- 特征：
  1. 【内生】：业绩大幅超预期（Earnings Surprise）、指引上调、毛利率拐点、高管大额增持。
  2. 【外生】：超预期的行业政策、核心产业链供需逆转（涨价潮/缺货潮）、重大并购交易落地。
- 逻辑：可能直接驱动股价趋势性变化。

## 9-10分：历史性拐点/颠覆性变量 (Transformative)
- 特征：远超预期的爆炸性财报、颠覆性技术突破、央行级别重大政策转向。
- 逻辑：极其罕见，可能改变整个板块或市场走向。

# 评分倾向指引（重要！请仔细遵守）
- 大多数有实质内容的财经新闻应落在 **6-7 分**区间，这是正常分布的中枢
- 只要新闻包含具体数据、具名公司、明确事件，**至少给 6 分**
- 5 分应该较少出现，仅用于信息量确实有限但不算纯噪音的内容
- 3-4 分仅用于明确的低价值内容（口号式愿景、无数据旧闻）
- 只有完全无价值的噪音才给 0-2 分
- **请注意：你有偏低打分的倾向，请有意识地校正，宁可略高不要略低**

# 翻译要求（极其重要）

- chinese_title 和 chinese_summary 必须是 **纯简体中文**，绝对不可包含任何英文单词或字母。
- **当标题过短或为纯产品名（如 "OpenAI o1-mini"、"Hello GPT-4o"、"Dota 2"）时，必须结合 Content 内容生成一个描述性的中文标题**。例如：
  - "OpenAI o1-mini" + Content 提到推进低成本推理 → chinese_title: "OpenAI发布推理模型o1迷你版，推进低成本AI推理"
  - "Hello GPT-4o" + Content 提到多模态旗舰模型 → chinese_title: "OpenAI发布多模态旗舰模型GPT-4o"
  - "OpenAI API" + Content 提到开放API访问 → chinese_title: "OpenAI开放API接口供开发者使用"
  - 绝对不可直接复制英文标题作为 chinese_title！
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

# Output Constraints (Strict)

你必须且只能返回原始 JSON 数组。
严禁输出：Markdown 代码块符号（```）、<think> 标签、XML 标签、任何解释文字、开场白或总结。

JSON 字段及规则：
- id: 对应新闻编号（从1开始）
- score: 整数，范围 0-10（严格参考上述评分标尺）
- chinese_title：【必填】不超过 30 字的纯中文翻译标题。⚠️ 严禁留空、严禁使用英文、严禁直接复制原标题
- chinese_summary：【必填】不超过 80 字的纯中文摘要。⚠️ 严禁留空、严禁使用英文
- tags: 提取 3-5 个核心标签（必须用中文），包含：① 所属板块（如"半导体"） ② 明确个股（如"英伟达"，若无则省略） ③ 事件定性（如"业绩指引上调"、"宏观流动性"、"供需逆转"、"无效噪音"）
- relevant_tickers: 提取相关股票代码（可为空数组）
- 每条新闻都必须评分并翻译，即使是低分
- 所有字段都必须返回，不可省略任何字段

# JSON Format Example
[{"id": 1, "score": 8, "chinese_title": "英伟达第三季度业绩指引大幅上调", "chinese_summary": "英伟达公布第三季度营收350亿美元，同比增长94%，指引远超市场预期，构成实质性盈余惊喜", "tags": ["AI算力", "英伟达", "业绩指引上调", "核心催化"], "relevant_tickers": ["NVDA"]}]"""


def _detect_is_english(text: str) -> bool:
    """使用 langdetect 检测文本是否为英语"""
    try:
        lang = detect(text)
        return lang == "en"
    except LangDetectException:
        return False


def _contains_chinese(text: str) -> bool:
    """检查文本是否包含中文字符（CJK 统一表意字符范围），用于验证翻译结果"""
    return bool(re.search(r"[\u4e00-\u9fff]", text))


@dataclass
class ScoredNewsItem:
    """经 DeepSeek 评分后的新闻条目。
    - raw: 原始新闻数据
    - score: AI 评分（0-10）
    - chinese_title: 英文新闻翻译后的中文标题（中文新闻为空）
    - relevant_tickers: 相关股票代码列表（如 ['NVDA', 'AAPL']）
    """
    raw: RawNewsItem
    score: int
    reason: str
    summary: str
    tags: list[str]
    chinese_title: str = ""
    relevant_tickers: list[str] = field(default_factory=list)
    sentiment_score: int | None = None
    surprise_factor: int | None = None
    catalyst_type: str | None = None
    sentiment_entity: str | None = None
    sentiment_reasoning: str | None = None


def _build_user_prompt(batch: list[RawNewsItem], is_english: bool) -> str:
    """将一批新闻条目格式化为发送给 DeepSeek 的用户提示词。
    格式：[编号] 标题 + 摘要前200字 + 来源，中英文使用不同模板。
    """
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
    """从 DeepSeek 响应中提取 JSON 数组。

    LLM 输出格式不稳定，使用多层策略：
    1. 去除 <think> 标签 → 2. 提取 Markdown 代码块 → 3. 正则匹配 [...] → 4. 回退解析
    支持 dict 包装器（如 {"results": [...]}）自动解包。
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
    """解析 DeepSeek API 响应为评分结果列表。

    处理逻辑：
    - 从 JSON 数组中逐条解析，id 为 1-indexed 转 0-indexed
    - score < 阈值（默认 5）的条目被丢弃
    - 英文新闻额外提取 chinese_title/chinese_summary/relevant_tickers
    - 翻译结果通过 _contains_chinese() 验证，非中文的丢弃
    """
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

                # 兜底：如果 chinese_title 为空但 chinese_summary 有中文，
                # 从摘要截取前30字作为标题，避免回退到英文原标题
                if not chinese_title and chinese_summary and _contains_chinese(chinese_summary):
                    chinese_title = chinese_summary[:30].rstrip("，。、；：")
                    logger.info(
                        "chinese_title empty, fallback from summary: '%s' (original: '%s')",
                        chinese_title, batch[idx].title[:50],
                    )

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
                tickers = [str(t) for t in item.get("relevant_tickers", []) if t][:5]
                scored.append(ScoredNewsItem(
                    raw=batch[idx],
                    score=min(score, 10),
                    reason=str(item.get("reason", "")),
                    summary=str(item.get("summary", ""))[:100],
                    tags=[str(t) for t in item.get("tags", []) if t][:5],
                    relevant_tickers=tickers,
                ))
        except (ValueError, TypeError) as e:
            logger.warning("Skipping malformed item in LLM response: %s (%s)", item, e)
            continue

    return scored


async def filter_batch(
    batch: list[RawNewsItem],
    is_english: bool = False,
    *,
    client: httpx.AsyncClient | None = None,
    use_mock: bool = False,
) -> list[ScoredNewsItem]:
    """发送单批次（≤20条）到 DeepSeek API 进行评分，返回通过阈值的条目。

    参数：
        client: 共享的 httpx 客户端（复用 TCP 连接）。为 None 时自动创建临时客户端。
        use_mock: True 时跳过真实 API 调用，使用本地 mock 数据（测试用）。

    API 调用参数：model=deepseek-chat, temperature=0.1, max_tokens=4096

    错误处理策略：
        - 400 + Content Exists Risk → 跳过整个 batch，不重试（内容审查）
        - 429/500/502/503 → 指数退避重试 sleep(3 × attempt)
        - 超时/连接错误 → 同上重试
        - 0 结果但 batch > 3 → 可能格式异常，重试
    """
    if not batch:
        return []

    # ── Mock mode: use local data pool instead of real API ──
    if use_mock:
        return _filter_batch_mock(batch, is_english)

    if not settings.SILICONFLOW_API_KEY:
        logger.warning("SiliconFlow API key not configured, skipping AI scoring")
        return []

    system_prompt = SYSTEM_PROMPT_EN if is_english else SYSTEM_PROMPT_CN
    user_prompt = _build_user_prompt(batch, is_english)

    payload = {
        "model": settings.SILICONFLOW_LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
        "enable_thinking": False,
    }

    headers = {
        "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }

    # Use shared client if provided; otherwise create a temporary one
    _owns_client = client is None
    if _owns_client:
        client = httpx.AsyncClient(timeout=90.0)

    try:
        for attempt in range(1, settings.DEEPSEEK_MAX_RETRIES + 1):
            try:
                resp = await client.post(settings.SILICONFLOW_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text[:500]

                # ── Content safety filter → skip immediately, no retry ──
                if status == 400 and any(kw in body for kw in _CONTENT_RISK_KEYWORDS):
                    titles = [it.title[:40] for it in batch[:3]]
                    logger.warning(
                        "⚠️ SiliconFlow content safety triggered — skipping batch "
                        "(%d items, first titles: %s)",
                        len(batch), titles,
                    )
                    return []

                max_retries = settings.DEEPSEEK_MAX_RETRIES
                logger.error(
                    "SiliconFlow API HTTP %s (attempt %d/%d): %s",
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
                    "SiliconFlow network error (attempt %d/%d): %s", attempt, max_retries, e,
                )
                if attempt < max_retries:
                    await asyncio.sleep(3 * attempt)
                    continue
                return []
            except Exception as e:
                max_retries = settings.DEEPSEEK_MAX_RETRIES
                logger.error("SiliconFlow request failed (attempt %d/%d): %s", attempt, max_retries, e)
                if attempt < max_retries:
                    await asyncio.sleep(3 * attempt)
                    continue
                return []

            try:
                raw_text = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                logger.error("Unexpected SiliconFlow response structure: %s", e)
                return []

            scored = _parse_response(raw_text, batch, is_english)

            # If we got zero results but had items, might be a bad response — retry
            max_retries = settings.DEEPSEEK_MAX_RETRIES
            if not scored and len(batch) > 3 and attempt < max_retries:
                logger.warning(
                    "SiliconFlow returned 0 scored items for %d inputs (attempt %d/%d), "
                    "retrying...\n── Raw response (%d chars) ──\n%s",
                    len(batch), attempt, max_retries, len(raw_text), raw_text[:1500],
                )
                await asyncio.sleep(2 * attempt)
                continue

            logger.info("SiliconFlow scored batch: %d/%d passed threshold (>=%d)",
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
    """评分阶段的总结果，包含错误统计信息。
    - scored: 通过评分阈值的新闻列表
    - skipped_batches: 因错误跳过的 batch 数量
    - total_batches: 总 batch 数量
    - had_errors: 是否有任何 batch 出错（用于 pipeline 决定是否标记低分 URL）
    """
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
    """AI 评分的主入口：将所有新闻分批发送 DeepSeek 评分。

    处理流程：
    1. langdetect 自动将新闻分为中文/英文两组
    2. 各自按 batch_size=20 分批
    3. 共享同一个 httpx.AsyncClient（复用 TCP/TLS 连接）
    4. 中文 batch 使用 SYSTEM_PROMPT_CN，英文使用 SYSTEM_PROMPT_EN
    5. 单 batch 失败只记日志，不影响其他 batch
    6. 返回 FilterResult（含 scored 列表和错误统计）
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
    logger.info("Total items passing SiliconFlow filter: %d / %d", len(all_scored), len(items))
    return FilterResult(scored=all_scored, skipped_batches=skipped_batches, total_batches=total_batches)
