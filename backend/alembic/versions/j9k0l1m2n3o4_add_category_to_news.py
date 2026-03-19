"""add category to news

Revision ID: j9k0l1m2n3o4
Revises: i8j9k0l1m2n3
Create Date: 2026-03-18 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "j9k0l1m2n3o4"
down_revision = "i8j9k0l1m2n3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 category 列，默认值 "财经"
    op.add_column(
        "news",
        sa.Column("category", sa.String(32), nullable=False, server_default="财经"),
    )
    op.create_index("ix_news_category", "news", ["category"])

    # 将现有 TechCrunch 新闻标记为 "科技"
    op.execute("UPDATE news SET category = '科技' WHERE source = 'TechCrunch'")


def downgrade() -> None:
    op.drop_index("ix_news_category", table_name="news")
    op.drop_column("news", "category")
