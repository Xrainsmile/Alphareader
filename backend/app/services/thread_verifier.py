#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""世界线 P2-9：LLM 二次语义校验（挡住「规则像、语义不像」的误归）。

为什么需要
----------
规则打分（S=0.55E+0.30M+0.15R + 实体门控 + 类型门控）只能判断
「形似」：共享实体多、类型不冲突。但它判断不了**语义是否同一条叙事**。
现网铁证：12 条 8-K 线（40+ 章）——几十家无关公司只因共享「8-K」这个
披露形式就被串成一条线，规则层无论怎么调阈值都挡不住，因为从规则看
它们确实"很像"。

本模块做**守门员**而非**决策者**：规则先筛出候选，只有规则判定 join=True
且 S 落在"灰色地带"（默认 [T_JOIN, T_JOIN+0.15)）时才送 LLM 复核。
S 已经很高的明显命中不再花 token，S 不够的已被规则挡掉。

成本：按日增量 47K token 估算，月成本增加不到 ¥2。

失败策略：LLM 不可用 / 超时 / 返回非法 → **放行**（保持规则判定）。
宁可放过不可错杀：误杀会让线碎片化，代价远高于偶尔的误归。
"""
from __future__ import annotations

import json
import logging
import re

from app.config import settings

logger = logging.getLogger("alphareader.thread_verify")

_SYSTEM = """你是新闻事件聚合的语义校验器。判断「待归事件」是否属于「目标世界线」这条连续叙事。

世界线 = 围绕同一**争夺标的**、按同一**推进机制**演进的事件序列。

判定标准（全部满足才是 yes）：
1. 争夺标的一致（同一个被争夺的东西：通航权、定价权、技术份额、政策走向…）
2. 推进机制一致（同一类因果链：制裁→反制、供需缺口→涨价、数据→预期→政策…）
3. 读者会把两者当作同一件事的连续进展

判定为 no 的典型情况：
- 只是**形式相似**（都提交 8-K、都发财报、都是市场收盘综述），但主体无关
- 只是**共享通用概念**（都提到油价/AI/通胀），但争夺的标的不同
- 一个是原因、一个是结果，但分属不同的叙事主线（应各归其线，用传导边连接）

只输出 JSON：{"verdict":"yes|no","reason":"不超过25字"}
不要输出任何其他内容。"""

_USER = """目标世界线：{title}
争夺标的：{asset}
推进机制：{mech}
已有章节（最近5条）：
{chapters}

待归事件：{ev_title}
事件摘要：{ev_summary}

这条待归事件是否属于上述世界线？"""


def should_verify(s: float) -> bool:
    """是否值得送 LLM 复核：只查规则判 join 且落在灰色地带的。

    S 远高于阈值 → 明显命中，不必查（省 token）。
    S 低于阈值   → 已被规则挡掉，不必查。
    """
    if not settings.THREAD_LLM_VERIFY_ENABLED:
        return False
    lo = settings.THREAD_T_JOIN
    hi = lo + settings.THREAD_LLM_VERIFY_BAND
    return lo <= s < hi


async def verify(
    ev_title: str,
    ev_summary: str,
    thread_title: str,
    thread_asset: str,
    thread_mech: str,
    chapters: list[str],
) -> bool | None:
    """返回 True(同线) / False(不同线) / None(无法判定，放行)。"""
    try:
        from app.services.llm_client import stream_chat
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_client import failed: %s", exc)
        return None

    user = _USER.format(
        title=thread_title or "（未命名）",
        asset=thread_asset or "（未标注）",
        mech=thread_mech or "（未标注）",
        chapters="\n".join("- " + c for c in chapters[:5]) or "（无）",
        ev_title=ev_title or "（无标题）",
        ev_summary=(ev_summary or "")[:300] or "（无摘要）",
    )
    try:
        raw = await stream_chat(
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": user}],
            temperature=0.0,
            max_tokens=120,
            log_tag="THREAD_VERIFY",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("thread verify llm call failed: %s", exc)
        return None

    if not raw or not raw.strip():
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        logger.warning("thread verify: no JSON in response: %r", raw[:120])
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        logger.warning("thread verify: bad JSON: %r", m.group(0)[:120])
        return None
    v = str(obj.get("verdict", "")).strip().lower()
    if v in ("yes", "true", "1"):
        return True
    if v in ("no", "false", "0"):
        return False
    return None
