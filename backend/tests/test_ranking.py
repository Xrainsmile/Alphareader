"""Tests for app.utils.ranking — Gravity-based ranking score."""

from datetime import datetime, timedelta, timezone

import pytest

from app.utils.ranking import calculate_ranking_score, gravity_sql_expression


class TestCalculateRankingScore:
    """Test the gravity ranking formula."""

    @pytest.fixture
    def now(self):
        return datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)

    # ── Basic formula correctness ──

    def test_recent_high_score_ranks_highest(self, now):
        """A high-score article published just now should rank very high."""
        score = calculate_ranking_score(9, now - timedelta(minutes=10), now=now)
        assert score > 0
        assert score > 1.5  # (9-1) / (0.17+2)^1.8 ≈ ~1.99

    def test_old_high_score_decays(self, now):
        """Same score, 24h later → much lower ranking."""
        recent = calculate_ranking_score(9, now - timedelta(hours=1), now=now)
        old = calculate_ranking_score(9, now - timedelta(hours=24), now=now)
        assert recent > old * 5  # should be significantly higher

    def test_higher_score_beats_lower_at_same_time(self, now):
        """At the same publish time, higher ai_score wins."""
        t = now - timedelta(hours=2)
        high = calculate_ranking_score(9, t, now=now)
        low = calculate_ranking_score(6, t, now=now)
        assert high > low

    def test_lower_score_recent_can_beat_higher_score_old(self, now):
        """A score-7 article 30min ago should beat a score-9 from 12h ago."""
        fresh_7 = calculate_ranking_score(7, now - timedelta(minutes=30), now=now)
        stale_9 = calculate_ranking_score(9, now - timedelta(hours=12), now=now)
        assert fresh_7 > stale_9

    # ── Normalization ──

    def test_score_0_to_100_normalized(self, now):
        """ai_score in 0-100 range should be auto-normalized to 0-10."""
        t = now - timedelta(hours=1)
        from_100 = calculate_ranking_score(90, t, now=now)
        from_10 = calculate_ranking_score(9, t, now=now)
        assert from_100 == from_10

    def test_score_0_to_10_used_directly(self, now):
        """ai_score <= 10 should be used directly."""
        t = now - timedelta(hours=1)
        s = calculate_ranking_score(8.5, t, now=now)
        assert s > 0

    # ── Edge cases ──

    def test_none_publish_time_returns_zero(self):
        assert calculate_ranking_score(9, None) == 0.0

    def test_future_publish_time_clamped(self, now):
        """Future publish time treated as 0 hours elapsed."""
        future = now + timedelta(hours=5)
        score = calculate_ranking_score(9, future, now=now)
        just_now = calculate_ranking_score(9, now, now=now)
        assert score == just_now

    def test_zero_score(self, now):
        """ai_score=0 → numerator max(0-1, 0) = 0 → rank = 0."""
        assert calculate_ranking_score(0, now, now=now) == 0.0

    def test_score_1_gives_zero(self, now):
        """ai_score=1 → (1-1)=0 → rank = 0 (noise floor)."""
        assert calculate_ranking_score(1, now, now=now) == 0.0

    def test_negative_score_clamped(self, now):
        """Negative scores clamped to 0."""
        assert calculate_ranking_score(-5, now, now=now) == 0.0

    def test_result_has_4_decimal_places(self, now):
        result = calculate_ranking_score(8, now - timedelta(hours=3), now=now)
        decimal_str = str(result).split(".")[-1]
        assert len(decimal_str) <= 4

    # ── Gravity factor tuning ──

    def test_higher_gravity_decays_faster(self, now):
        """Higher gravity → faster decay for the same article."""
        t = now - timedelta(hours=6)
        slow = calculate_ranking_score(8, t, gravity=1.2, now=now)
        fast = calculate_ranking_score(8, t, gravity=2.5, now=now)
        assert slow > fast

    def test_gravity_1_linear_like(self, now):
        """gravity=1 should decay roughly linearly."""
        t = now - timedelta(hours=10)
        score = calculate_ranking_score(8, t, gravity=1.0, now=now)
        assert score > 0

    # ── Timezone handling ──

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetime should work (assumed UTC)."""
        now = datetime(2026, 2, 10, 12, 0, 0)
        t = datetime(2026, 2, 10, 10, 0, 0)
        score = calculate_ranking_score(8, t, now=now)
        assert score > 0

    def test_mixed_timezone_handled(self):
        """One aware + one naive should still work."""
        now = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        t = datetime(2026, 2, 10, 10, 0, 0)  # naive
        score = calculate_ranking_score(8, t, now=now)
        assert score > 0


class TestGravitySqlExpression:
    """Test the SQL expression generator."""

    def test_returns_valid_sql_string(self):
        expr = gravity_sql_expression()
        assert "ai_score" in expr
        assert "published_at" in expr
        assert "POWER" in expr
        assert "1.8" in expr

    def test_custom_columns(self):
        expr = gravity_sql_expression(
            score_column="importance",
            time_column="created_at",
            gravity=2.0,
        )
        assert "importance" in expr
        assert "created_at" in expr
        assert "2.0" in expr

    def test_custom_gravity(self):
        expr = gravity_sql_expression(gravity=3.0)
        assert "3.0" in expr
