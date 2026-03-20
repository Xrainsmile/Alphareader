"""DailyBriefing ORM model – 每日综合分析报告。

融合 VCP/趋势策略白名单 + 行情数据 + 新闻概览 + 模拟仓状态，
由 DeepSeek 生成包含交易建议的 Markdown 分析报告。

每天最多一条（盘后生成），唯一约束 briefing_date。
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyBriefing(Base):
    """每日综合分析报告 — 盘后自动生成。

    content: DeepSeek 生成的 Markdown 分析报告（含交易建议）
    meta:    JSONB 存放策略统计概要（不传给 AI，仅前端展示用）
    """

    __tablename__ = "daily_briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 报告日期（一天一条）
    briefing_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # 报告内容（Markdown）
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 策略统计概要（前端侧边栏/卡片展示用）
    # 例如: {"vcp_count": 5, "trend_count": 8, "value_count": 3, "news_digests": 2}
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 喂给 AI 的 prompt token 估算（便于监控成本）
    prompt_tokens_est: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 生成耗时（秒）
    generation_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # 状态：ok / failed / empty（无可用数据时跳过）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("briefing_date", name="uq_briefing_date"),
        Index("ix_briefing_date_desc", briefing_date.desc()),
    )
