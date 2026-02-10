"""Gravity-based ranking score — Hacker News algorithm adapted for financial news.

Formula:  rank = (ai_score - 1) / (hours_elapsed + 2) ^ gravity

- ai_score:  DeepSeek importance score (0-100 scale, normalized to 0-10 for calculation)
- hours_elapsed: hours since publish time
- gravity: decay factor (default 1.8 — financial news decays fast)

Higher gravity → faster decay.  A score-9 article published 6 hours ago
will rank below a score-7 article published 1 hour ago.
"""

from __future__ import annotations

from datetime import datetime, timezone


def calculate_ranking_score(
    ai_score: float,
    publish_time: datetime | None,
    gravity: float = 1.8,
    now: datetime | None = None,
) -> float:
    """Calculate time-decayed ranking score using the gravity algorithm.

    Args:
        ai_score: AI importance score. Accepts 0-100 (auto-normalized to 0-10)
                  or 0-10 directly.
        publish_time: When the article was published (timezone-aware or naive UTC).
        gravity: Decay exponent. Default 1.8 (tuned for financial news).
                 - 1.2 = slow decay (general news)
                 - 1.8 = standard decay (financial news)
                 - 2.5 = aggressive decay (breaking / flash news)
        now: Override "current time" for testing. Defaults to UTC now.

    Returns:
        Ranking score as float, rounded to 4 decimal places.
        Higher = more prominent.
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

    # Gravity formula: rank = (score - 1) / (hours + 2) ^ gravity
    # The "-1" ensures score=1 items get rank=0 (noise floor)
    # The "+2" prevents division by zero and dampens the first 2 hours
    numerator = max(score - 1.0, 0.0)
    denominator = (hours_elapsed + 2.0) ** gravity

    rank = numerator / denominator

    return round(rank, 4)


def gravity_sql_expression(
    score_column: str = "ai_score",
    time_column: str = "published_at",
    gravity: float = 1.8,
) -> str:
    """Generate a raw SQL expression for ranking score.

    Can be used in ORDER BY or as a computed column.

    Args:
        score_column: Name of the AI score column.
        time_column: Name of the publish timestamp column (must be TIMESTAMPTZ).
        gravity: Decay exponent.

    Returns:
        PostgreSQL SQL expression string.
    """
    return (
        f"(GREATEST({score_column} / 10.0 - 1, 0)) "
        f"/ POWER("
        f"GREATEST(EXTRACT(EPOCH FROM (NOW() - COALESCE({time_column}, NOW()))) / 3600.0, 0) + 2, "
        f"{gravity})"
    )
