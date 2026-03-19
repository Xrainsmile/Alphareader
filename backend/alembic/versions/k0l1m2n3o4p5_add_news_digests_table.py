"""add news_digests table

Revision ID: k0l1m2n3o4p5
Revises: j9k0l1m2n3o4
Create Date: 2026-03-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "k0l1m2n3o4p5"
down_revision = "j9k0l1m2n3o4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_digests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("digest_date", sa.Date(), nullable=False),
        sa.Column("period_label", sa.String(length=32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("news_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("digest_date", "period_label", name="uq_digest_date_period"),
    )
    op.create_index("ix_news_digests_digest_date", "news_digests", ["digest_date"], unique=False)
    op.create_index(
        "ix_news_digests_date_desc",
        "news_digests",
        [sa.text("digest_date DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_news_digests_date_desc", table_name="news_digests")
    op.drop_index("ix_news_digests_digest_date", table_name="news_digests")
    op.drop_table("news_digests")
