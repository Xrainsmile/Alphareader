"""Add market field to stock tables for US stock support.

Tables affected:
  - stock_daily_quote: +market, name varchar(32)→varchar(128)
  - stock_rs_rating: +market, name varchar(32)→varchar(128)
  - screener_runs: +market
  - watchlist_daily: +market, name varchar(32)→varchar(128)
  - trend_screener_runs: +market
  - trend_watchlist_daily: +market, name varchar(32)→varchar(128)
  - news_catalyst_stocks: +market, name varchar(32)→varchar(128)

All existing rows get market='CN' (A股) as default.

Revision ID: n1n2n3_market
Revises: m1m2m3_phase2
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "n1n2n3_market"
down_revision = "m1m2m3_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add market column to all tables (NOT NULL with server_default) ──

    # stock_daily_quote
    op.add_column(
        "stock_daily_quote",
        sa.Column("market", sa.String(4), nullable=False, server_default="CN"),
    )
    op.create_index("ix_sdq_market", "stock_daily_quote", ["market"])
    op.create_index("ix_quote_market_date", "stock_daily_quote", ["market", "trade_date"])

    # stock_rs_rating
    op.add_column(
        "stock_rs_rating",
        sa.Column("market", sa.String(4), nullable=False, server_default="CN"),
    )
    op.create_index("ix_srs_market", "stock_rs_rating", ["market"])
    op.create_index("ix_rs_market_date", "stock_rs_rating", ["market", "trade_date"])

    # screener_runs
    op.add_column(
        "screener_runs",
        sa.Column("market", sa.String(4), nullable=False, server_default="CN"),
    )
    op.create_index("ix_scr_run_market", "screener_runs", ["market"])

    # watchlist_daily
    op.add_column(
        "watchlist_daily",
        sa.Column("market", sa.String(4), nullable=False, server_default="CN"),
    )
    op.create_index("ix_wl_market", "watchlist_daily", ["market"])
    op.create_index("ix_watchlist_market_date", "watchlist_daily", ["market", "run_date"])

    # trend_screener_runs
    op.add_column(
        "trend_screener_runs",
        sa.Column("market", sa.String(4), nullable=False, server_default="CN"),
    )
    op.create_index("ix_tsr_market", "trend_screener_runs", ["market"])

    # trend_watchlist_daily
    op.add_column(
        "trend_watchlist_daily",
        sa.Column("market", sa.String(4), nullable=False, server_default="CN"),
    )
    op.create_index("ix_twl_market", "trend_watchlist_daily", ["market"])
    op.create_index(
        "ix_trend_watchlist_market_date", "trend_watchlist_daily", ["market", "run_date"]
    )

    # news_catalyst_stocks
    op.add_column(
        "news_catalyst_stocks",
        sa.Column("market", sa.String(4), nullable=False, server_default="CN"),
    )
    op.create_index("ix_ncs_market", "news_catalyst_stocks", ["market"])
    op.create_index(
        "ix_catalyst_market_date", "news_catalyst_stocks", ["market", "catalyst_date"]
    )

    # ── 2. Expand name columns from varchar(32) to varchar(128) ──

    op.alter_column(
        "stock_daily_quote", "name",
        type_=sa.String(128), existing_type=sa.String(32),
    )
    op.alter_column(
        "stock_rs_rating", "name",
        type_=sa.String(128), existing_type=sa.String(32),
    )
    op.alter_column(
        "watchlist_daily", "name",
        type_=sa.String(128), existing_type=sa.String(32),
    )
    op.alter_column(
        "trend_watchlist_daily", "name",
        type_=sa.String(128), existing_type=sa.String(32),
    )
    op.alter_column(
        "news_catalyst_stocks", "name",
        type_=sa.String(128), existing_type=sa.String(32),
    )


def downgrade() -> None:
    # ── Revert name column sizes ──
    op.alter_column(
        "news_catalyst_stocks", "name",
        type_=sa.String(32), existing_type=sa.String(128),
    )
    op.alter_column(
        "trend_watchlist_daily", "name",
        type_=sa.String(32), existing_type=sa.String(128),
    )
    op.alter_column(
        "watchlist_daily", "name",
        type_=sa.String(32), existing_type=sa.String(128),
    )
    op.alter_column(
        "stock_rs_rating", "name",
        type_=sa.String(32), existing_type=sa.String(128),
    )
    op.alter_column(
        "stock_daily_quote", "name",
        type_=sa.String(32), existing_type=sa.String(128),
    )

    # ── Drop market indexes and columns ──
    op.drop_index("ix_catalyst_market_date", "news_catalyst_stocks")
    op.drop_index("ix_ncs_market", "news_catalyst_stocks")
    op.drop_column("news_catalyst_stocks", "market")

    op.drop_index("ix_trend_watchlist_market_date", "trend_watchlist_daily")
    op.drop_index("ix_twl_market", "trend_watchlist_daily")
    op.drop_column("trend_watchlist_daily", "market")

    op.drop_index("ix_tsr_market", "trend_screener_runs")
    op.drop_column("trend_screener_runs", "market")

    op.drop_index("ix_watchlist_market_date", "watchlist_daily")
    op.drop_index("ix_wl_market", "watchlist_daily")
    op.drop_column("watchlist_daily", "market")

    op.drop_index("ix_scr_run_market", "screener_runs")
    op.drop_column("screener_runs", "market")

    op.drop_index("ix_rs_market_date", "stock_rs_rating")
    op.drop_index("ix_srs_market", "stock_rs_rating")
    op.drop_column("stock_rs_rating", "market")

    op.drop_index("ix_quote_market_date", "stock_daily_quote")
    op.drop_index("ix_sdq_market", "stock_daily_quote")
    op.drop_column("stock_daily_quote", "market")
