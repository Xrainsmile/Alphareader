"""P2: 把 event_versions / digest_event_links 的 event_id FK 从 news.id 重定向到 events.id

P1b 已把 events.id 复用 news 聚合根 id，因此这两张表里的 event_id 值（=原 news 根 id）
天然就是新建 events 行的 id，**数据值无需变更**，本迁移只改约束目标：

- 旧：event_id UUID REFERENCES news(id) ON DELETE CASCADE（自动约束名
  event_versions_event_id_fkey / digest_event_links_event_id_fkey）
  副作用：删除 news 事件根 → 级联抹掉版本历史与 Reports 链接（P0-1 的根因）。
- 新：event_id UUID REFERENCES events(id) ON DELETE CASCADE
  删除 news 根不再级联；删除 events 行才级联清其版本/链接（符合事件生命周期归属）。

防御性清理：加 FK 前删除指向非 events 的孤儿行（P1b 不变量下应为 0，纯安全网）。
"""

from alembic import op
import sqlalchemy as sa

revision = "z3c4d5e6_event_fk_redirect"
down_revision = "z2b3c4d5_events_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0. 防御：清理指向非 events 的孤儿行（P1b 后应为空集）
    op.execute(sa.text(
        "DELETE FROM event_versions WHERE event_id NOT IN (SELECT id FROM events)"
    ))
    op.execute(sa.text(
        "DELETE FROM digest_event_links WHERE event_id NOT IN (SELECT id FROM events)"
    ))

    # 1. event_versions: 旧 FK 自动名 event_versions_event_id_fkey
    op.drop_constraint("event_versions_event_id_fkey", "event_versions", type_="foreignkey")
    op.create_foreign_key(
        "fk_event_versions_event_id", "event_versions", "events",
        ["event_id"], ["id"], ondelete="CASCADE",
    )

    # 2. digest_event_links: 旧 FK 自动名 digest_event_links_event_id_fkey
    op.drop_constraint("digest_event_links_event_id_fkey", "digest_event_links", type_="foreignkey")
    op.create_foreign_key(
        "fk_digest_event_links_event_id", "digest_event_links", "events",
        ["event_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_digest_event_links_event_id", "digest_event_links", type_="foreignkey")
    op.create_foreign_key(
        "fk_digest_event_links_event_id_news", "digest_event_links", "news",
        ["event_id"], ["id"], ondelete="CASCADE",
    )

    op.drop_constraint("fk_event_versions_event_id", "event_versions", type_="foreignkey")
    op.create_foreign_key(
        "fk_event_versions_event_id_news", "event_versions", "news",
        ["event_id"], ["id"], ondelete="CASCADE",
    )
