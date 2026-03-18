"""Screener 模型 — 每日白名单 + 运行记录。

SQLAlchemy 2.0 Mapped 风格，与项目其他模型保持一致。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScreenerRun(Base):
    """Screener 运行记录 — 每次 pipeline 执行后写入一条。

    记录运行耗时、各步骤通过数量（漏斗）、错误信息，
    用于前端展示运行历史和排查问题。
    """

    __tablename__ = "screener_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # 漏斗统计
    total_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage2_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fundamental_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 详细统计 JSON（完整的 stats dict，含各子步骤数量）
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # 错误信息
    errors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    # 状态：success / partial（有错误但有结果）/ failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")


class WatchlistDaily(Base):
    """每日白名单 — 每个交易日 screener 筛选出的股票列表。

    每只股票一行，方便 SQL 查询某只股票历史入选情况、
    按日期查询当日白名单等。
    """

    __tablename__ = "watchlist_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    # 股票名称（从 stock_daily_quote 关联）
    name: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 技术面指标
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema20: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema50: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema120: Mapped[float | None] = mapped_column(Float, nullable=True)
    vcp_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 基本面指标
    eps_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_yoy: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 扩展维度 — 行业/题材/主营/资金流向
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    concepts: Mapped[str | None] = mapped_column(String(512), nullable=True)
    main_business: Mapped[str | None] = mapped_column(Text, nullable=True)
    fund_flow_net: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 关联运行记录
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("run_date", "ts_code", name="uq_watchlist_daily"),
    )


class TrendScreenerRun(Base):
    """右侧趋势 Screener 运行记录 — 每次 pipeline 执行后写入一条。

    记录运行耗时、各步骤通过数量（漏斗）、错误信息。
    """

    __tablename__ = "trend_screener_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # 漏斗统计
    total_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trend_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 详细统计 JSON（完整的 stats dict，含各子步骤数量）
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # 错误信息
    errors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    # 状态：success / partial / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")


class TrendWatchlistDaily(Base):
    """右侧趋势每日白名单 — 每个交易日趋势策略筛选出的股票列表。

    每只股票一行，独立于 VCP 的 watchlist_daily 表。
    """

    __tablename__ = "trend_watchlist_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    # 股票名称
    name: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 技术面指标
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma20: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma50: Mapped[float | None] = mapped_column(Float, nullable=True)
    adx: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 扩展维度 — 行业/题材/主营/资金流向
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    concepts: Mapped[str | None] = mapped_column(String(512), nullable=True)
    main_business: Mapped[str | None] = mapped_column(Text, nullable=True)
    fund_flow_net: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 关联运行记录
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("run_date", "ts_code", name="uq_trend_watchlist_daily"),
    )
