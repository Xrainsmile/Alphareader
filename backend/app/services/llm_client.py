"""LLM 客户端封装 (llm_client.py)
================================
职责：统一封装 DeepSeek（OpenAI 兼容）API 的流式调用，
消除 digest_service / briefing_service 中重复的 streaming 解析与重试逻辑。

设计要点：
  - streaming 模式逐块接收，避免长回复因空闲超时导致 ReadError / ConnectError
  - 自动重试（429/5xx/网络错误），指数退避 + 抖动
  - 返回拼接后的完整文本，JSON 提取由调用方各自处理

调用方：
  - digest_service._call_deepseek_digest() — 时段新闻摘要
  - briefing_service._call_deepseek_catalyst() — 每日研报新闻×股票关联判断
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import random

import httpx

from app.config import settings

logger = logging.getLogger("alphareader.llm_client")

# DeepSeek 内容安全审查关键词（与 llm_news_filter 保持一致）
_CONTENT_RISK_KEYWORDS = ("Content Exists Risk", "content_filter", "content_policy")


async def stream_chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1500,
    max_retries: int | None = None,
    log_tag: str = "LLM",
) -> str:
    """流式调用 DeepSeek（OpenAI 兼容）Chat API，返回拼接后的完整文本。

    参数：
        messages: OpenAI messages 数组（system / user）
        model: 模型名，默认用 settings.DEEPSEEK_MODEL
        temperature: 采样温度
        max_tokens: 最大输出 token 数
        max_retries: 最大重试次数，默认 max(settings.LLM_MAX_RETRIES, 3)
        log_tag: 日志前缀（区分 digest / catalyst 等场景）

    返回：
        拼接后的完整文本；API key 未配置或全部重试失败时返回空串。

    重试策略：
        - HTTP 429 / 5xx / 网络错误 / 空响应 → 指数退避重试
        - HTTP 400 内容审查 → 不重试，直接返回空串（上层走兜底）
    """
    api_key = settings.DEEPSEEK_API_KEY
    if not api_key or api_key.startswith("sk-your"):
        logger.warning("%s: DeepSeek API key not configured, returning empty", log_tag)
        return ""

    if model is None:
        model = settings.DEEPSEEK_MODEL
    if max_retries is None:
        max_retries = max(settings.LLM_MAX_RETRIES, 3)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)) as client:
        for attempt in range(1, max_retries + 1):
            try:
                chunks: list[str] = []
                async with client.stream(
                    "POST",
                    settings.DEEPSEEK_API_URL,
                    json=payload,
                    headers=headers,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = _json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta and delta["content"]:
                                chunks.append(delta["content"])
                        except (_json.JSONDecodeError, KeyError, IndexError):
                            continue

                content = "".join(chunks).strip()
                if content:
                    logger.info("%s stream OK (attempt %d): %d chars",
                                log_tag, attempt, len(content))
                    return content

                logger.warning("%s stream returned empty (attempt %d/%d)",
                               log_tag, attempt, max_retries)

            except httpx.HTTPStatusError as e:
                body = e.response.text[:500] if e.response else "N/A"
                status_code = e.response.status_code if e.response else "?"
                # 内容审查 → 不重试
                if status_code == 400 and any(kw in body for kw in _CONTENT_RISK_KEYWORDS):
                    logger.warning("%s content risk (400), aborting: %s", log_tag, body[:200])
                    return ""
                logger.error("%s HTTP %s (attempt %d/%d): %s",
                             log_tag, status_code, attempt, max_retries, body)
            except Exception as e:
                logger.error("%s error (attempt %d/%d): %r",
                             log_tag, attempt, max_retries, e)

            if attempt < max_retries:
                delay = min(30.0, float(2 ** attempt)) + random.uniform(0, 1.0)
                await asyncio.sleep(delay)

    return ""
