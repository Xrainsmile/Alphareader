"""add screener_runs and watchlist_daily tables

Revision ID: f5g6h7i8j9k0
Revises: e4f5g6h7i8j9
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f5g6h7i8j9k0'
down_revision = 'e4f5g6h7i8j9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── screener_runs ──
    op.create_table(
        'screener_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('duration_sec', sa.Float(), nullable=False),
        sa.Column('total_input', sa.Integer(), nullable=False),
        sa.Column('stage2_passed', sa.Integer(), nullable=False),
        sa.Column('fundamental_passed', sa.Integer(), nullable=False),
        sa.Column('final_count', sa.Integer(), nullable=False),
        sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_screener_runs_run_date'), 'screener_runs', ['run_date'], unique=False)

    # ── watchlist_daily ──
    op.create_table(
        'watchlist_daily',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('ts_code', sa.String(length=10), nullable=False),
        sa.Column('current_price', sa.Float(), nullable=True),
        sa.Column('ema20', sa.Float(), nullable=True),
        sa.Column('ema50', sa.Float(), nullable=True),
        sa.Column('ema120', sa.Float(), nullable=True),
        sa.Column('vcp_score', sa.Float(), nullable=True),
        sa.Column('eps_growth', sa.Float(), nullable=True),
        sa.Column('revenue_yoy', sa.Float(), nullable=True),
        sa.Column('run_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_date', 'ts_code', name='uq_watchlist_daily'),
    )
    op.create_index(op.f('ix_watchlist_daily_run_date'), 'watchlist_daily', ['run_date'], unique=False)
    op.create_index(op.f('ix_watchlist_daily_ts_code'), 'watchlist_daily', ['ts_code'], unique=False)
    op.create_index(op.f('ix_watchlist_daily_run_id'), 'watchlist_daily', ['run_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_watchlist_daily_run_id'), table_name='watchlist_daily')
    op.drop_index(op.f('ix_watchlist_daily_ts_code'), table_name='watchlist_daily')
    op.drop_index(op.f('ix_watchlist_daily_run_date'), table_name='watchlist_daily')
    op.drop_table('watchlist_daily')
    op.drop_index(op.f('ix_screener_runs_run_date'), table_name='screener_runs')
    op.drop_table('screener_runs')
