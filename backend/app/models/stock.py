"""Stock ORM models – daily quotes cache & RS Rating snapshots.

StockDailyQuote: 每日股票前复权行情缓存（A 股 + 美股）
StockRSRating:   RS 相对强度评分快照（IBD/Minervini 方法）

market 字段区分市场：'CN' = A 股, 'US' = 美股。
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
    """每日股票前复权行情缓存。

    支持 A 股和美股：
      - A 股 ts_code: 6 位数字（如 "600519"），数据来源 akshare / 腾讯财经
      - 美股 ts_code: ticker symbol（如 "AAPL"），数据来源 yfinance
    """

    __tablename__ = "stock_daily_quote"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    market: Mapped[str] = mapped_column(
        String(4), nullable=False, default="CN", server_default="CN", index=True
    )  # 'CN' = A 股, 'US' = 美股
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
        Index("ix_quote_market_date", "market", "trade_date"),
    )


class StockRSRating(Base):
    """RS 相对强度评分快照。

    每日计算一次，基于 3/6/9/12 个月加权涨跌幅百分位排名。
    RS_Rating 范围 1-99，99 = 最强。
    """

    __tablename__ = "stock_rs_rating"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    market: Mapped[str] = mapped_column(
        String(4), nullable=False, default="CN", server_default="CN", index=True
    )  # 'CN' = A 股, 'US' = 美股
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
        Index("ix_rs_market_date", "market", "trade_date"),
    )
