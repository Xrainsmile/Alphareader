"""SEPA 模拟盘训练系统 ORM models.

覆盖 A股(CN) / 港股(HK) / 美股(US) 三个市场，每个市场独立账户、独立币种、独立 KPI。

四张表：
  - SepaAccount:       模拟账户（每市场一条，记录初始资金/币种）
  - SepaMarketGate:    市场闸门（每市场一条，4 项指标 + 汇总开关）
  - SepaWatchlistItem: 股池候选标的（含 8 条趋势模板逐条判定结果）
  - SepaTrade:         交易记录（一笔完整交易：开仓建记录，平仓补全 exit 字段）

设计说明：
  * 现金 / 市值 / 盈亏 均动态计算，不冗余存储，避免数据不一致（便于重置）。
  * SepaTrade 采用「一笔交易 = 一条记录」模型，最利于纪律 KPI 计算。
  * 现价统一录在 SepaWatchlistItem.price，持仓浮动盈亏从同 market+symbol 关联取价。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
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

# ── 市场常量 ──
SEPA_MARKETS = ("CN", "HK", "US")
SEPA_CURRENCY = {"CN": "CNY", "HK": "HKD", "US": "USD"}
SEPA_CURRENCY_SYMBOL = {"CN": "¥", "HK": "HK$", "US": "$"}
# 各市场默认初始资金（可在账户表中修改）
SEPA_DEFAULT_CAPITAL = {
    "CN": Decimal("300000"),
    "HK": Decimal("300000"),
    "US": Decimal("40000"),
}


class SepaAccount(Base):
    """模拟账户 — 每个市场一条。

    现金 / 市值 / 盈亏均动态计算，本表仅保存初始资金与币种等不变量。
    """

    __tablename__ = "sepa_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(4), nullable=False)  # CN / HK / US
    currency: Mapped[str] = mapped_column(String(4), nullable=False)  # CNY / HKD / USD
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    inception_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("market", name="uq_sepa_account_market"),
    )


class SepaMarketGate(Base):
    """市场闸门 — 每个市场一条最新状态。

    4 项指标全部为 True 时 gate_open=True，否则关闭（禁止开新仓）。
    """

    __tablename__ = "sepa_market_gates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(4), nullable=False)

    # 4 项闸门指标（手册第二章）
    index_above_ma50: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 指数站上50日线
    ma50_trending_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 50日线斜率向上
    breadth_healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 市场宽度（涨跌家数比>1）
    new_highs_gt_lows: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 新高>新低

    gate_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 汇总状态
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("market", name="uq_sepa_gate_market"),
    )


class SepaWatchlistItem(Base):
    """股池候选标的 — 含 8 条趋势模板逐条判定结果。

    status:
      - candidate: 候选（数据未录全或未判定）
      - passed:    8 条全过（✅ 入池，可买入）
      - rejected:  未通过
    """

    __tablename__ = "sepa_watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # ── 趋势模板所需关键数据（手动录入或后续 API 拉取）──
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 现价
    ma50: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma150: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma200: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma200_rising: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 200日线≥1月上升
    high52w: Mapped[float | None] = mapped_column(Float, nullable=True)
    low52w: Mapped[float | None] = mapped_column(Float, nullable=True)
    rs: Mapped[float | None] = mapped_column(Float, nullable=True)  # 相对强度 RS（0-99）

    # ── 8 条模板判定结果 ──
    template_pass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    template_detail: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 逐条 [{no,desc,pass}]

    # ── VCP 形态 & 枢轴 ──
    vcp_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 收缩次数/是否接近枢轴
    pivot_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 枢轴买点
    # VCP 算法自动识别结果（批量回填，可由 refresh-vcp 重写；与人工 vcp_confirmed 互斥独立）
    vcp_auto: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── 基本面加分项（手动标注）──
    fundamental_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # EPS增速/营收加速/催化剂

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("market", "symbol", name="uq_sepa_watch_market_symbol"),
        Index("ix_sepa_watch_market_status", "market", "status"),
    )


class SepaTrade(Base):
    """交易记录 — 一笔完整交易（开仓建记录，平仓补全 exit 字段）。

    status:
      - open:   持仓中
      - closed: 已平仓

    followed_rule 是纪律 KPI 的核心字段：平仓时强制标注「是否按规则止损」。
    """

    __tablename__ = "sepa_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="buy")  # buy（做多）
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open")  # open / closed

    # ── 开仓信息 ──
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)  # 买入金额 = price*shares
    pivot_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 枢轴点
    stop_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)  # 止损价（强制）
    max_risk: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)  # 最大亏损金额
    max_risk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 占账户总资产%
    entry_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    risky_entry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 距枢轴>5%追高放行

    # ── 平仓信息（平仓时填写）──
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 盈亏%
    pnl_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)  # 盈亏金额
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 止损/止盈/趋势坏
    followed_rule: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 是否按规则止损（KPI核心）
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 复盘备注

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_sepa_trade_market_status", "market", "status"),
        Index("ix_sepa_trade_market_entry", "market", "entry_date"),
    )
