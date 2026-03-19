"""情绪分析流水线 (sentiment_pipeline.py)
=========================================
职责：编排"去重 → 情绪分析 → 落库"三阶段漏斗，是本模块的主控函数。

核心设计——三路分支路由：
  DROP    → 绝对重复，直接丢弃，不碰数据库，不碰 LLM。
  RELATED → 同一事件的附属报道，【跳过 LLM 调用】，直接落库并关联父 ID。
            （节省理由：附属报道的情绪方向与父条目几乎完全一致，
              额外调用一次 LLM 仅为了 +0 信息量，纯浪费 Token 与等待时间）
  NEW     → 全新独立事件，触发 LLM 情绪分析，提取完整字段后落库。

System Prompt 作为模块级全局常量定义（见文件顶部），
方便在不动业务逻辑的情况下迭代 Prompt Engineering。

使用方式：
    result = await process_incoming_news(news_data)
    # result: {"status": "stored" | "dropped", "news_id": uuid | None}
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from app.config import settings
from app.utils.json_extractor import extract_json_from_deepseek

# ══════════════════════════════════════════════════════════════════
# System Prompt —— 情绪分析专用
# ──────────────────────────────────────────────────────────────────
# 【设计说明】
#   - 放在文件顶部作为模块级常量，而非硬编码在函数体内。
#   - 这是你最重要的"Prompt Engineering 资产"，改 Prompt 不需要动业务逻辑。
#   - 若 Prompt 过长，也可移到 app/prompts/sentiment.txt 再 open().read() 加载。
# ══════════════════════════════════════════════════════════════════

SENTIMENT_SYSTEM_PROMPT = """你是一位顶级的金融量化分析师和操盘手，精通成长股投资与趋势交易（如 Mark Minervini 的 VCP 理论）。你的任务是阅读极短的财经快讯，敏锐地捕捉其中的"情绪方向"和"预期差"，并严格以 JSON 格式输出。

【核心评估维度定义】

1. 情绪得分 (sentiment_score): [-5 到 +5 的整数]

+5: 极度利好。如：业绩极其亮眼、获得颠覆性重大突破、主营业务迎来爆发式政策利好。
+3: 中度利好。如：业绩符合较高预期、获得日常大订单、高管增持。
+1: 轻微利好。如：行业常规性正向数据、模糊的政策利好。
0:  中性、客观陈述或无明确方向。
-1 到 -5: 对应级别的利空（如不及预期、合规处罚、黑天鹅事故、地缘冲突导致的特定标的受损）。

2. 预期差指数 (surprise_factor): [0 到 5 的整数]

预期差是引发股价大幅波动的核心。你必须通过文本中的线索来推断其罕见程度：

5 (极其震撼): 完全打破市场固有认知。例如：连年亏损的夕阳企业突然宣布核心技术突破并斩获巨单；业绩指引翻数倍；"历史首次"、"彻底反转"。
4 (显著超预期): 明显超出行业平均水平或前期指引。包含词汇如"大超预期"、"创X年新高"、"大幅上修"。
3 (具备增量信息): 有确实的新催化剂，但属于合理推演范围内。
1-2 (符合预期/炒冷饭): 市场大概率已经知道的信息，例如"按计划发布"、"符合此前预告"、"行业常规数据公布"。
0 (毫无新意): 纯粹的废话或完全可预见的事情。

3. 核心催化类型 (catalyst_type):

仅限从以下列表中选择一个：[业绩财报, 宏观政策, 行业景气度, 产品技术突破, 资金面异动, 合规与风险, 人事变动, 地缘政治, 其他]

【输出格式要求】

你必须只输出合法的 JSON，不要有任何 Markdown 标记或多余的解释。格式如下：

