"""统计数据模型 — 用户行为 + Pipeline 运行记录。

SQLAlchemy 2.0 Mapped 风格，与项目其他模型保持一致。
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnalyticsDaily(Base):
    """每日聚合统计表 — 存储用户行为的按日聚合数据。

    metric 类型：
      - page_view: 页面访问量
      - news_click: 新闻点击量
      - news_impression: 新闻曝光量
      - session_duration: 会话总停留秒数

    dimension 说明：
      - "_total": 全局总量
      - news UUID: 具体新闻条目的统计
    """
    __tablename__ = "analytics_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    dimension: Mapped[str] = mapped_column(String(200), nullable=False, default="_total")
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("date", "metric", "dimension", name="uq_analytics_daily"),
    )


class PipelineRun(Base):
    """Pipeline 运行记录表 — 每次 Pipeline 执行后写入一条。"""
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    total_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    after_dedup: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    after_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    by_source: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    score_distribution: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    errors: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
