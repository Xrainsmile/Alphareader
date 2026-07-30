"""补齐五张核心表的建表迁移（历史插入位：m1m2m3 之前）

背景（底层 review 发现）：
stock_daily_quote / stock_rs_rating / analytics_daily / pipeline_runs /
news_catalyst_stocks 五张表从未有 create_table 迁移，历史上仅靠 dev 环境
main.py 的 create_all 隐式创建；而后续 m1m2m3（ALTER volume/建索引）与
n1n2n3（+market/name 拓宽）直接操作这些表，纯 alembic 空库升级必崩。

本迁移插入在 l1m2n3o4p5q6 之后、m1m2m3 之前，按【当时形态】建表：
  - volume INTEGER（m1m2m3 随后转 BIGINT）
  - name VARCHAR(32)（n1n2n3 随后拓宽为 VARCHAR(128)）
  - 无 market 列（n1n2n3 随后添加）
后续迁移会自然把表演进到当前模型形态。
全部使用 IF NOT EXISTS，对已由 create_all 建过表的库幂等。

Revision ID: m0x1_missing_core_tables
Revises: l1m2n3o4p5q6
Create Date: 2026-07-30
"""

from alembic import op

revision = "m0x1_missing_core_tables"
down_revision = "l1m2n3o4p5q6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── stock_daily_quote（每日股票行情缓存，历史形态）──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_daily_quote (
            id SERIAL PRIMARY KEY,
            ts_code VARCHAR(10) NOT NULL,
            name VARCHAR(32) NOT NULL DEFAULT '',
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            close DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            volume INTEGER,
            amount DOUBLE PRECISION,
            turnover DOUBLE PRECISION,
            amplitude DOUBLE PRECISION,
            pct_change DOUBLE PRECISION,
            change DOUBLE PRECISION,
            created_at TIMESTAMPTZ DEFAULT now(),
            CONSTRAINT uq_quote_code_date UNIQUE (ts_code, trade_date)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_daily_quote_ts_code ON stock_daily_quote (ts_code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_daily_quote_trade_date ON stock_daily_quote (trade_date)")

    # ── stock_rs_rating（RS 相对强度评分快照，历史形态）──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_rs_rating (
            id SERIAL PRIMARY KEY,
            ts_code VARCHAR(10) NOT NULL,
            name VARCHAR(32) NOT NULL DEFAULT '',
            trade_date DATE NOT NULL,
            p3 DOUBLE PRECISION,
            p6 DOUBLE PRECISION,
            p9 DOUBLE PRECISION,
            p12 DOUBLE PRECISION,
            score DOUBLE PRECISION NOT NULL,
            rs_rating INTEGER NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            CONSTRAINT uq_rs_code_date UNIQUE (ts_code, trade_date)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_rs_rating_ts_code ON stock_rs_rating (ts_code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_rs_rating_trade_date ON stock_rs_rating (trade_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rs_date_rating ON stock_rs_rating (trade_date, rs_rating DESC)")

    # ── analytics_daily（每日聚合统计）──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_daily (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            metric VARCHAR(50) NOT NULL,
            dimension VARCHAR(200) NOT NULL DEFAULT '_total',
            value BIGINT NOT NULL DEFAULT 0,
            CONSTRAINT uq_analytics_daily UNIQUE (date, metric, dimension)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_analytics_daily_date ON analytics_daily (date)")

    # ── pipeline_runs（Pipeline 运行记录）──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id SERIAL PRIMARY KEY,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0,
            total_fetched INTEGER NOT NULL DEFAULT 0,
            after_dedup INTEGER NOT NULL DEFAULT 0,
            after_score INTEGER NOT NULL DEFAULT 0,
            stored INTEGER NOT NULL DEFAULT 0,
            by_source JSONB NOT NULL DEFAULT '{}'::jsonb,
            score_distribution JSONB NOT NULL DEFAULT '{}'::jsonb,
            errors TEXT[] NOT NULL DEFAULT '{}'
        )
        """
    )

    # ── news_catalyst_stocks（每日新闻催化标的，历史形态）──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS news_catalyst_stocks (
            id SERIAL PRIMARY KEY,
            catalyst_date DATE NOT NULL,
            ts_code VARCHAR(10) NOT NULL,
            name VARCHAR(32),
            news_count INTEGER NOT NULL DEFAULT 1,
            top_score SMALLINT NOT NULL DEFAULT 0,
            avg_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            catalyst_types VARCHAR[],
            catalyst_summary TEXT,
            avg_sentiment DOUBLE PRECISION,
            news_titles VARCHAR[],
            in_vcp BOOLEAN NOT NULL DEFAULT false,
            vcp_score DOUBLE PRECISION,
            in_trend BOOLEAN NOT NULL DEFAULT false,
            trend_score DOUBLE PRECISION,
            rs_rating SMALLINT,
            heat_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            confirm_level VARCHAR(20) NOT NULL DEFAULT 'catalyst_only',
            created_at TIMESTAMPTZ DEFAULT now(),
            CONSTRAINT uq_catalyst_date_code UNIQUE (catalyst_date, ts_code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_news_catalyst_stocks_catalyst_date ON news_catalyst_stocks (catalyst_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_news_catalyst_stocks_ts_code ON news_catalyst_stocks (ts_code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_catalyst_date_heat ON news_catalyst_stocks (catalyst_date, heat_score DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_catalyst_confirm ON news_catalyst_stocks (catalyst_date, confirm_level)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS news_catalyst_stocks")
    op.execute("DROP TABLE IF EXISTS pipeline_runs")
    op.execute("DROP TABLE IF EXISTS analytics_daily")
    op.execute("DROP TABLE IF EXISTS stock_rs_rating")
    op.execute("DROP TABLE IF EXISTS stock_daily_quote")
