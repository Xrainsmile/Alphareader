"""Sandbox (模拟仓) ORM models.

四张表：
  - SandboxStock:    观察池股票（模拟仓持仓 / 观察标的）
  - SandboxAnalysis: 推演记录（每次分析结论、方向、目标价等）
  - SandboxTrade:    交易记录（买入 / 卖出 / 调仓）
  - SandboxNav:      净值快照（每交易日收盘后计算）
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SandboxStock(Base):
    """观察池股票 — 模拟仓跟踪的标的。

    status:
      - watching: 观察中（尚未建仓）
      - holding:  持仓中
      - exited:   已退出
    """

    __tablename__ = "sandbox_stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="watching"
    )  # watching / holding / exited
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 加入观察池的理由
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("ts_code", name="uq_sandbox_stock_code"),
    )


class SandboxAnalysis(Base):
    """推演记录 — 对某只观察池股票的分析结论。

    direction: bullish / bearish / neutral
    """

    __tablename__ = "sandbox_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    direction: Mapped[str] = mapped_column(
        String(16), nullable=False, default="neutral"
    )  # bullish / bearish / neutral
    summary: Mapped[str] = mapped_column(Text, nullable=False)  # 分析摘要
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # 详细正文(Markdown)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_analysis_stock_created", "stock_id", "created_at"),
    )


class SandboxTrade(Base):
    """交易记录 — 模拟仓的买卖操作。

    action: buy / sell
    """

    __tablename__ = "sandbox_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # buy / sell
    price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)  # 股数
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 交易备注
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_trade_stock_date", "stock_id", "trade_date"),
    )


class SandboxNav(Base):
    """净值快照 — 每交易日收盘后计算一次。

    nav = 总市值 / 初始资金
    初始资金默认 1,000,000（百万虚拟资金）。
    """

    __tablename__ = "sandbox_nav"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_market_value: Mapped[Decimal] = mapped_column(
        Numeric(16, 4), nullable=False
    )  # 持仓总市值
    cash: Mapped[Decimal] = mapped_column(
        Numeric(16, 4), nullable=False
    )  # 剩余现金
    nav: Mapped[float] = mapped_column(Float, nullable=False)  # 单位净值
    total_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0)  # 累计盈亏%
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("trade_date", name="uq_sandbox_nav_date"),
        Index("ix_nav_date", "trade_date"),
    )
