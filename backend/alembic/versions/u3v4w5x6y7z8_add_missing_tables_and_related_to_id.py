"""news.related_to_id 补列 + 模型对齐索引（链尾）

两项收尾修复（底层 review 发现）：
1. news.related_to_id（事件聚合自引用外键）模型有列但无任何迁移 → 补列+索引。
2. 五张核心表的建表迁移已由 m0x1_missing_core_tables 插入链中补齐；
   本迁移再补 market 单列索引（模型 index=True 期望 ix_<table>_market 命名，
   历史上 n1n2n3 用的是 ix_sdq_market 等手工名），IF NOT EXISTS 幂等。

Revision ID: u3v4w5x6y7z8
Revises: t2u3v4w5x6y7
Create Date: 2026-07-30
"""

from alembic import op

revision = "u3v4w5x6y7z8"
down_revision = "t2u3v4w5x6y7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── news.related_to_id（事件聚合：指向同一事件的更早报道，自引用）──
    op.execute(
        "ALTER TABLE news ADD COLUMN IF NOT EXISTS related_to_id UUID "
        "REFERENCES news(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_news_related_to_id ON news (related_to_id)"
    )

    # ── market 单列索引（模型 index=True 期望的命名，幂等补齐）──
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_daily_quote_market ON stock_daily_quote (market)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_rs_rating_market ON stock_rs_rating (market)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_news_catalyst_stocks_market ON news_catalyst_stocks (market)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_news_catalyst_stocks_market")
    op.execute("DROP INDEX IF EXISTS ix_stock_rs_rating_market")
    op.execute("DROP INDEX IF EXISTS ix_stock_daily_quote_market")
    op.execute("DROP INDEX IF EXISTS ix_news_related_to_id")
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS related_to_id")
