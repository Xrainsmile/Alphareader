"""DigestEventLink ORM model – 简报-事件链接（跨简报对比机制）。

每份结构化简报（schema v2）收录事件时，把 (digest_id, event_id,
event_version, section, rank) 写入本表。生成下一份简报时可据此回答：
  - 该事件上次是否已出现过？
  - 上次讲的是哪个版本？当前版本是否有新增（version > 上次）？
  - 上次位于「必须知道」还是「值得留意」？
从而避免连续四份简报重复讲同一件事，并支撑 ongoing_updates /
quiet_topics / what_changed 的生成。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DigestEventLink(Base):
    __tablename__ = "digest_event_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    digest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news_digests.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # 收录时的事件版本（与 event_versions 对齐；未合成事件为 None）
    event_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # must_know / worth_watching / ongoing_updates
    section: Mapped[str] = mapped_column(String(24), nullable=False)
    # 在 section 内的排序（0 起）
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("digest_id", "event_id", name="uq_digest_event"),
        Index("ix_digest_event_links_event", "event_id", created_at.desc()),
    )
