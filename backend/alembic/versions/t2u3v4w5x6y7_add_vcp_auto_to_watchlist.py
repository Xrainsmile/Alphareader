"""add vcp_auto JSON column to sepa_watchlist_items

承载 VCP 形态算法自动识别结果（由 refresh-vcp 批量回填），
与人工 vcp_confirmed 决策字段相互独立。

Revision ID: t2u3v4w5x6y7
Revises: s1t2r3_market_adaptability
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't2u3v4w5x6y7'
down_revision: Union[str, None] = 's1t2r3_market_adaptability'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sepa_watchlist_items',
        sa.Column('vcp_auto', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('sepa_watchlist_items', 'vcp_auto')
