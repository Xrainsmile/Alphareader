"""Entity ORM model — 世界线（World Thread）P0 实体层。

把实体从 news.sentiment_entity（单值字符串）升级为独立卡片：
- entities        —— 规范实体卡，永久保留，只增不减
- event_entities  —— 事件-实体关联（带角色），随事件过期级联删除

设计要点：
1. entities 是唯一永久实体；关联表是临时的，用于近线聚类。
2. 聚类依赖事件存在期内的关联，事件过期后 mention_count 不回退，
   实体卡仍然留存（这正是"永久"的含义）。
3. is_generic 标记泛化实体（美国/市场/行业），P1 聚类时不参与 Jaccard 主判定。
4. 与 news.sentiment_entity 并存不替换：后者服务 A 股单值标的上游，
   前者服务世界线的多值可关联需求。两者语义不同。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY, Boolean, DateTime, ForeignKey, Index, Integer, REAL,
    SmallInteger, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 规范名（别名归一后）：胡塞武装
    canonical_name: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    # org 机构 / person 人物 / place 地点 / asset 资产 / commodity 商品 / concept 概念
    entity_type: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    # 别名表：胡塞 / Houthi / 安拉拥护者
    aliases: Mapped[list[str] | None] = mapped_column(ARRAY(String(128)), nullable=True)
    # 仅新实体判定用（P0 阶段可不填，留 P1 聚类时用）
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(REAL), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 累计提及次数，永不回退
    mention_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # 泛化实体不参与聚类主判定
    is_generic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EventEntity(Base):
    __tablename__ = "event_entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    # subject 动作发起方 / target 承受方 / stake 争夺标的 / asset 受袭资产 / location 地点
    # 注意：这是「实体级」角色，与 thread_events.role（线级：事件在线中的作用）不同义
    role: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # 1=次要提及 2=核心实体（P1 聚类时核心实体加权 3x）
    weight: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("event_id", "entity_id", name="uq_event_entity"),
        Index("ix_event_entities_entity", "entity_id"),
    )
