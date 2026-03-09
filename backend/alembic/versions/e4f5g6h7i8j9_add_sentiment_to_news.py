"""add sentiment fields to news

Revision ID: e4f5g6h7i8j9
Revises: d3e4f5g6h7i8
Create Date: 2026-03-09

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e4f5g6h7i8j9'
down_revision = 'd3e4f5g6h7i8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('news', sa.Column('sentiment_score', sa.SmallInteger(), nullable=True))
    op.add_column('news', sa.Column('surprise_factor', sa.SmallInteger(), nullable=True))
    op.add_column('news', sa.Column('catalyst_type', sa.String(32), nullable=True))
    op.add_column('news', sa.Column('sentiment_entity', sa.String(128), nullable=True))
    op.add_column('news', sa.Column('sentiment_reasoning', sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column('news', 'sentiment_reasoning')
    op.drop_column('news', 'sentiment_entity')
    op.drop_column('news', 'catalyst_type')
    op.drop_column('news', 'surprise_factor')
    op.drop_column('news', 'sentiment_score')
