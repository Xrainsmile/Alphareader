"""add sepa training system tables

Revision ID: o1o2o3_sepa
Revises: n1n2n3_market
Create Date: 2026-06-18

SEPA 模拟盘训练系统四张表（三市场 CN/HK/US 独立账户）：
  sepa_accounts / sepa_market_gates / sepa_watchlist_items / sepa_trades
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "o1o2o3_sepa"
down_revision = "n1n2n3_market"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sepa_accounts ──
    op.create_table(
        "sepa_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(4), nullable=False),
        sa.Column("currency", sa.String(4), nullable=False),
        sa.Column("initial_capital", sa.Numeric(18, 4), nullable=False),
        sa.Column("inception_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market", name="uq_sepa_account_market"),
    )

    # ── sepa_market_gates ──
    op.create_table(
        "sepa_market_gates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(4), nullable=False),
        sa.Column("index_above_ma50", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ma50_trending_up", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("breadth_healthy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("new_highs_gt_lows", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gate_open", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market", name="uq_sepa_gate_market"),
    )

    # ── sepa_watchlist_items ──
    op.create_table(
        "sepa_watchlist_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(4), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False, server_default=""),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("ma50", sa.Float(), nullable=True),
        sa.Column("ma150", sa.Float(), nullable=True),
        sa.Column("ma200", sa.Float(), nullable=True),
        sa.Column("ma200_rising", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("high52w", sa.Float(), nullable=True),
        sa.Column("low52w", sa.Float(), nullable=True),
        sa.Column("rs", sa.Float(), nullable=True),
        sa.Column("template_pass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("template_detail", sa.JSON(), nullable=True),
        sa.Column("vcp_stage", sa.String(128), nullable=True),
        sa.Column("pivot_price", sa.Float(), nullable=True),
        sa.Column("fundamental_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market", "symbol", name="uq_sepa_watch_market_symbol"),
    )
    op.create_index("ix_sepa_watchlist_items_market", "sepa_watchlist_items", ["market"])
    op.create_index("ix_sepa_watch_market_status", "sepa_watchlist_items", ["market", "status"])

    # ── sepa_trades ──
    op.create_table(
        "sepa_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(4), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False, server_default=""),
        sa.Column("side", sa.String(8), nullable=False, server_default="buy"),
        sa.Column("status", sa.String(8), nullable=False, server_default="open"),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("entry_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("pivot_price", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("max_risk", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("max_risk_pct", sa.Float(), nullable=True),
        sa.Column("entry_reason", sa.Text(), nullable=True),
        sa.Column("risky_entry", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("exit_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
        sa.Column("pnl_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("exit_reason", sa.String(32), nullable=True),
        sa.Column("followed_rule", sa.Boolean(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sepa_trades_market", "sepa_trades", ["market"])
    op.create_index("ix_sepa_trades_symbol", "sepa_trades", ["symbol"])
    op.create_index("ix_sepa_trade_market_status", "sepa_trades", ["market", "status"])
    op.create_index("ix_sepa_trade_market_entry", "sepa_trades", ["market", "entry_date"])


def downgrade() -> None:
    op.drop_table("sepa_trades")
    op.drop_table("sepa_watchlist_items")
    op.drop_table("sepa_market_gates")
    op.drop_table("sepa_accounts")
