"""add is_highlight to news

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2026-07-13

P2 ③：新增 is_highlight 布尔列，用于两层筛选（信息流 vs 重点推荐）。
由 LLM 在评分时显式输出，与 ai_score 解耦——高分不一定是重点，
重点必须是"明确的强催化 + 显著预期差"。默认 false，兼容存量数据。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "q3r4s5t6u7v8"
down_revision = "p2q3r4s5t6u7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news",
        sa.Column(
            "is_highlight",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("ix_news_is_highlight", "news", ["is_highlight"])


def downgrade() -> None:
    op.drop_index("ix_news_is_highlight", table_name="news")
    op.drop_column("news", "is_highlight")
