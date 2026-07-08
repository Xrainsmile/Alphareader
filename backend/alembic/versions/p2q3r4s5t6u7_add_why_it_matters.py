"""add why_it_matters to news

Revision ID: p2q3r4s5t6u7
Revises: o1o2o3_sepa
Create Date: 2026-07-08

为 news 表新增 why_it_matters 列，用于存储 AI 生成的"推荐理由"
（一句话告诉投资者为什么该关注这条新闻，对标 AIHOT 的推荐理由）。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "p2q3r4s5t6u7"
down_revision = "o1o2o3_sepa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news",
        sa.Column("why_it_matters", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("news", "why_it_matters")
