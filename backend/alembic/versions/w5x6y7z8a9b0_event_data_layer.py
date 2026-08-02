"""事件数据层：news 事件包九列 + event_versions 表 + 简报结构化字段

事件化新闻版本的数据层（PRD 第一阶段）：
1. news 表新增 9 个事件字段（全部 nullable，兼容存量数据）：
   event_latest_change / event_why_important / event_uncertainty /
   event_watch_next / event_status / event_first_seen_at /
   event_last_updated_at / event_source_count / event_version
2. 新建 event_versions 表（事件版本快照，仅实质更新时写入）
3. news_digests 增加 structured_content(JSONB) + schema_version(默认1)
4. 事件列表查询索引：event_status / event_last_updated_at / event_source_count

Revision ID: w5x6y7z8a9b0
Revises: v4w5x6y7z8a9
Create Date: 2026-08-02
"""

from alembic import op

revision = "w5x6y7z8a9b0"
down_revision = "v4w5x6y7z8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. news 事件包字段（幂等）──
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_latest_change TEXT")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_why_important TEXT")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_uncertainty TEXT")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_watch_next TEXT")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_status VARCHAR(16)")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_first_seen_at TIMESTAMPTZ")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_last_updated_at TIMESTAMPTZ")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_source_count SMALLINT")
    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS event_version INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_news_event_status ON news (event_status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_news_event_last_updated_at ON news (event_last_updated_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_news_event_source_count ON news (event_source_count)")

    # ── 2. event_versions 事件版本表 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_versions (
            id SERIAL PRIMARY KEY,
            event_id UUID NOT NULL REFERENCES news(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            event_title VARCHAR(512),
            event_summary TEXT,
            latest_change TEXT,
            why_important TEXT,
            uncertainty TEXT,
            watch_next TEXT,
            status VARCHAR(16),
            source_count SMALLINT,
            article_count SMALLINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_event_version UNIQUE (event_id, version)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_versions_event_id ON event_versions (event_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_versions_event_created ON event_versions (event_id, created_at DESC)")

    # ── 3. news_digests 结构化简报字段 ──
    op.execute("ALTER TABLE news_digests ADD COLUMN IF NOT EXISTS structured_content JSONB")
    op.execute("ALTER TABLE news_digests ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1")


def downgrade() -> None:
    op.execute("ALTER TABLE news_digests DROP COLUMN IF EXISTS schema_version")
    op.execute("ALTER TABLE news_digests DROP COLUMN IF EXISTS structured_content")
    op.execute("DROP TABLE IF EXISTS event_versions")
    op.execute("DROP INDEX IF EXISTS ix_news_event_source_count")
    op.execute("DROP INDEX IF EXISTS ix_news_event_last_updated_at")
    op.execute("DROP INDEX IF EXISTS ix_news_event_status")
    for col in (
        "event_version", "event_source_count", "event_last_updated_at",
        "event_first_seen_at", "event_status", "event_watch_next",
        "event_uncertainty", "event_why_important", "event_latest_change",
    ):
        op.execute(f"ALTER TABLE news DROP COLUMN IF EXISTS {col}")
