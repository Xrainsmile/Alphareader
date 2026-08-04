"""add event_embedding to news (事件记忆 / 方案B)

Revision ID: b0c1d2e3_event_embedding
Revises: a9b8c7_prefilter_reason
Create Date: 2026-08-04

为 news 表新增事件语义向量列，支撑「跨周期相似事件召回」：
  - event_embedding        REAL[]      事件包（title+summary）的语义向量，仅聚合根有值
  - event_embedding_model  VARCHAR(64) 生成该向量的 provider/model/dim 标签

不使用 pgvector：向量仅在事件合成时（每轮 ≤10 次）被读取一次做内存余弦，
候选量级几千行，numpy 矩阵乘法足够；避免为 4G 服务器引入扩展与索引常驻内存。
模型或维度变更时 event_embedding_model 不匹配，旧向量自动被忽略并逐步覆盖。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b0c1d2e3_event_embedding"
down_revision = "a9b8c7_prefilter_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news",
        sa.Column("event_embedding", postgresql.ARRAY(sa.REAL), nullable=True),
    )
    op.add_column(
        "news",
        sa.Column("event_embedding_model", sa.String(64), nullable=True),
    )
    # 部分索引：召回时只扫「有向量的聚合根」，避免全表扫描
    op.execute(
        "CREATE INDEX ix_news_event_memory ON news (created_at DESC) "
        "WHERE related_to_id IS NULL AND event_embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_news_event_memory")
    op.drop_column("news", "event_embedding_model")
    op.drop_column("news", "event_embedding")
