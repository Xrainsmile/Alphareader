"""digest_event_links 表（跨简报对比机制）

简报生成时记录收录的 (event_id, event_version, section, rank)，
下一份简报据此做版本对比：version > 上次才算有新变化，
避免连续简报重复讲同一事件，并支撑 ongoing_updates/quiet_topics。

Revision ID: x6y7z8a9b0c1
Revises: w5x6y7z8a9b0
Create Date: 2026-08-02
"""

from alembic import op

revision = "x6y7z8a9b0c1"
down_revision = "w5x6y7z8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS digest_event_links (
            id SERIAL PRIMARY KEY,
            digest_id INTEGER NOT NULL REFERENCES news_digests(id) ON DELETE CASCADE,
            event_id UUID NOT NULL REFERENCES news(id) ON DELETE CASCADE,
            event_version INTEGER,
            section VARCHAR(24) NOT NULL,
            rank INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_digest_event UNIQUE (digest_id, event_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_digest_event_links_digest_id ON digest_event_links (digest_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_digest_event_links_event_id ON digest_event_links (event_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_digest_event_links_event ON digest_event_links (event_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS digest_event_links")
