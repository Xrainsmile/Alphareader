"""world_thread_p1e_watchpoints

补建 thread_watchpoints（线级观察点）。P1-a 的四张表已建，这张是遗漏的第五张。

★ id 必须带 server_default=gen_random_uuid()：
  ORM 层的 default=uuid.uuid4 只在 ORM 会话内生效，裸 SQL 插入（本模块
  service 层全部用 text() 裸 SQL）不会触发 Python default，会直接撞
  NOT NULL。P1-c 的 thread_route_scores 同样是裸 SQL 插入，已带该默认值。

与传导链的分工：
  传导链   回看，记录「已发生的 A → B」，evidence_status 三态
  观察点   前瞻，声明「下一步看到什么说明线在推进」，status 四态

两套状态语义独立，不可互相推导——观察点被命中不等于它验证的传导边被证实。

Revision ID: 7b1e9f4a2c33
Revises: 93af9caa343e
Create Date: 2026-10-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7b1e9f4a2c33'
down_revision: Union[str, Sequence[str], None] = '93af9caa343e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'thread_watchpoints',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('thread_id', postgresql.UUID(as_uuid=True), nullable=False),
        # 可证伪断言，必填；空串在 DB 层挡住（不可证伪的观察点是噪音源）
        sa.Column('assertion', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False,
                  server_default='trigger'),
        sa.Column('criteria', postgresql.JSONB(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default='open'),
        # 观察点必须有期限，否则无限堆积成噪音
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_event_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['resolved_event_id'], ['events.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('open','hit','missed','expired')",
            name='ck_watchpoint_status',
        ),
        sa.CheckConstraint(
            "kind IN ('trigger','signal','guard','invalidation')",
            name='ck_watchpoint_kind',
        ),
        sa.CheckConstraint(
            "length(btrim(assertion)) > 0",
            name='ck_watchpoint_assertion_not_blank',
        ),
    )
    op.create_index('ix_watchpoints_thread', 'thread_watchpoints',
                    ['thread_id', 'status'], unique=False)
    op.create_index('ix_watchpoints_expires', 'thread_watchpoints',
                    ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_watchpoints_expires', table_name='thread_watchpoints')
    op.drop_index('ix_watchpoints_thread', table_name='thread_watchpoints')
    op.drop_table('thread_watchpoints')
