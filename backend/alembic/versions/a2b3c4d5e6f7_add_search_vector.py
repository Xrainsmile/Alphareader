"""add search_vector column with GIN index and auto-update trigger

Revision ID: a2b3c4d5e6f7
Revises: fd0f8570cdf0
Create Date: 2026-02-18

Adds:
  - search_vector TSVECTOR column on news table
  - GIN index for fast full-text search
  - Trigger to auto-update search_vector on INSERT/UPDATE
  - Backfill existing rows
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "fd0f8570cdf0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add search_vector column
    op.add_column("news", sa.Column("search_vector", TSVECTOR(), nullable=True))

    # 2. Create GIN index
    op.create_index(
        "ix_news_search_vector",
        "news",
        ["search_vector"],
        postgresql_using="gin",
    )

    # 3. Create trigger function: combine title (weight A) + ai_summary (weight B)
    # Using 'simple' config which works for both Chinese and English
    op.execute("""
        CREATE OR REPLACE FUNCTION news_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('simple', COALESCE(NEW.title, '')), 'A') ||
                setweight(to_tsvector('simple', COALESCE(NEW.ai_summary, '')), 'B');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 4. Create trigger
    op.execute("""
        CREATE TRIGGER trig_news_search_vector
        BEFORE INSERT OR UPDATE OF title, ai_summary
        ON news
        FOR EACH ROW
        EXECUTE FUNCTION news_search_vector_update();
    """)

    # 5. Backfill existing rows
    op.execute("""
        UPDATE news SET search_vector =
            setweight(to_tsvector('simple', COALESCE(title, '')), 'A') ||
            setweight(to_tsvector('simple', COALESCE(ai_summary, '')), 'B');
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trig_news_search_vector ON news;")
    op.execute("DROP FUNCTION IF EXISTS news_search_vector_update();")
    op.drop_index("ix_news_search_vector", table_name="news")
    op.drop_column("news", "search_vector")
