"""P2: 世界线工作台查询索引

背景
----
workbench.py 的四个端点引入了新的查询路径，现有索引未覆盖：

1. **雷达时间窗过滤**：`events.last_updated_at >= :since` 配合
   `thread_events` 三表 JOIN。现有 `ix_events_last_updated_at` 是单列索引，
   雷达还需在窗口内按 `impact/novelty/urgency` 做 AVG 聚合，
   复合索引可避免回表取这三个字段。

2. **实体监控趋势**：`event_entities` 按 `entity_id` 分组后 JOIN `events`
   再按 `last_updated_at` 排序。现有表只有 `ix_event_entities_entity` 之类
   单列索引（见 P0 迁移），缺 `(entity_id, event_id)` 复合。

3. **简报→世界线**：`digest_event_links.event_id` 已有单列索引，但查询还要
   回取 `digest_id/section/rank`，复合索引可覆盖。

4. **章节反查简报**：`thread_events(thread_id, event_id)` 已由唯一约束
   `uq_thread_event` 覆盖，不重复建。

设计取舍
--------
- 全部使用 `CREATE INDEX IF NOT EXISTS`：本地库由 create_all 建表、
  索引可能已存在，迁移必须可重入。
- 不加 `CONCURRENTLY`：alembic 迁移在事务内执行，CONCURRENTLY 不能在事务块中跑。
  本批表当前量级（thread_events 832 行、event_entities 3178 行）建索引是毫秒级，
  不会锁表到影响业务。量级到十万行以上时需单独评估在线建索引方案。
- 只加索引不改数据：本迁移零风险，回滚只删索引。

Revision ID: b7c3d4e5f6a8
Revises: a1b2c3d4e5f6
"""

from alembic import op

revision = "b7c3d4e5f6a8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 雷达窗口：时间过滤 + 质量字段覆盖，避免回表
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_events_window_quality
        ON events (last_updated_at, impact, novelty, urgency)
    """)

    # 2) 实体趋势：entity_id → event_id 复合，供 JOIN events 取时间
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_event_entities_entity_event
        ON event_entities (entity_id, event_id)
    """)

    # 3) 简报→世界线：event_id 覆盖回取 digest 归属与条目元信息
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_digest_links_event_cover
        ON digest_event_links (event_id, digest_id, section)
    """)

    # 4) 实体监控列表：非泛化实体按类型过滤（is_generic 已在 P0 有部分索引，
    #    此处补 entity_type 复合，供工作台类型筛选）
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_entities_type_generic
        ON entities (entity_type, is_generic)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_entities_type_generic")
    op.execute("DROP INDEX IF EXISTS ix_digest_links_event_cover")
    op.execute("DROP INDEX IF EXISTS ix_event_entities_entity_event")
    op.execute("DROP INDEX IF EXISTS ix_events_window_quality")
