"""add event outcome memory columns to news

为「事件结果记忆」补列，让历史同类事件召回能携带结局信息，
支撑"通常多久落地 / 是否常被证伪"的规律判断：
  - event_outcome_type   VARCHAR(16)   confirmed/reversed/delayed/cancelled/unknown
  - event_final_outcome  TEXT          最终结果摘要
  - event_watch_result   TEXT          此前观察点是否兑现
  - event_resolved_at    TIMESTAMPTZ   结束时间
  - event_duration_hours INTEGER       从首现到结束的小时数

Revision ID: c2d3e4f5_event_outcome_memory
Revises: c1d2e3f4_pf_stats
Create Date: 2026-08-06
"""

from alembic import op

revision = "c2d3e4f5_event_outcome_memory"
down_revision = "c1d2e3f4_pf_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_outcome_type VARCHAR(16)")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_final_outcome TEXT")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_watch_result TEXT")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_resolved_at TIMESTAMPTZ")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_duration_hours INTEGER")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_news_event_outcome_type ON news(event_outcome_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_news_event_resolved_at ON news(event_resolved_at)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_duration_hours")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_resolved_at")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_watch_result")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_final_outcome")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_outcome_type")
