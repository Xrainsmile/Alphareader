"""催化剂标的模型 — 每日新闻催化剂 × 技术面交叉验证。

存储从高评分新闻中提取的股票标的聚合结果，
以及与 VCP / 趋势白名单的交叉验证状态。
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NewsCatalystStock(Base):
    """每日新闻催化标的 — 从高评分新闻中聚合出的股票标的排行榜。

    核心逻辑：
      - 每条 ai_score >= 7 的新闻，提取其 tags / sentiment_entity 中的股票代码或公司名
      - 按 ts_code 聚合：被多少条高分新闻提及、最高评分、催化剂类型汇总
      - 与当日 VCP / 趋势白名单交叉验证，标记确认状态
    """

    __tablename__ = "news_catalyst_stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalyst_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ts_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    market: Mapped[str] = mapped_column(
        String(4), nullable=False, default="CN", server_default="CN", index=True
    )  # 'CN' = A 股, 'US' = 美股

    # 股票名称
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # 催化剂聚合指标
    news_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    top_score: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    avg_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 催化剂类型汇总（如 ["业绩财报", "产品技术突破"]）
    catalyst_types: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # 催化剂摘要（LLM 生成的一句话总结）
    catalyst_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 情绪分数（聚合后的加权平均，-5 ~ +5）
    avg_sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 关联的原始新闻标题列表（展示用）
    news_titles: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # ── 交叉验证状态 ──
    in_vcp: Mapped[bool] = mapped_column(default=False)
    vcp_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_trend: Mapped[bool] = mapped_column(default=False)
    trend_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rs_rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # 综合催化剂热度（news_count × top_score 加权）
    heat_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 交叉验证分类：
    #   "double_confirmed" — 催化剂 + 技术面双确认（在 VCP 或趋势白名单中）
    #   "strong_rs"        — 催化剂 + RS >= 80
    #   "catalyst_only"    — 有催化剂但技术面未就绪（加入观察池）
    confirm_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="catalyst_only"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("catalyst_date", "ts_code", name="uq_catalyst_date_code"),
        Index("ix_catalyst_date_heat", "catalyst_date", heat_score.desc()),
        Index("ix_catalyst_confirm", "catalyst_date", "confirm_level"),
        Index("ix_catalyst_market_date", "market", "catalyst_date"),
    )
