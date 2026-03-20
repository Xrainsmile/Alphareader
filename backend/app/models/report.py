"""Report ORM model – stores daily market review reports (复盘).

Fields align with frontend parseFrontMatter() output:
  sync_id  — unique identifier (markdown filename without .md)
  title    — report title
  date     — report date string "YYYY-MM-DD"
  cover    — cover image URL (Tencent COS)
  summary  — brief description for list page
  content  — raw Markdown body (without Front Matter)
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sync_id: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    cover: Mapped[str | None] = mapped_column(String(2048), nullable=True, default="")
    summary: Mapped[str | None] = mapped_column(String(1024), nullable=True, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Indexes ──
    __table_args__ = (
        # List page: latest reports first
        Index("ix_reports_date_desc", date.desc()),
    )
