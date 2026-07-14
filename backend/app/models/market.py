"""市场适配度相关模型 — 指数日行情 + 策略市场适配度结果。

SQLAlchemy 2.0 Mapped 风格，与项目其他模型保持一致。
market 字段区分市场：'CN' = A 股, 'US' = 美股。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IndexDaily(Base):
    """指数日行情 — 基准指数（沪深300 / 中证1000 / 标普500 / 纳斯达克等）。

    由 index_fetcher 每日采集并 upsert；VCP 市场适配度服务读取基准指数
    序列计算「大盘趋势」与「波动环境」两个维度。

    index_code 约定：
      CN: '000300'(沪深300) / '000852'(中证1000)
      US: '^GSPC'(标普500) / '^IXIC'(纳斯达克)
      （若实时源不可达，可能写入 'SPX_PROXY' 等合成代理，source 字段标记）
    """

    __tablename__ = "index_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    index_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    market: Mapped[str] = mapped_column(
        String(4), nullable=False, default="CN", server_default="CN", index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 数据来源标记：'akshare' / 'yfinance' / 'synthetic'
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        UniqueConstraint("index_code", "trade_date", name="uq_index_daily"),
        Index("ix_index_market_date", "market", "trade_date"),
    )


class MarketAdaptability(Base):
    """策略市场适配度结果 — 每个交易日、每个市场、每个策略一行。

    保存各维度原始值、分数、最终等级、规则版本与 reason_codes，
    满足 PRD 7.3「结果可追溯」：trade_date / 规则版本 / 输入数据版本 /
    各维度原始值 / 分数 / 最终等级 全部落库。
    """

    __tablename__ = "market_adaptability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    market: Mapped[str] = mapped_column(
        String(4), nullable=False, default="CN", server_default="CN", index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # 内部 0-100 总分
    total_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    # 三档等级：favorable / neutral / cautious
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")

    # 五个维度明细：[{key,name,score,max,status,status_label,detail,raw}]
    dimension_scores: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # 触发的原因码：VOLATILITY_SHOCK / BREADTH_DETERIORATING / TREND_BROKEN /
    #              BREAKOUT_FAIL / SAMPLE_INSUFFICIENT / DATA_DELAY ...
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # 结论文案（中文，可解释）
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 规则版本（与 strategy_config.RULE_VERSION 对应）
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # 输入数据版本：所依赖的行情/指数数据日期与来源（用于追溯与降级判断）
    input_data_version: Mapped[str | None] = mapped_column(String(128), nullable=True)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "strategy_id", "market", "trade_date", name="uq_market_adaptability"
        ),
        Index("ix_adapt_market_date", "market", "trade_date"),
    )
