"""add watchlist extra fields: name, industry, concepts, main_business, fund_flow_net

Revision ID: g6h7i8j9k0l1
Revises: f5g6h7i8j9k0
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'g6h7i8j9k0l1'
down_revision = 'f5g6h7i8j9k0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('watchlist_daily', sa.Column('name', sa.String(length=32), nullable=True))
    op.add_column('watchlist_daily', sa.Column('industry', sa.String(length=64), nullable=True))
    op.add_column('watchlist_daily', sa.Column('concepts', sa.String(length=512), nullable=True))
    op.add_column('watchlist_daily', sa.Column('main_business', sa.Text(), nullable=True))
    op.add_column('watchlist_daily', sa.Column('fund_flow_net', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('watchlist_daily', 'fund_flow_net')
    op.drop_column('watchlist_daily', 'main_business')
    op.drop_column('watchlist_daily', 'concepts')
    op.drop_column('watchlist_daily', 'industry')
    op.drop_column('watchlist_daily', 'name')
