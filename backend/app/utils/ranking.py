"""Hacker Gravity — 直接复用 Hacker News 重力排名公式。

原版公式:  rank = (points - 1) / (hours_elapsed + 2) ^ gravity
本项目:    rank = (ai_score - 1) / (hours_elapsed + 2) ^ gravity

- points:  在 HN 中为用户 upvote 数；本项目用 DeepSeek AI 评分 (0-10) 作为 points。
- hours_elapsed: 从 published_at 到当前的小时数。
- gravity: 时间衰减因子，固定 1.8（与 HN 默认值一致）。
- "-1":  使 score=1 的新闻 rank=0（噪声地板），与 HN 中 1 票帖子 rank=0 逻辑相同。
- "+2":  防除零 & 抑制发布初期极端值，同 HN 原版。

参考: https://news.ycombinator.com/item?id=1781013 (Paul Graham's gravity explanation)
"""

from __future__ import annotations

from datetime import datetime, timezone


def calculate_ranking_score(
    ai_score: float,
    publish_time: datetime | None,
    gravity: float = 1.8,
    now: datetime | None = None,
) -> float:
    """计算 Hacker Gravity 排名分数（Hacker News 原版重力公式）。

    公式: rank = (points - 1) / (hours_elapsed + 2) ^ gravity
    其中 points = ai_score（AI 评分替代用户投票数）。

    Args:
        ai_score: AI 评分，作为 HN 公式中的 points。
                  接受 0-100（自动归一化为 0-10）或 0-10。
        publish_time: 文章发布时间（时区感知或 naive UTC）。
        gravity: 时间衰减指数，默认 1.8（与 HN 默认值一致）。
        now: 覆盖"当前时间"，用于测试。默认 UTC now。

    Returns:
        Hacker Gravity 分数（float，保留 4 位小数），越高越靠前。
    """
    if publish_time is None:
        return 0.0

    # Normalize ai_score: if > 10, assume 0-100 scale → convert to 0-10
    score = ai_score / 10.0 if ai_score > 10 else float(ai_score)

    # Ensure score is at least 0
    score = max(score, 0.0)

    # Calculate time elapsed in hours
    if now is None:
        now = datetime.now(timezone.utc)

    # Make both timezone-aware for comparison
    if publish_time.tzinfo is None:
        publish_time = publish_time.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    elapsed_seconds = (now - publish_time).total_seconds()

    # Clamp: future timestamps treated as "just now" (0 hours)
    hours_elapsed = max(elapsed_seconds / 3600.0, 0.0)

    # Hacker News 原版重力公式: rank = (points - 1) / (hours + 2) ^ gravity
    # points = ai_score; "-1" 使 1 分新闻 rank=0（与 HN 1 票帖子逻辑一致）
    # "+2" 防除零 & 抑制前 2 小时极端值（同 HN）
    numerator = max(score - 1.0, 0.0)
    denominator = (hours_elapsed + 2.0) ** gravity

    rank = numerator / denominator

    return round(rank, 4)


def gravity_sql_expression(
    score_column: str = "ai_score",
    time_column: str = "published_at",
    gravity: float = 1.8,
) -> str:
    """生成 Hacker Gravity 排名的 PostgreSQL SQL 表达式。

    可用于 ORDER BY 或计算列。

    Args:
        score_column: AI 评分列名（作为 HN 公式中的 points）。
        time_column: 发布时间列名（TIMESTAMPTZ）。
        gravity: 时间衰减指数，默认 1.8（同 HN）。

    Returns:
        PostgreSQL SQL 表达式字符串。
    """
    return (
        f"(GREATEST({score_column} / 10.0 - 1, 0)) "
        f"/ POWER("
        f"GREATEST(EXTRACT(EPOCH FROM (NOW() - COALESCE({time_column}, NOW()))) / 3600.0, 0) + 2, "
        f"{gravity})"
    )
