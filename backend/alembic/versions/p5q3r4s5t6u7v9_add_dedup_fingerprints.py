"""add content_hash and simhash_fingerprint to news

Revision ID: p5q3r4s5t6u7v9
Revises: q3r4s5t6u7v8
Create Date: 2026-07-13

P5: 持久化去重指纹到 DB，评分前加载 7 天历史用于跨天旧闻识别。
"""
from alembic import op
import sqlalchemy as sa

revision = "p5q3r4s5t6u7v9"
down_revision = "q3r4s5t6u7v8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("news", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column("news", sa.Column("simhash_fingerprint", sa.BigInteger(), nullable=True))
    op.create_index("ix_news_content_hash", "news", ["content_hash"])
    op.create_index("ix_news_simhash_fingerprint", "news", ["simhash_fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_news_simhash_fingerprint", table_name="news")
    op.drop_index("ix_news_content_hash", table_name="news")
    op.drop_column("news", "simhash_fingerprint")
    op.drop_column("news", "content_hash")
