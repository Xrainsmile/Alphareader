"""统计数据模型 — 用户行为 + Pipeline 运行记录。"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Column,
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    metric = Column(String(50), nullable=False)
    dimension = Column(String(200), nullable=False, default="_total")
    value = Column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("date", "metric", "dimension", name="uq_analytics_daily"),
    )


class PipelineRun(Base):
    """Pipeline 运行记录表 — 每次 Pipeline 执行后写入一条。"""
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    duration_sec = Column(Float, nullable=False, default=0)
    total_fetched = Column(Integer, nullable=False, default=0)
    after_dedup = Column(Integer, nullable=False, default=0)
    after_score = Column(Integer, nullable=False, default=0)
    stored = Column(Integer, nullable=False, default=0)
    by_source = Column(JSONB, nullable=False, default=dict)
    score_distribution = Column(JSONB, nullable=False, default=dict)
    errors = Column(ARRAY(Text), nullable=False, default=list)
