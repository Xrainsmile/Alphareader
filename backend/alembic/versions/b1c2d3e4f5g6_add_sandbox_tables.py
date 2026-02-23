"""add sandbox tables

Revision ID: b1c2d3e4f5g6
Revises: a2b3c4d5e6f7
Create Date: 2026-02-24

模拟仓四张表：sandbox_stocks / sandbox_analyses / sandbox_trades / sandbox_nav
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5g6"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sandbox_stocks ──
    op.create_table(
        "sandbox_stocks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts_code", sa.String(10), nullable=False),
        sa.Column("name", sa.String(32), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="watching"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", name="uq_sandbox_stock_code"),
    )
    op.create_index("ix_sandbox_stocks_ts_code", "sandbox_stocks", ["ts_code"])

    # ── sandbox_analyses ──
    op.create_table(
        "sandbox_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("ts_code", sa.String(10), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False, server_default="neutral"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sandbox_analyses_stock_id", "sandbox_analyses", ["stock_id"])
    op.create_index("ix_sandbox_analyses_ts_code", "sandbox_analyses", ["ts_code"])
    op.create_index("ix_analysis_stock_created", "sandbox_analyses", ["stock_id", "created_at"])

    # ── sandbox_trades ──
    op.create_table(
        "sandbox_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("ts_code", sa.String(10), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sandbox_trades_stock_id", "sandbox_trades", ["stock_id"])
    op.create_index("ix_sandbox_trades_ts_code", "sandbox_trades", ["ts_code"])
    op.create_index("ix_trade_stock_date", "sandbox_trades", ["stock_id", "trade_date"])

    # ── sandbox_nav ──
    op.create_table(
        "sandbox_nav",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("total_market_value", sa.Numeric(16, 4), nullable=False),
        sa.Column("cash", sa.Numeric(16, 4), nullable=False),
        sa.Column("nav", sa.Float(), nullable=False),
        sa.Column("total_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", name="uq_sandbox_nav_date"),
    )
    op.create_index("ix_nav_date", "sandbox_nav", ["trade_date"])


def downgrade() -> None:
    op.drop_table("sandbox_nav")
    op.drop_table("sandbox_trades")
    op.drop_table("sandbox_analyses")
    op.drop_table("sandbox_stocks")
