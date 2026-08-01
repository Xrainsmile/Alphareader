"""news 事件合成三列（方案A：事件中心化）

为「多信源聚合成事件卡片」补列（仅写在聚合根 related_to_id IS NULL 的行上）：
1. event_title          — LLM 合成的事件标题（概括事件本质，非任一原标题照抄）
2. event_summary        — LLM 合成的事件综述（核心事实+多方信源信息增量+涉及标的）
3. event_article_count  — 上次合成时基于的报道总数（根+子），
                          用于增量判断：新子报道到达后计数变大则重新合成

Revision ID: v4w5x6y7z8a9
Revises: u3v4w5x6y7z8
Create Date: 2026-08-01
"""

from alembic import op

revision = "v4w5x6y7z8a9"
down_revision = "u3v4w5x6y7z8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_title VARCHAR(512)")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_summary TEXT")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_article_count SMALLINT")


def downgrade() -> None:
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_article_count")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_summary")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS event_title")
