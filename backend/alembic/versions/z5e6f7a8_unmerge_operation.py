"""P1c: thread_operations 允许 'unmerge' 操作

撤销合并（POST /threads/unmerge）需要写审计留痕。原 ck_thread_op_operation
白名单只有 pin/unpin/merge/split/remove/move/restore，写 'unmerge' 会被
CHECK 约束拒绝（CheckViolationError → 500）。

★ 为什么必须加白名单而不是复用 'merge'：
  审计表是人工治理的溯源依据。用 'merge' 记撤销会让 /history 无法区分
  「做了什么」和「撤了什么」，审计链当场失真。

幂等：drop + create，重跑结果一致。
"""

import sqlalchemy as sa
from alembic import op

revision = "z5e6f7a8_unmerge_operation"
down_revision = "z4d5e6f7_children_event_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE thread_operations
            DROP CONSTRAINT IF EXISTS ck_thread_op_operation;
    """))
    op.execute(sa.text("""
        ALTER TABLE thread_operations
            ADD CONSTRAINT ck_thread_op_operation
            CHECK (operation IN ('pin','unpin','merge','split','remove',
                                 'move','restore','unmerge'));
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE thread_operations
            DROP CONSTRAINT IF EXISTS ck_thread_op_operation;
    """))
    op.execute(sa.text("""
        ALTER TABLE thread_operations
            ADD CONSTRAINT ck_thread_op_operation
            CHECK (operation IN ('pin','unpin','merge','split','remove',
                                 'move','restore'));
    """))
