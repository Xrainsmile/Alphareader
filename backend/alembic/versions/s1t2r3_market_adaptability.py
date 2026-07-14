"""create index_daily and market_adaptability tables

Revision ID: s1t2r3_market_adaptability
Revises: p5q3r4s5t6u7v9
Create Date: 2026-07-14

投资策略页改版（阶段二）：指数日行情 + VCP 五项市场适配度结果表。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "s1t2r3_market_adaptability"
down_revision = "p5q3r4s5t6u7v9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── index_daily：基准指数日行情 ──
    op.create_table(
        "index_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("index_code", sa.String(length=16), nullable=False),
        sa.Column("index_name", sa.String(length=64), nullable=True),
        sa.Column("market", sa.String(length=4), nullable=False, server_default="CN"),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("index_code", "trade_date", name="uq_index_daily"),
    )
    op.create_index("ix_index_daily_code", "index_daily", ["index_code"])
    op.create_index("ix_index_daily_market_date", "index_daily", ["market", "trade_date"])

    # ── market_adaptability：策略市场适配度结果 ──
    op.create_table(
        "market_adaptability",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_id", sa.String(length=16), nullable=False),
        sa.Column("market", sa.String(length=4), nullable=False, server_default="CN"),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="neutral"),
        sa.Column("dimension_scores", JSONB(), nullable=False),
        sa.Column("reason_codes", JSONB(), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("rule_version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("input_data_version", sa.String(length=128), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", "market", "trade_date", name="uq_market_adaptability"),
    )
    op.create_index("ix_adapt_market_date", "market_adaptability", ["market", "trade_date"])


def downgrade() -> None:
    op.drop_index("ix_adapt_market_date", table_name="market_adaptability")
    op.drop_table("market_adaptability")
    op.drop_index("ix_index_daily_market_date", table_name="index_daily")
    op.drop_index("ix_index_daily_code", table_name="index_daily")
    op.drop_table("index_daily")
