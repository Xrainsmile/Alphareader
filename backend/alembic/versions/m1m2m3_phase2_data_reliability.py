"""Phase 2: Data reliability — indexes, column types, constraints.

M-1: Add missing indexes (pipeline_runs.started_at, news.tags GIN,
     watchlist_daily/trend_watchlist_daily composite score indexes)
M-2: Remove redundant indexes (sandbox_nav.ix_nav_date, stock_daily_quote.ix_quote_code_date)
M-3: Fix column types (reports.date String→Date, stock_daily_quote.volume Integer→BigInteger,
     sandbox_nav.nav/total_pnl Float→Numeric, sandbox_analyses.score Float→Numeric)

Revision ID: m1m2m3_phase2
Revises: l1m2n3o4p5q6
Create Date: 2026-03-21
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "m1m2m3_phase2"
down_revision = "l1m2n3o4p5q6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── M-1: Add missing indexes ──

    # pipeline_runs.started_at — frequently filtered by date range
    op.create_index("ix_pipeline_runs_started_at", "pipeline_runs", ["started_at"])

    # news.tags — GIN index for ARRAY element queries (tags @> ARRAY['sector'])
    op.create_index("ix_news_tags", "news", ["tags"], postgresql_using="gin")

    # watchlist_daily (run_date, vcp_score DESC) — for sorted daily queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_watchlist_date_score "
        "ON watchlist_daily (run_date, vcp_score DESC NULLS LAST)"
    )

    # trend_watchlist_daily (run_date, trend_score DESC) — for sorted daily queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_trend_watchlist_date_score "
        "ON trend_watchlist_daily (run_date, trend_score DESC NULLS LAST)"
    )

    # ── M-2: Remove redundant indexes ──

    # sandbox_nav.ix_nav_date duplicates uq_sandbox_nav_date unique constraint
    op.execute("DROP INDEX IF EXISTS ix_nav_date")

    # stock_daily_quote.ix_quote_code_date duplicates uq_quote_code_date unique constraint
    op.execute("DROP INDEX IF EXISTS ix_quote_code_date")

    # ── M-3: Fix column types ──

    # reports.date: varchar(32) → date
    # First convert existing string data to date
    op.execute(
        "ALTER TABLE reports "
        "ALTER COLUMN date TYPE date USING date::date"
    )

    # stock_daily_quote.volume: integer → bigint
    op.execute(
        "ALTER TABLE stock_daily_quote "
        "ALTER COLUMN volume TYPE bigint"
    )

    # sandbox_analyses.score: float → numeric(3,1)
    op.execute(
        "ALTER TABLE sandbox_analyses "
        "ALTER COLUMN score TYPE numeric(3,1) USING score::numeric(3,1)"
    )

    # sandbox_nav.nav: float → numeric(16,4)
    op.execute(
        "ALTER TABLE sandbox_nav "
        "ALTER COLUMN nav TYPE numeric(16,4) USING nav::numeric(16,4)"
    )

    # sandbox_nav.total_pnl: float → numeric(16,4)
    op.execute(
        "ALTER TABLE sandbox_nav "
        "ALTER COLUMN total_pnl TYPE numeric(16,4) USING total_pnl::numeric(16,4)"
    )


def downgrade() -> None:
    # ── Revert M-3 column types ──
    op.execute("ALTER TABLE sandbox_nav ALTER COLUMN total_pnl TYPE double precision USING total_pnl::double precision")
    op.execute("ALTER TABLE sandbox_nav ALTER COLUMN nav TYPE double precision USING nav::double precision")
    op.execute("ALTER TABLE sandbox_analyses ALTER COLUMN score TYPE double precision USING score::double precision")
    op.execute("ALTER TABLE stock_daily_quote ALTER COLUMN volume TYPE integer USING volume::integer")
    op.execute("ALTER TABLE reports ALTER COLUMN date TYPE varchar(32) USING date::varchar(32)")

    # ── Revert M-2: Recreate removed indexes ──
    op.create_index("ix_quote_code_date", "stock_daily_quote", ["ts_code", "trade_date"])
    op.create_index("ix_nav_date", "sandbox_nav", ["trade_date"])

    # ── Revert M-1: Drop added indexes ──
    op.execute("DROP INDEX IF EXISTS ix_trend_watchlist_date_score")
    op.execute("DROP INDEX IF EXISTS ix_watchlist_date_score")
    op.drop_index("ix_news_tags", "news")
    op.drop_index("ix_pipeline_runs_started_at", "pipeline_runs")
