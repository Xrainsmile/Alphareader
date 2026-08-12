"""P1b: 回填 events 行 + 设置 news.event_id（长期方案数据迁移）

将现有事件根（news.related_to_id IS NULL AND event_title IS NOT NULL）转为独立的
events 行，并把 news.event_id 指向对应事件：

- events.id **复用** news 根 id。因此 event_versions.event_id / digest_event_links.event_id
  当前值（=新闻根 id）天然就是新建 events 行的 id，P2 只需把这两张表的 FK 目标从
  news.id 改成 events.id（值无需变更），删除 news 根不再级联抹掉版本/链接。
- news.event_id：根自身 = 其 id；任意深度的子报道沿 related_to_id 上溯到合格根后设置。
- article_count / source_count 用精确计数回填（不依赖可能陈旧的 event_article_count）。
- 幂等：events INSERT ON CONFLICT DO NOTHING；news.event_id 重设为根 id，可重跑。

⚠️ 部署前置：本迁移依赖 P1a（z1a2b3c4_events_table）已应用，即 4 个旧分支头都已合并。
   部署前须在 prod 跑 `alembic heads`，确认只输出 `z1a2b3c4_events_table` 一个 head。
"""

import sqlalchemy as sa
from alembic import op

revision = "z2b3c4d5_events_backfill"
down_revision = "z1a2b3c4_events_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 建 events 行（复用 news 根 id；字段去 event_ 前缀映射）
    op.execute(sa.text("""
        INSERT INTO events (
            id, title, summary, latest_change, why_important, uncertainty,
            watch_next, status, first_seen_at, last_updated_at,
            version, impact, novelty, urgency, confidence, relevance,
            embedding, embedding_model,
            outcome_type, final_outcome, watch_result, resolved_at, duration_hours,
            last_alerted_version, created_at
        )
        SELECT
            id, event_title, event_summary, event_latest_change, event_why_important, event_uncertainty,
            event_watch_next, event_status, event_first_seen_at, event_last_updated_at,
            event_version, event_impact, event_novelty, event_urgency, event_confidence, event_relevance,
            event_embedding, event_embedding_model,
            event_outcome_type, event_final_outcome, event_watch_result, event_resolved_at, event_duration_hours,
            event_last_alerted_version, COALESCE(created_at, now())
        FROM news
        WHERE related_to_id IS NULL
          AND event_title IS NOT NULL
        ON CONFLICT (id) DO NOTHING
    """))

    # 2. 精确计数回填 article_count / source_count（根 + 全部子报道）
    op.execute(sa.text("""
        UPDATE events e SET
            article_count = 1 + COALESCE((
                SELECT COUNT(*) FROM news n WHERE n.related_to_id = e.id
            ), 0),
            source_count = (
                SELECT COUNT(DISTINCT n.source) FROM news n
                WHERE n.id = e.id OR n.related_to_id = e.id
            )
    """))

    # 3. 根自身 event_id = 其 id
    op.execute(sa.text("""
        UPDATE news SET event_id = id
        WHERE related_to_id IS NULL AND event_title IS NOT NULL
    """))

    # 4. 子报道 event_id = 最终事件根（递归上溯，兼容历史链式 related_to_id 残留）
    #    up 沿 related_to_id 逐级向上，最终一跳的 parent_id 即合格事件根。
    op.execute(sa.text("""
        WITH RECURSIVE up AS (
            SELECT id AS child_id, related_to_id AS parent_id
            FROM news
            WHERE related_to_id IS NOT NULL
            UNION ALL
            SELECT up.child_id, n.related_to_id
            FROM up
            JOIN news n ON n.id = up.parent_id
            WHERE n.related_to_id IS NOT NULL
        )
        UPDATE news x SET event_id = up.parent_id
        FROM up
        WHERE x.id = up.child_id
          AND up.parent_id IN (
              SELECT id FROM news
              WHERE related_to_id IS NULL AND event_title IS NOT NULL
          )
    """))


def downgrade() -> None:
    # 撤销回填：先清空 news.event_id（SET NULL，不级联），再清空 events（此时
    # event_versions/digest_event_links 的 FK 目标仍是 news.id，删 events 不受影响）。
    op.execute(sa.text("UPDATE news SET event_id = NULL"))
    op.execute(sa.text("DELETE FROM events"))
