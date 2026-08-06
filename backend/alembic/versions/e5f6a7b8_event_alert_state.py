"""add event_last_alerted_version for major-event instant alert

为「重大事件即时提醒」补去重列：

  - event_last_alerted_version  INTEGER

合成阶段满足（event_version 增加 + ai_score>=8 + 官方/多信源 + latest_change 非空）
时即时推送一条 1-2 条短简讯；本列记录已推送到的 event_version，避免重复推送同一版本。

⚠️ 依赖 d4e5f6a7_event_signals（同工作树内、尚未部署的"事件排序信号"迁移）。
部署时须 `alembic upgrade head` 一并应用。

Revision ID: e5f6a7b8_event_alert_state
Revises: d4e5f6a7_event_signals
Create Date: 2026-08-06
"""

from alembic import op

revision = "e5f6a7b8_event_alert_state"
down_revision = "d4e5f6a7_event_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE news ADD COLUMN IF NOT EXISTS event_last_alerted_version INTEGER"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_last_alerted_version")
