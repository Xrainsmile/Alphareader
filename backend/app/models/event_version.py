"""EventVersion ORM model – 事件版本历史（事件化新闻的数据层）。

每当事件合成 LLM 判定 has_material_update=true（实质更新）时，
把该版本的事件状态快照写入本表，event_version + 1。
事件详情页的「事件演进」时间线即来源于此表。

仅实质更新才新增版本（重复转述/标题变化不产生版本），
避免版本表被无意义刷新撑大。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, SmallInteger,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EventVersion(Base):
    __tablename__ = "event_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 所属事件（= events.id，P2 起重定向，删除 news 根不再级联抹版本）
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 版本号，从 1 开始，实质更新时 +1
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    # 该版本的事件状态快照（与 news 根行的 event_* 字段同构）
    event_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    event_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_important: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty: Mapped[str | None] = mapped_column(Text, nullable=True)
    watch_next: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    article_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("event_id", "version", name="uq_event_version"),
        Index("ix_event_versions_event_created", "event_id", created_at.desc()),
    )
