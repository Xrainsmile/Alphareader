"""init_news_table

Revision ID: 1fc3903986cd
Revises: 
Create Date: 2026-02-10 18:59:35.376868

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1fc3903986cd'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the news table with all indexes."""
    op.create_table(
        'news',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(512), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('source', sa.String(128), nullable=False),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ai_score', sa.Integer(), nullable=True, default=0),
        sa.Column('ai_summary', sa.String(1024), nullable=True),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('url'),
    )
    # Single-column indexes
    op.create_index('ix_news_title', 'news', ['title'])
    op.create_index('ix_news_source', 'news', ['source'])
    op.create_index('ix_news_ai_score', 'news', ['ai_score'])
    # Composite indexes for query performance
    op.create_index('ix_news_created_score', 'news', [sa.text('created_at DESC'), sa.text('ai_score DESC')])
    op.create_index('ix_news_source_score', 'news', ['source', sa.text('ai_score DESC')])


def downgrade() -> None:
    """Drop the news table."""
    op.drop_index('ix_news_source_score', table_name='news')
    op.drop_index('ix_news_created_score', table_name='news')
    op.drop_index('ix_news_ai_score', table_name='news')
    op.drop_index('ix_news_source', table_name='news')
    op.drop_index('ix_news_title', table_name='news')
    op.drop_table('news')
