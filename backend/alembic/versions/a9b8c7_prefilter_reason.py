"""add prefilter_reason to news

Revision ID: a9b8c7_prefilter_reason
Revises: x6y7z8a9b0c1
Create Date: 2026-08-03

为 news 表新增 prefilter_reason 列，记录新闻经预筛（LLM 评分前过滤/压缩）的决策原因，
用于影子测试审计与误杀排查。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a9b8c7_prefilter_reason"
down_revision = "x6y7z8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news",
        sa.Column("prefilter_reason", sa.String(256), nullable=True),
    )
    op.create_index("ix_news_prefilter_reason", "news", ["prefilter_reason"])


def downgrade() -> None:
    op.drop_index("ix_news_prefilter_reason", table_name="news")
    op.drop_column("news", "prefilter_reason")
