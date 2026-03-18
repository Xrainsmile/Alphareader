"""add trend_screener_runs and trend_watchlist_daily tables

Revision ID: i8j9k0l1m2n3
Revises: h7i8j9k0l1m2
Create Date: 2026-03-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'i8j9k0l1m2n3'
down_revision = 'h7i8j9k0l1m2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── trend_screener_runs ──
    op.create_table(
        'trend_screener_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('duration_sec', sa.Float(), nullable=False),
        sa.Column('total_input', sa.Integer(), nullable=False),
        sa.Column('trend_passed', sa.Integer(), nullable=False),
        sa.Column('final_count', sa.Integer(), nullable=False),
        sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_trend_screener_runs_run_date'), 'trend_screener_runs', ['run_date'], unique=False)

    # ── trend_watchlist_daily ──
    op.create_table(
        'trend_watchlist_daily',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('ts_code', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=32), nullable=True),
        sa.Column('current_price', sa.Float(), nullable=True),
        sa.Column('ma20', sa.Float(), nullable=True),
        sa.Column('ma50', sa.Float(), nullable=True),
        sa.Column('adx', sa.Float(), nullable=True),
        sa.Column('rsi', sa.Float(), nullable=True),
        sa.Column('volume_ratio', sa.Float(), nullable=True),
        sa.Column('trend_score', sa.Float(), nullable=True),
        sa.Column('industry', sa.String(length=64), nullable=True),
        sa.Column('concepts', sa.String(length=512), nullable=True),
        sa.Column('main_business', sa.Text(), nullable=True),
        sa.Column('fund_flow_net', sa.Float(), nullable=True),
        sa.Column('run_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_date', 'ts_code', name='uq_trend_watchlist_daily'),
    )
    op.create_index(op.f('ix_trend_watchlist_daily_run_date'), 'trend_watchlist_daily', ['run_date'], unique=False)
    op.create_index(op.f('ix_trend_watchlist_daily_ts_code'), 'trend_watchlist_daily', ['ts_code'], unique=False)
    op.create_index(op.f('ix_trend_watchlist_daily_run_id'), 'trend_watchlist_daily', ['run_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trend_watchlist_daily_run_id'), table_name='trend_watchlist_daily')
    op.drop_index(op.f('ix_trend_watchlist_daily_ts_code'), table_name='trend_watchlist_daily')
    op.drop_index(op.f('ix_trend_watchlist_daily_run_date'), table_name='trend_watchlist_daily')
    op.drop_table('trend_watchlist_daily')
    op.drop_index(op.f('ix_trend_screener_runs_run_date'), table_name='trend_screener_runs')
    op.drop_table('trend_screener_runs')