{
  "entity": "提取受该新闻影响最直接的具体公司名称、股票代码或特定细分行业",
  "catalyst_type": "核心催化类型",
  "reasoning": "用一句话简述你打出该情绪分和预期差的逻辑（必须包含对预期差的判断依据）",
  "sentiment_score": 0,
  "surprise_factor": 0
}"""

# ── User Prompt 模板 ──
# 使用方式：SENTIMENT_USER_PROMPT_TEMPLATE.format(news_text="...新闻内容...")
# 动态部分只有 {news_text}，其余结构固定。
SENTIMENT_USER_PROMPT_TEMPLATE = "请分析以下新闻：\n\n新闻内容：{news_text}"

# ══════════════════════════════════════════════════════════════════
# 枚举 & 数据结构
# ══════════════════════════════════════════════════════════════════

class DeduplicationStatus(str, Enum):
    DROP    = "DROP"     # 绝对重复 (Cosine > 0.85)，直接丢弃
    RELATED = "RELATED"  # 同类事件附属报道 (0.70 < Cosine ≤ 0.85)，放行但不调 LLM
    NEW     = "NEW"      # 全新独立事件 (Cosine ≤ 0.70)，完整走 LLM


@dataclass
class DeduplicationResult:
    """check_duplicate() 的返回值结构。"""
    status: DeduplicationStatus
    related_to_id: uuid.UUID | None = None   # 仅 RELATED 状态时有值


@dataclass
class SentimentResult:
    """LLM 情绪分析的输出字段，带默认值——即使 LLM 失败也可安全落库。

    字段与 Prompt 定义严格对齐：
      entity          — 受影响的具体公司/代码/细分行业
      sentiment_score — 整数 -5 ~ +5
      surprise_factor — 整数  0 ~ 5
      catalyst_type   — 催化剂类型（中文枚举）
      reasoning       — 一句话推理
    """
    entity:          str = ""
    sentiment_score: int = 0
    surprise_factor: int = 0
    catalyst_type:   str = "其他"
    reasoning:       str = ""


logger = logging.getLogger("alphareader.sentiment_pipeline")


# ══════════════════════════════════════════════════════════════════
# Mock 占位函数 —— 替换为真实实现时只需改这三个函数体
# ══════════════════════════════════════════════════════════════════

async def check_duplicate(
    news_data: dict[str, Any],
    window_minutes: int = 90,
) -> DeduplicationResult:
    """【占位】调用去重引擎，返回三态结果。

    真实实现：
        - 调用 NewsDeduplicator（见 app/utils/deduplicator.py）
        - 利用现有 Embedding 索引做余弦相似度比对
        - 返回 DROP / RELATED（附 related_to_id）/ NEW
    """
    # TODO: 替换为真实去重逻辑
    raise NotImplementedError("请对接 app/utils/deduplicator.py 中的 NewsDeduplicator")


async def analyze_sentiment_and_surprise_with_llm(
    news_text: str,
) -> dict[str, Any]:
    """调用 DeepSeek API 对单条新闻进行情绪分析，返回解析后的 JSON dict。

    - 使用文件顶部的 SENTIMENT_SYSTEM_PROMPT 和 SENTIMENT_USER_PROMPT_TEMPLATE
    - temperature=0.1，max_tokens=256（情绪分析输出极短，不需要更多）
    - 重试策略：429/5xx 最多重试 DEEPSEEK_MAX_RETRIES 次，指数退避
    - 返回 dict，键：entity, sentiment_score, surprise_factor, catalyst_type, reasoning
    - 调用失败或解析失败均抛出异常，由上层 process_incoming_news 的 try/except 兜底
    """
    if not settings.SILICONFLOW_API_KEY:
        raise RuntimeError("SiliconFlow API key 未配置")

    payload = {
        "model": settings.SILICONFLOW_LLM_MODEL,
        "messages": [
            {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
            {"role": "user",   "content": news_text},  # news_text 已由 _build_news_text_for_llm 套入模板
        ],
        "temperature": 0.1,
        "max_tokens": 256,
        "enable_thinking": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(1, settings.DEEPSEEK_MAX_RETRIES + 1):
            try:
                resp = await client.post(
                    settings.SILICONFLOW_API_URL,
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                # 内容安全审查触发 → 不重试，直接抛出让上层用默认值兜底
                if status_code == 400:
                    raise RuntimeError(f"LLM 内容审查拦截 (400): {e.response.text[:200]}") from e
                # 限速或服务端错误 → 退避重试
                if attempt < settings.DEEPSEEK_MAX_RETRIES and status_code in (429, 500, 502, 503):
                    await asyncio.sleep(2 * attempt)
                    continue
                raise RuntimeError(f"SiliconFlow HTTP {status_code}") from e
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < settings.DEEPSEEK_MAX_RETRIES:
                    await asyncio.sleep(2 * attempt)
                    continue
                raise TimeoutError(f"SiliconFlow 请求超时/连接失败: {e}") from e

            # ── 解析响应 ──
            raw_content: str = resp.json()["choices"][0]["message"]["content"]

            result = extract_json_from_deepseek(raw_content)

            # extract_json_from_deepseek 对单个 {} 对象也能解析，直接判断类型
            if not isinstance(result, dict):
                # LLM 返回了数组或无法解析 → 当作 JSON 异常抛出，让上层兜底
                raise json.JSONDecodeError(
                    f"期望 dict，实际得到 {type(result).__name__}",
                    raw_content, 0,
                )

            return result

    # 理论上不会到达这里（循环内必然 return 或 raise），保险起见
    raise RuntimeError("SiliconFlow API 所有重试均失败")


async def save_to_db(
    news_data: dict[str, Any],
    sentiment: SentimentResult | None,
    related_to_id: uuid.UUID | None,
) -> uuid.UUID:
    """【占位】将完整新闻数据写入 PostgreSQL。

    真实实现：
        - 参考 pipeline.py 中的 _store_scored_items()
        - 使用 pg_insert(News).values(...).on_conflict_do_nothing(index_elements=["url"])
        - 将 sentiment 字段映射到对应数据库列（需先做 Alembic migration 添加列）
        - 返回新插入记录的 UUID
    """
    # TODO: 替换为真实数据库写入逻辑
    raise NotImplementedError("请对接 app/database.py 中的 async_session 执行 INSERT")


# ══════════════════════════════════════════════════════════════════
# 主控函数
# ══════════════════════════════════════════════════════════════════

async def process_incoming_news(news_data: dict[str, Any]) -> dict[str, Any]:
    """新闻入库的主控函数——漏斗式三阶段处理。

    参数：
        news_data: 包含 title / content / source / url / published_at 等字段的字典。

    返回：
        {
          "status": "dropped" | "stored",
          "reason": str,           # 简短说明
          "news_id": UUID | None,  # 成功落库后的数据库 ID
          "llm_called": bool,      # 是否调用了 LLM（用于成本审计日志）
        }

    控制流：
        ┌──────────────────────────────────────────────────────────┐
        │  check_duplicate()                                       │
        │       │                                                  │
        │   ┌───┴────────────────────────────┐                    │
        │  DROP                          RELATED / NEW             │
        │   │                                │                     │
        │  return                      save_to_db()               │
        │  (丢弃)                       RELATED: 跳过 LLM         │
        │                               NEW:     先调 LLM          │
        └──────────────────────────────────────────────────────────┘
    """
    news_title = news_data.get("title", "")[:60]  # 仅用于日志，截断避免泄露过长内容

    # ──────────────────────────────────────────────────────────────
    # Step 1：过去重漏斗
    # ──────────────────────────────────────────────────────────────
    try:
        dedup_result = await check_duplicate(news_data, window_minutes=90)
    except Exception as e:
        logger.error("去重检查失败，跳过本条新闻 | title=%s | error=%s", news_title, e)
        return {"status": "dropped", "reason": f"dedup_error: {e}", "news_id": None, "llm_called": False}

    status = dedup_result.status

    # ──────────────────────────────────────────────────────────────
    # Step 2：三路分支路由
    # ──────────────────────────────────────────────────────────────

    # ── 分支 A：DROP —— 绝对重复，直接丢弃 ──
    if status == DeduplicationStatus.DROP:
        logger.info("DROP（绝对重复，丢弃）| title=%s", news_title)
        return {"status": "dropped", "reason": "duplicate", "news_id": None, "llm_called": False}

    # ── 分支 B：RELATED —— 同类事件附属报道，【绝对不调 LLM】直接落库 ──
    if status == DeduplicationStatus.RELATED:
        # 【设计决策】跳过 LLM 的理由：
        #   1. 成本控制：附属报道与父条目描述同一事件，情绪方向高度一致，
        #      额外调用 LLM 只是在用 API 费用确认一件已知的事。
        #   2. 延迟优化：跳过 LLM 后，附属报道可在毫秒级完成落库，
        #      避免因 LLM 排队延迟影响实时性。
        #   3. 前端展示：RELATED 条目通过 related_to_id 折叠在父卡片下，
        #      用户感知到的是"聚合热度 +1"，而非独立情绪评分。
        logger.info(
            "RELATED（附属报道，跳过 LLM，直接落库）| title=%s | related_to_id=%s",
            news_title, dedup_result.related_to_id,
        )
        try:
            news_id = await save_to_db(
                news_data=news_data,
                sentiment=None,                        # 不填情绪字段
                related_to_id=dedup_result.related_to_id,
            )
            return {"status": "stored", "reason": "related", "news_id": news_id, "llm_called": False}
        except Exception as e:
            logger.error("RELATED 落库失败 | title=%s | error=%s", news_title, e)
            return {"status": "dropped", "reason": f"db_error: {e}", "news_id": None, "llm_called": False}

    # ── 分支 C：NEW —— 全新独立事件，完整走 LLM 分析 ──
    # （到这里 status 一定是 NEW，无需再判断）
    logger.info("NEW（全新事件，触发 LLM 情绪分析）| title=%s", news_title)

    # Step 2a：调用 LLM 情绪分析
    sentiment = _safe_parse_sentiment_defaults()  # 预置默认值，LLM 失败时原样落库
    try:
        news_text = _build_news_text_for_llm(news_data)
        raw_result: dict[str, Any] = await analyze_sentiment_and_surprise_with_llm(news_text)
        sentiment = _parse_sentiment_result(raw_result)
        logger.info(
            "LLM 情绪分析完成 | title=%s | score=%d | surprise=%d | catalyst=%s | entity=%s",
            news_title, sentiment.sentiment_score, sentiment.surprise_factor,
            sentiment.catalyst_type, sentiment.entity,
        )
    except json.JSONDecodeError as e:
        # LLM 返回了非法 JSON —— 使用默认值继续落库，绝不崩溃整个流程
        logger.warning(
            "LLM 返回非法 JSON，使用默认值继续落库 | title=%s | error=%s",
            news_title, e,
        )
    except TimeoutError as e:
        # LLM 请求超时 —— 同上
        logger.warning(
            "LLM 请求超时，使用默认值继续落库 | title=%s | error=%s",
            news_title, e,
        )
    except Exception as e:
        # 兜底：任何其他 LLM 异常 —— 同上，不能因 LLM 失败阻断入库
        logger.warning(
            "LLM 分析异常（兜底），使用默认值继续落库 | title=%s | error=%s",
            news_title, e,
        )

    # Step 2b：将 LLM 字段合并到 news_data（方便 save_to_db 透传）
    news_data_with_sentiment = {
        **news_data,
        "entity":          sentiment.entity,
        "sentiment_score": sentiment.sentiment_score,
        "surprise_factor": sentiment.surprise_factor,
        "catalyst_type":   sentiment.catalyst_type,
        "reasoning":       sentiment.reasoning,
    }

    # Step 2c：落库
    try:
        news_id = await save_to_db(
            news_data=news_data_with_sentiment,
            sentiment=sentiment,
            related_to_id=None,
        )
        return {"status": "stored", "reason": "new", "news_id": news_id, "llm_called": True}
    except Exception as e:
        logger.error("NEW 落库失败 | title=%s | error=%s", news_title, e)
        return {"status": "dropped", "reason": f"db_error: {e}", "news_id": None, "llm_called": True}


# ══════════════════════════════════════════════════════════════════
# 内部工具函数
# ══════════════════════════════════════════════════════════════════

def _safe_parse_sentiment_defaults() -> SentimentResult:
    """返回情绪分析的安全默认值（分数归零，类型标记为其他）。"""
    return SentimentResult(
        entity="",
        sentiment_score=0,
        surprise_factor=0,
        catalyst_type="其他",
        reasoning="LLM 分析失败，使用默认值",
    )


def _parse_sentiment_result(raw: dict[str, Any]) -> SentimentResult:
    """从 LLM 返回的 dict 中安全提取情绪字段，字段缺失或类型错误时回退默认值。

    sentiment_score 钳位到 [-5, 5]，surprise_factor 钳位到 [0, 5]，防止 LLM 越界。
    """
    return SentimentResult(
        entity=str(raw.get("entity", "")),
        sentiment_score=max(-5, min(5, int(raw.get("sentiment_score", 0)))),
        surprise_factor=max(0,  min(5, int(raw.get("surprise_factor", 0)))),
        catalyst_type=str(raw.get("catalyst_type", "其他")),
        reasoning=str(raw.get("reasoning", ""))[:150],
    )


def _build_news_text_for_llm(news_data: dict[str, Any]) -> str:
    """将 news_data 拼接成新闻正文，再注入 User Prompt 模板。

    正文格式：标题（重复一次加权）+ 摘要/正文前300字 + 来源
    最终套入 SENTIMENT_USER_PROMPT_TEMPLATE，供 LLM 调用方直接使用。
    """
    title   = news_data.get("title", "")
    content = news_data.get("content", "")[:300]  # 截断，控制 Token 消耗
    source  = news_data.get("source", "")

    parts = [title, title]  # 标题重复一次加权
    if content and content != title:
        parts.append(content)
    if source:
        parts.append(f"（来源：{source}）")

    news_text = " ".join(parts)
    return SENTIMENT_USER_PROMPT_TEMPLATE.format(news_text=news_text)
