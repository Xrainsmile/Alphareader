"""events 表 + news.event_id（长期方案：事件根从 news 拆出）

本迁移同时 **merge 4 个既有分支头**（watchlist / event / reports / market），
解决 `alembic upgrade head` 因多 head 报错的问题。

注意：本迁移仅做加性 DDL，**不改动任何运行时行为**：
- news.event_* 字段保留（过渡期 P1a→P5 仍由 event_synthesizer 写入 news）。
- events 表初始为空，数据回填（建事件行、重定向 event_versions/digest_event_links
  的 event_id 到 events.id）在后续 P1b 迁移完成后部署。
"""

from collections import OrderedDict

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ── merge 4 个分支头 ──
down_revision = [
    "g6h7i8j9k0l1",          # watchlist_extra
    "e5f6a7b8_event_alert_state",  # event alert state
    "fd0f8570cdf0",          # reports table
    "t2u3v4w5x6y7",          # vcp auto to watchlist
]
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. events 表（事件级聚合根）──
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("latest_change", sa.Text(), nullable=True),
        sa.Column("why_important", sa.Text(), nullable=True),
        sa.Column("uncertainty", sa.Text(), nullable=True),
        sa.Column("watch_next", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_count", sa.SmallInteger(), nullable=True),
        sa.Column("article_count", sa.SmallInteger(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("impact", sa.Integer(), nullable=True),
        sa.Column("novelty", sa.Integer(), nullable=True),
        sa.Column("urgency", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("relevance", sa.Integer(), nullable=True),
        sa.Column("embedding", sa.ARRAY(sa.REAL()), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=True),
        sa.Column("outcome_type", sa.String(length=16), nullable=True),
        sa.Column("final_outcome", sa.Text(), nullable=True),
        sa.Column("watch_result", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_hours", sa.Integer(), nullable=True),
        sa.Column("last_alerted_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_status", "events", ["status"])
    op.create_index("ix_events_last_updated_at", "events", ["last_updated_at"])
    op.create_index("ix_events_source_count", "events", ["source_count"])
    op.create_index("ix_events_outcome_type", "events", ["outcome_type"])
    op.create_index("ix_events_resolved_at", "events", ["resolved_at"])
    op.create_index(
        "ix_events_last_updated_status", "events", ["last_updated_at", "status"]
    )

    # ── 2. news.event_id：指向 events.id（SET NULL，删除事件不级联删报道）──
    op.add_column(
        "news",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_news_event_id", "news", "events",
        ["event_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_news_event_id", "news", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_news_event_id", table_name="news")
    op.drop_constraint("fk_news_event_id", "news", type_="foreignkey")
    op.drop_column("news", "event_id")

    op.drop_index("ix_events_last_updated_status", table_name="events")
    op.drop_index("ix_events_resolved_at", table_name="events")
    op.drop_index("ix_events_outcome_type", table_name="events")
    op.drop_index("ix_events_source_count", table_name="events")
    op.drop_index("ix_events_last_updated_at", table_name="events")
    op.drop_index("ix_events_status", table_name="events")
    op.drop_table("events")
