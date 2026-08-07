"""统一 LLM token 用量统计 (llm_usage.py)
=====================================
按 scene 维度记录每次 LLM 调用的 token 消耗，便于按场景对账 DeepSeek 成本。

scene 取值（建议，非强制）：
  news_score_cn     中文新闻评分
  news_score_en     英文新闻评分
  news_translate_en 英译中翻译
  event_synth       事件合成（多源簇 → 事件包）
  digest            阶段简报生成
  ticker_mapping    公司名 → 股票代码映射

每次调用 emit 一条结构化日志（logger: alphareader.llm_usage），并在进程内累加，
供每日汇总（`log_llm_usage_summary` + `reset_llm_usage_stats`）使用。

注意：uvicorn 多 worker 下累加器为进程级，仅作近似；逐行日志才是完整审计源。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("alphareader.llm_usage")


@dataclass
class _SceneStat:
    calls: int = 0
    prompt: int = 0
    completion: int = 0
    cache_hit: int = 0
    reasoning: int = 0
    total: int = 0


_STATS: dict[str, _SceneStat] = {}


def log_llm_usage(
    scene: str,
    *,
    prompt: int,
    completion: int,
    cache_hit: int = 0,
    reasoning: int = 0,
    total: int | None = None,
) -> None:
    """记录一次 LLM 调用的 token 消耗（按 scene 归类）。

    参数：
        scene: 场景标签，见模块 docstring。
        prompt / completion / cache_hit / reasoning: DeepSeek usage 各字段（token 数，可空）。
        total: 总 token；缺省按 prompt+completion 估算（不含 cache 折抵）。
    """
    p = int(prompt or 0)
    c = int(completion or 0)
    h = int(cache_hit or 0)
    r = int(reasoning or 0)
    t = int(total) if total is not None else p + c

    logger.info(
        "LLM usage [scene=%s] prompt=%s completion=%s cache_hit=%s reasoning=%s total=%s",
        scene, p, c, h, r, t,
    )

    s = _STATS.get(scene)
    if s is None:
        s = _SceneStat()
        _STATS[scene] = s
    s.calls += 1
    s.prompt += p
    s.completion += c
    s.cache_hit += h
    s.reasoning += r
    s.total += t


def get_llm_usage_stats() -> dict[str, dict[str, int]]:
    """返回各 scene 的累计统计（拷贝，避免外部修改）。"""
    return {scene: dict(s.__dict__) for scene, s in _STATS.items()}


def reset_llm_usage_stats() -> None:
    """清空进程内累加器（通常每日 0 点汇总后调用）。"""
    _STATS.clear()


def log_llm_usage_summary(tag: str = "daily") -> None:
    """打印一份按 scene 拆分的累计汇总日志行，并输出合计。"""
    if not _STATS:
        logger.info("LLM usage summary [%s]: no calls since last reset", tag)
        return

    parts: list[str] = []
    g = _SceneStat()
    for scene in sorted(_STATS):
        s = _STATS[scene]
        parts.append(
            f"{scene}={s.calls}calls/{s.total}tok(p{s.prompt},c{s.completion},h{s.cache_hit})"
        )
        g.calls += s.calls
        g.prompt += s.prompt
        g.completion += s.completion
        g.cache_hit += s.cache_hit
        g.reasoning += s.reasoning
        g.total += s.total

    logger.info(
        "LLM usage summary [%s]: %s | GRAND calls=%d total=%d (prompt=%d completion=%d cache_hit=%d reasoning=%d)",
        tag, " ".join(parts), g.calls, g.total, g.prompt, g.completion, g.cache_hit, g.reasoning,
    )
