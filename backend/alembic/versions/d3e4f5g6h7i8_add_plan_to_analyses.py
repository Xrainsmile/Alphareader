"""add plan column to sandbox_analyses and migrate legacy fields

Revision ID: d3e4f5g6h7i8
Revises: c2d3e4f5g6h7
Create Date: 2026-03-01

Add: plan (TEXT, nullable)
Migrate: discipline_action + risk_type + risk_price + risk_note → plan
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d3e4f5g6h7i8"
down_revision = "c2d3e4f5g6h7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 新增 plan 列（用 TEXT 避免长度限制）
    op.add_column("sandbox_analyses", sa.Column("plan", sa.Text(), nullable=True))

    # 2. 将历史数据的 discipline_action / risk_type / risk_price / risk_note 合并到 plan
    #    格式: "[留存] Top ¥1800.00 — 跌破1800止损"
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE sandbox_analyses
        SET plan = CONCAT_WS(' ',
            CASE discipline_action
                WHEN 'retain' THEN '[留存]'
                WHEN 'gray' THEN '[灰度]'
                WHEN 'research' THEN '[用研]'
                WHEN 'churn' THEN '[流失]'
                ELSE '[' || discipline_action || ']'
            END,
            CASE WHEN risk_type IS NOT NULL AND risk_type != '' THEN
                CASE risk_type
                    WHEN 'top' THEN 'Top'
                    WHEN 'bottom' THEN 'Bottom'
                    ELSE risk_type
                END
            ELSE NULL END,
            CASE WHEN risk_price IS NOT NULL THEN '¥' || risk_price::TEXT ELSE NULL END,
            CASE WHEN risk_note IS NOT NULL AND risk_note != '' THEN '— ' || risk_note ELSE NULL END
        )
        WHERE plan IS NULL
    """))


def downgrade() -> None:
    op.drop_column("sandbox_analyses", "plan")
