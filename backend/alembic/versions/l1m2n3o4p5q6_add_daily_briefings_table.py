"""add daily_briefings table

Revision ID: l1m2n3o4p5q6
Revises: k0l1m2n3o4p5
Create Date: 2026-03-20 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "l1m2n3o4p5q6"
down_revision = "k0l1m2n3o4p5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_briefings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("briefing_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("meta", JSONB(), nullable=False, server_default="{}"),
        sa.Column("prompt_tokens_est", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generation_sec", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("briefing_date", name="uq_briefing_date"),
    )
    op.create_index("ix_daily_briefings_briefing_date", "daily_briefings", ["briefing_date"], unique=False)
    op.create_index(
        "ix_briefing_date_desc",
        "daily_briefings",
        [sa.text("briefing_date DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_briefing_date_desc", table_name="daily_briefings")
    op.drop_index("ix_daily_briefings_briefing_date", table_name="daily_briefings")
    op.drop_table("daily_briefings")
