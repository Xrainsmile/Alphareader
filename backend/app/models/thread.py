"""World Thread ORM models — 世界线（World Thread）P1-a 存储层。

四张表（P1-a），按依赖顺序：
- thread_operations   治理审计表（最前建，eligible() 依赖它）
- threads             世界线主卡
- thread_events       事件-线关联（章节三字段分离）
- thread_transmissions 传导链（因果边，evidence_status 三态）

P1-e 补建第五张：
- thread_watchpoints  线级观察点（前瞻，可证伪断言）

设计要点：
1. threads 是主卡，其余全部外键引用它，必须先建。
2. thread_events 的章节三字段分离：chapter_id 永久稳定承担所有外部引用，
   chapter_no 可重排用于展示，chapter_seq 仅追加用于审计。
   事件版本（纵轴）与世界线章节（横轴）正交，故必须分离。
3. thread_transmissions 存的是「推断」不是「事实」，evidence_status 保守：
   contradicted 一旦落定禁止自动回退，必须人工仲裁。
4. thread_operations 是纯审计表，只 INSERT 不 UPDATE 不 DELETE，
   eligible() 通过查询它判断某事件是否被人工排除。
5. thread_watchpoints 与传导链是两种视角：传导链回看（已发生的 A→B），
   观察点前瞻（下一步看什么）。两者的状态字段语义独立，不可混用——
   观察点被命中不等于它验证的传导边被证实。

建表顺序（FK 依赖）：
  thread_operations → threads → thread_events → thread_transmissions
  → thread_watchpoints
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, REAL,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ThreadOperation(Base):
    """治理审计表 —— 只追加，永不修改、永不删除。

    eligible() 通过查询本表判断 (event_id, thread_id) 是否被人工排除，
    因此必须最先建表。每条操作留痕 operator + reason，保证可追溯。
    """

    __tablename__ = "thread_operations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=True,
    )
    # pin / unpin / merge / split / remove / move / restore
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    # 作用域：event 事件级 / thread 线级 / entity 实体级（排除泛化实体用）
    target_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="event", server_default="event"
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 谁做的（人工账号 或 "auto:xxx" 表示自动路径）
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 为什么做 —— 排除规则的命门，缺了 reason 的排除无法回溯
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 操作前后的快照，供回放与调参当 ground truth
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        CheckConstraint(
            "operation IN ('pin','unpin','merge','split','remove','move',"
            "'restore','unmerge')",
            name="ck_thread_op_operation",
        ),
        CheckConstraint(
            "target_type IN ('event','thread','entity')",
            name="ck_thread_op_target_type",
        ),
        # 线级操作历史（/history 端点，会长到上千条，需分页）
        Index("ix_thread_ops_thread_created", "thread_id", "created_at"),
        # eligible() 的排除检查热路径：某事件是否被排除
        Index("ix_thread_ops_target", "target_type", "target_id", "operation"),
    )


class ThreadRouteScore(Base):
    """归线影子表 —— 每对 (event, thread) 一条打分留痕。

    ★ 为什么不复用 thread_operations：
    二者性质完全不同，混在一张表会毁掉治理审计的价值。
      - thread_operations：人工治理事件，稀疏、权威、需长期追溯，/history 端点直接读它
      - thread_route_scores：算法观测数据，每事件×每线一条，量级是治理表的百倍以上

    若把 route 写进 thread_operations，人工治理历史会被噪声淹没，
    且 operation 的 CHECK 约束只有 7 个治理动作，route 不在治理语义内。

    影子期（7 天）结束后，本表用于分布分析：调权重、校准 T_JOIN。
    分析完成可归档清空，不影响任何生产逻辑。

    可清理性：本表无外键，删除不影响其他表；FK 用 ON DELETE CASCADE 仅作兜底。
    """

    __tablename__ = "thread_route_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=True,
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=True,
    )
    # ★ 总分与分项：缺了分项就无法调参——
    #   7 天后只能看到「误判」，却判断不出是 E 偏高还是 M 偏低
    score: Mapped[float | None] = mapped_column(REAL, nullable=True)
    score_entity: Mapped[float | None] = mapped_column(REAL, nullable=True)
    score_mechanism: Mapped[float | None] = mapped_column(REAL, nullable=True)
    score_recency: Mapped[float | None] = mapped_column(REAL, nullable=True)
    # 是否达到 T_JOIN（冗余存储：影子期阈值可能调整，必须记录当时的判定结果）
    joined: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    threshold: Mapped[float | None] = mapped_column(REAL, nullable=True)
    # 是否处于影子模式（非影子时也会留痕，用于对比影子期与生产期的分布漂移）
    shadow: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        # 按事件查所有候选线打分（影子期主查询）
        Index("ix_route_scores_event", "event_id", score.desc()),
        # 按线查历史事件打分（分析某条线的归线质量）
        Index("ix_route_scores_thread", "thread_id", "created_at"),
        # created_at 的索引由 index=True 自动生成（ix_thread_route_scores_created_at），
        # 不额外声明同名不同义的索引，避免重复。
    )


class Thread(Base):
    """世界线主卡。"""

    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 线名：也门-沙特军事对抗 / 红海航运与风险溢价传导
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 争夺标的（stake）：曼德海峡通行权 / 红海航运份额
    contested_asset: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 机制关键词（P1-b 由 LLM 输出 mechanism_hints 填充）
    mechanism_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # embryo 候选(<3章) / active 已确认 / dormant 休眠 / resolved 已收束
    # merged 已合并 / split 已拆分（保留重定向指针）
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="embryo", server_default="embryo", index=True
    )
    # 合并/拆分后的重定向目标，GET 源线时 301 式跳转
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 钉住：走高质量模型 + 提高摘要频次
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 人工锁定的字段，归线算法检测到后不得覆盖
    # {"mechanism_key": "...", "contested_asset": "..."}
    pinned_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 线卡 rollup（4 段式，§7.1），滚动压缩后写入
    rollup: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rollup_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rollup_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 线级 embedding（rollup 向量），用于 semantic_sim 通道
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(REAL), nullable=True)
    # 章节计数：由 thread_events 的 COUNT(chapter_seq) 维护
    chapter_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # 核心实体（影线期统计用），P1-c 填充
    core_entities: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # 最近更新时间，用于 dormant 判定与 recency_bonus
    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('embryo','active','dormant','resolved','merged','split')",
            name="ck_threads_status",
        ),
        Index("ix_threads_status_activity", "status", "last_event_at"),
    )


class ThreadEvent(Base):
    """事件-线关联。一个事件可属多条线，每条线各自标注作用。"""

    __tablename__ = "thread_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ★ 该事件在【这条线】中的作用（线级，与 event_entities.role 实体级不同义）
    # core 核心进展 / trigger 触发因素 / reaction 应对反制
    # signal 指标变化 / context 背景存档 / noise 挂错（人工判定）
    # 默认 core：不确定时偏向可发现性，宁可多一条噪声章节也不让章节静默消失
    # 列名沿用 role，ORM 属性名改 membership_role 以隔离语义
    membership_role: Mapped[str] = mapped_column(
        "role", String(16), nullable=False, default="core", server_default="core"
    )
    # ★ 章节身份：一经分配永不变。传导链/观察点/人工操作一律引用它。
    # 事件更新到 v3、回填历史事件、Split/Move 迁移章节 —— chapter_id 全程不动。
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    # ★ 展示序号：按事件实际发生时间排序，可被重排（回填/Split/Move 后重算）
    chapter_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ★ 写入顺序：仅追加不修改，用于回放与审计。context/noise 置 NULL 不计入
    chapter_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 归线依据：auto 自动聚类 / manual 人工 / inherit 继承
    assigned_by: Mapped[str] = mapped_column(
        String(16), nullable=False, default="auto", server_default="auto"
    )
    match_score: Mapped[float | None] = mapped_column(REAL, nullable=True)
    # 章节快照：events 会被 90 天清理，线卡永久，故必须存快照而非依赖外键
    snapshot_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    snapshot_summary: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # 一个事件对同一条线只能有一个作用（幂等：重复归线 DO NOTHING）
        UniqueConstraint("thread_id", "event_id", name="uq_thread_event"),
        UniqueConstraint("thread_id", "chapter_seq", name="uq_thread_chapter_seq"),
        UniqueConstraint("thread_id", "chapter_no", name="uq_thread_chapter_no"),
        Index("ix_thread_events_thread_seq", "thread_id", chapter_seq.desc()),
        Index("ix_thread_events_thread_no", "thread_id", chapter_no),
        Index("ix_thread_events_event", "event_id"),
        # ★ 章节反查：传导链/观察点/人工操作都按 chapter_id 引用
        Index("ix_thread_events_chapter", "chapter_id"),
    )


class ThreadTransmission(Base):
    """传导链：世界线内部「A → B」的因果传导边。

    ★ 本表存的是「推断」不是「事实」，是整套设计里最需要保守的一张表。
    """

    __tablename__ = "thread_transmissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ★ 用 chapter_id 引用而非 event_id：章节身份永久稳定，
    #   事件版本更新/章节迁移都不会让传导链失效
    from_chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    to_chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    # 传导机制描述（人工或 LLM 生成），必须是可证伪的自然语言
    mechanism: Mapped[str] = mapped_column(Text, nullable=False)
    # ★ 证据状态三态，与 events.outcome_type（事件结局）不可混用：
    #   事件本身可 confirmed，但「袭击→油价涨」这条边仍只能 hypothesis
    evidence_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hypothesis", server_default="hypothesis"
    )
    # 支撑/反驳该传导边的事件（状态变动时必须填写）
    evidence_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 传导强度 0~1，用于排序与阈值过滤，不参与真伪判断
    strength: Mapped[float | None] = mapped_column(REAL, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 人工仲裁后才允许 contradicted → supported 回退，记录仲裁者
    arbitrated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "thread_id", "from_chapter_id", "to_chapter_id",
            name="uq_thread_transmission",
        ),
        CheckConstraint(
            "from_chapter_id <> to_chapter_id", name="ck_transmission_no_self"
        ),
        CheckConstraint(
            "evidence_status IN ('hypothesis','supported','contradicted')",
            name="ck_transmission_evidence_status",
        ),
        Index("ix_transmissions_thread", "thread_id", "evidence_status"),
        Index("ix_transmissions_from", "from_chapter_id"),
        Index("ix_transmissions_to", "to_chapter_id"),
    )


class ThreadWatchpoint(Base):
    """线级观察点：挂在世界线上的「下一个待验证信号」。

    与传导链的职责分工：
    - 传导链  记录「已经发生的 A → B」，回看视角，evidence_status 三态
    - 观察点  声明「接下来看到什么就说明线在推进」，前瞻视角，可证伪

    ★ 观察点必须是可证伪的自然语言断言，不是模糊的「持续关注」。
      「油价突破 100 美元」可证伪；「局势持续紧张」不可证伪，
      后者无论发生什么都能自圆其说，对决策毫无价值。

    ★ status 与传导链的 evidence_status 是两套独立语义，不可混用：
      观察点被「命中」不等于它验证的传导边被「证实」。
      命中只说明预期信号出现了，传导关系仍需独立证据支撑。
    """

    __tablename__ = "thread_watchpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ★ 可证伪的断言文本，必填且不可为空串——不可证伪的观察点没有存在意义
    assertion: Mapped[str] = mapped_column(Text, nullable=False)
    # 观察点类别，用于分组展示与差异化阈值
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="trigger", server_default="trigger"
    )
    # 命中判定的量化口径（可选），JSONB 便于按 kind 扩展不同结构
    criteria: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # ★ 状态机：open → hit / missed / expired
    #   hit/missed 是终态但允许人工 reopen（观察点可能误判或需重新观察）
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open"
    )
    # ★ 到期时间：观察点必须有期限。无期限的观察点等于永远不验证，
    #   会无限堆积成噪音，最终让整张表失去意义
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # 命中/判负时回填的佐证事件
    resolved_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('open','hit','missed','expired')",
            name="ck_watchpoint_status",
        ),
        CheckConstraint(
            "kind IN ('trigger','signal','guard','invalidation')",
            name="ck_watchpoint_kind",
        ),
        # ★ 空断言禁止入库：不可证伪的观察点是噪音源，在数据库层挡住
        CheckConstraint(
            "length(btrim(assertion)) > 0", name="ck_watchpoint_assertion_not_blank"
        ),
        Index("ix_watchpoints_thread", "thread_id", "status"),
        Index("ix_watchpoints_expires", "expires_at"),
    )
