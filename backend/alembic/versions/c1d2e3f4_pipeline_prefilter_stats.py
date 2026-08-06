"""add prefilter stats to pipeline_runs

Revision ID: c1d2e3f4_pf_stats
Revises: b0c1d2e3_event_embedding
Create Date: 2026-08-06

为 pipeline_runs 表新增 prefilter JSONB 列，持久化每轮预筛统计：
  {shadow, total, drop, inherit, audit, drop_by_reason}

背景：预筛影子测试自上线起只把统计写日志，日志随容器重建丢失，
导致「若启用预筛能省多少 LLM 送评量」这一核心分母始终无法计算。
落库后可直接按时间窗聚合节省率与各子规则的命中分布。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c1d2e3f4_pf_stats"
down_revision = "b0c1d2e3_event_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_runs",
        sa.Column(
            "prefilter",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("pipeline_runs", "prefilter")
