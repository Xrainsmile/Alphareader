"""Stock ORM models – daily quotes cache & RS Rating snapshots.

StockDailyQuote: 每日 A 股前复权行情缓存（替代原 SQLite 方案）
StockRSRating:   RS 相对强度评分快照（IBD/Minervini 方法）
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockDailyQuote(Base):
    """A 股前复权日线行情缓存。

    数据来源：akshare，每日更新一次，用于 RS Rating 计算。
    """

    __tablename__ = "stock_daily_quote"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=True)
    high: Mapped[float] = mapped_column(Float, nullable=True)
    low: Mapped[float] = mapped_column(Float, nullable=True)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=True)
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True)
    amplitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    pct_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_quote_code_date"),
    )


class StockRSRating(Base):
    """RS 相对强度评分快照。

    每日计算一次，基于 3/6/9/12 个月加权涨跌幅百分位排名。
    RS_Rating 范围 1-99，99 = 最强。
    """

    __tablename__ = "stock_rs_rating"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    p3: Mapped[float | None] = mapped_column(Float, nullable=True)
    p6: Mapped[float | None] = mapped_column(Float, nullable=True)
    p9: Mapped[float | None] = mapped_column(Float, nullable=True)
    p12: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rs_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_rs_code_date"),
        Index("ix_rs_date_rating", "trade_date", rs_rating.desc()),
    )
