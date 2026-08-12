"""P1b-fix: 重跑子报道 event_id 回填（修复 z2 递归 CTE bug）

z2（z2b3c4d5_events_backfill）第 4 步的递归 CTE 把 root 初始化为子报道自身 id
且递归步从未更新，导致「子报道 event_id 回填」恒命中 0 行。生产在 z2 已应用的
情况下 311 条子报道全部 event_id IS NULL，影响：

- news 列表 API LEFT JOIN events（n.event_id）→ 子报道丢失事件归属展示；
- digest_service 同样按 News.event_id 关联事件。

本迁移用修正后的递归 CTE 重跑该 UPDATE（幂等：已正确的行重设为相同值）。
"""

import sqlalchemy as sa
from alembic import op

revision = "z4d5e6f7_children_event_id"
down_revision = "z3c4d5e6_event_fk_redirect"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    # 无法区分「z4 回填的」与「后续运行自然写入的」event_id，不做撤销。
    pass
