"""创建 news_catalyst_stocks 表的迁移脚本。

在服务器上执行：
  cd /home/Alphareader
  docker compose exec web python3 -m app.scripts.migrate_catalyst
"""

import asyncio
import logging
import sys

# 确保能从 backend 目录 import
sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def migrate():
    from sqlalchemy import text
    from app.database import engine

    DDL = """
    CREATE TABLE IF NOT EXISTS news_catalyst_stocks (
        id              SERIAL PRIMARY KEY,
        catalyst_date   DATE NOT NULL,
        ts_code         VARCHAR(10) NOT NULL,
        name            VARCHAR(32),
        news_count      INTEGER NOT NULL DEFAULT 1,
        top_score       SMALLINT NOT NULL DEFAULT 0,
        avg_score       FLOAT NOT NULL DEFAULT 0.0,
        catalyst_types  VARCHAR[],
        catalyst_summary TEXT,
        avg_sentiment   FLOAT,
        news_titles     VARCHAR[],
        in_vcp          BOOLEAN DEFAULT FALSE,
        vcp_score       FLOAT,
        in_trend        BOOLEAN DEFAULT FALSE,
        trend_score     FLOAT,
        rs_rating       SMALLINT,
        heat_score      FLOAT NOT NULL DEFAULT 0.0,
        confirm_level   VARCHAR(20) NOT NULL DEFAULT 'catalyst_only',
        created_at      TIMESTAMPTZ DEFAULT NOW()
    );

    -- 唯一约束
    DO $$ BEGIN
        ALTER TABLE news_catalyst_stocks
            ADD CONSTRAINT uq_catalyst_date_code UNIQUE (catalyst_date, ts_code);
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END $$;

    -- 索引
    CREATE INDEX IF NOT EXISTS ix_catalyst_date_heat
        ON news_catalyst_stocks (catalyst_date, heat_score DESC);
    CREATE INDEX IF NOT EXISTS ix_catalyst_confirm
        ON news_catalyst_stocks (catalyst_date, confirm_level);
    CREATE INDEX IF NOT EXISTS ix_catalyst_ts_code
        ON news_catalyst_stocks (ts_code);
    CREATE INDEX IF NOT EXISTS ix_catalyst_date
        ON news_catalyst_stocks (catalyst_date);
    """

    async with engine.begin() as conn:
        await conn.execute(text(DDL))

    logger.info("✅ news_catalyst_stocks table created / verified successfully")


if __name__ == "__main__":
    asyncio.run(migrate())
