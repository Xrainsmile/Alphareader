"""News ORM model – the core data entity of AlphaReader."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class News(Base):
    __tablename__ = "news"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="财经", server_default="财经", index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ai_score: Mapped[int] = mapped_column(Integer, nullable=True, default=0, index=True)
    ai_summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    # 事件聚合：指向同一事件的更早报道（自引用外键），前端可据此折叠关联新闻
    related_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("news.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sentiment_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    surprise_factor: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    catalyst_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sentiment_entity: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sentiment_reasoning: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Full-text search vector: auto-populated by DB trigger
    # 'simple' config works well for both Chinese and English (unigram tokenization)
    search_vector = Column(TSVECTOR, nullable=True)

    # ── Composite Indexes for query performance ──
    __table_args__ = (
        # Primary query pattern: today's top news
        Index("ix_news_created_score", created_at.desc(), ai_score.desc()),
        # Source + score filtering
        Index("ix_news_source_score", "source", ai_score.desc()),
        # GIN index for full-text search
        Index("ix_news_search_vector", "search_vector", postgresql_using="gin"),
        # GIN index for ARRAY tags filtering (e.g., tags @> ARRAY['sector'])
        Index("ix_news_tags", "tags", postgresql_using="gin"),
    )
