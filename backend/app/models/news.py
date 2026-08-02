"""News ORM model – the core data entity of AlphaReader."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func
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
    # 推荐理由：一句话告诉用户"为什么该关注这条"，类比 AIHOT 的推荐理由
    why_it_matters: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # P2 ③：两层筛选——由 LLM 显式判定是否为"重点推荐"，前端可据此突出显示
    is_highlight: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
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
    # 方案A 事件中心化：LLM 将「根+关联报道」合成为一张事件卡片（仅写在聚合根上）
    # event_article_count 记录上次合成时的报道总数，新子报道到达后计数变大则触发重新合成
    event_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    event_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_article_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # 事件化新闻扩展字段（事件包：变化/重要性/不确定性/观察点/状态/版本）
    event_latest_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_why_important: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_uncertainty: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_watch_next: Mapped[str | None] = mapped_column(Text, nullable=True)
    # new / developing / stable / resolved
    event_status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    event_first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # 独立信源数（同一媒体多篇只计 1），与报道总数 event_article_count 分开统计
    event_source_count: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, index=True
    )
    # 事件版本：初始 1，has_material_update=true 时 +1（快照见 event_versions 表）
    event_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # P5: 去重指纹——持久化到 DB，评分前加载 7 天历史用于跨天旧闻识别
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    simhash_fingerprint: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # 预筛决策原因：记录该条新闻通过/继承/被拦截的原因，便于影子测试审计与误杀排查
    prefilter_reason: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
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
