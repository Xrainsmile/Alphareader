"""Event ORM model — 事件级聚合根（长期方案：从 news 拆出的独立事件表）。

背景（P0-1）：news 同时承载原始报道与事件聚合根（event_* 字段），
且 event_versions.event_id / digest_event_links.event_id 均 ON DELETE CASCADE 指向
news.id。旧的 7 天 cleanup 直接删事件根，会破坏 90 天 Event Memory、拆散长周期事件、
级联删除 Reports 历史链接。

本表把事件状态从 news 拆出为独立生命周期：
- 原始报道（news）保留 7~30 天后可删，事件（events）按 EVENT_MEMORY_LOOKBACK_DAYS 保留。
- news.event_id → events.id；event_versions / digest_event_links 的 event_id 重定向到 events.id，
  删除 news 根不再级联抹掉版本历史与 Reports 链接。

列名去除了 news 上的 event_ 前缀（title=event_title, summary=event_summary, ...），
与 EventVersion 快照字段对齐（无前缀）。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY, BigInteger, DateTime, ForeignKey, Index, Integer, REAL, SmallInteger,
    String, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── 事件包（与 news 旧 event_* 同义，去前缀）──
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_important: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty: Mapped[str | None] = mapped_column(Text, nullable=True)
    watch_next: Mapped[str | None] = mapped_column(Text, nullable=True)

    # new / developing / stable / resolved
    status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # 独立信源数（同一媒体多篇只计 1）
    source_count: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, index=True
    )
    # 报道总数（根 + 全部子报道）
    article_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # 事件版本：初始 1，has_material_update=true 时 +1
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── 事件级排序信号（0-10，纯规则计算）──
    impact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    novelty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urgency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relevance: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── 事件记忆（方案B）语义向量 ──
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(REAL), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── 事件结果记忆（让"历史规律"有据可依）──
    outcome_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    final_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    watch_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    duration_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 重大事件即时提醒去重：已为哪个 version 推送过提醒
    last_alerted_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_events_last_updated_status", "last_updated_at", "status"),
    )
