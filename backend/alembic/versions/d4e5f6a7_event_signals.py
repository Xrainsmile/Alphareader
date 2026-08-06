"""add event ranking signal columns to news

为「事件级排序信号」补列，让 News「重要」排序能显式考虑
本轮变化是否重大 / 当前紧迫性 / 是否存在官方确认 / 不确定性 / 用户是否需要行动，
而不再只靠 根新闻 ai_score + 信源加分 + 时间衰减：

  - event_impact     INTEGER   本轮变化是否重大（重要性）
  - event_novelty    INTEGER   本轮变化是否新鲜 / 是否仍在演进
  - event_urgency    INTEGER   当前紧迫性
  - event_confidence INTEGER   确定性（含官方确认 / 多源交叉验证）
  - event_relevance  INTEGER   用户是否需要行动

信号在事件合成时由既有字段 + 程序规则算出（见 app/utils/event_signals.py），
无需额外模型调用。

⚠️ 依赖 c2d3e4f5_event_outcome_memory（同工作树内、尚未部署的"结果记忆"迁移）。
部署时须 `alembic upgrade head` 一并应用两条迁移。

Revision ID: d4e5f6a7_event_signals
Revises: c2d3e4f5_event_outcome_memory
Create Date: 2026-08-06
"""

from alembic import op

revision = "d4e5f6a7_event_signals"
down_revision = "c2d3e4f5_event_outcome_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_impact INTEGER")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_novelty INTEGER")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_urgency INTEGER")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_confidence INTEGER")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_relevance INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_relevance")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_confidence")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_urgency")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_novelty")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_impact")
