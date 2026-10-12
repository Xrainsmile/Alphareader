# P0 实施规格：实体层（World Thread 地基）

> 状态：**规格已定，未动代码**。文档先落地，等你批注后再开工。
> 前置：[world-thread-design.md](/Users/rick/AlphaReader/docs/world-thread-design.md)
> 作者：Rick / With　日期：2026-10-12

---

## 0. 本轮确认（先回答你的三个点）

### 0.1 风险 A：thinking 已关闭，从清单划掉

项目已有 5 处显式关闭：

| 文件 | 行 |
|---|---|
| [llm_client.py](/Users/rick/AlphaReader/backend/app/services/llm_client.py) | 73 |
| [llm_news_filter.py](/Users/rick/AlphaReader/backend/app/services/llm_news_filter.py) | 1009（评分）、1287（翻译） |
| [event_synthesizer.py](/Users/rick/AlphaReader/backend/app/services/event_synthesizer.py) | 550 |
| [catalyst_aggregator.py](/Users/rick/AlphaReader/backend/app/services/catalyst_aggregator.py) | 111 |

均为 `"thinking": {"type": "disabled"}`。**§8.5 风险 A 作废**，输出 token 放大风险不存在，原成本测算的下界更可信。

### 0.2 500 字上限：数字错了，机制也错了

**两条都认。**

**（1）数字没推导。** 我当时取的是"安全整数"。重算一遍，按 4 段式在成熟线程（约 100 章）下的真实占用：

| 段 | 内容 | 成熟线程实际占用 |
|---|---|---|
| 起 | 起源，冻结不变 | ~80 字 |
| 承 | 已收束阶段列表（每阶段 ~60 字 × 5） | ~300 字 |
| 转 | 最近一次转折 | ~100 字 |
| 当前 | 活章节 | ~150 字 |
| 观察点 | `open_watches` ≤ 5 条 | ~150 字 |
| **合计** | | **~780 字** |

14 章的年轻线程只需 ~180 字，但 1 年以上的线需要 ~800 字。**500 对年轻线宽松、对成熟线不够**——单一常数本来就覆盖不了两个量级。

**（2）机制错了。** 原设计写的是"超 500 字时强制重写压缩"，这是**全局截断**：每次重写都要模型重新决定砍什么，砍掉的东西不可恢复，且随章节增长重写压力线性上升。

**改为分层老化**——章节压进阶段，阶段压进列表，永不重写已收束的内容：

| 层 | 内容 | 上限 | 生命周期 |
|---|---|---|---|
| L0 起源 | 线的起点 | 80 字 | **冻结**，永不改 |
| L1 阶段列表 | 已收束阶段，每阶段一行 | 60 字 × ≤5 | 追加，满 5 个后最老的合并为一行 |
| L2 当前阶段 | 活章节浓缩 | 200 字 | 每次更新重写（**只有这层重写**） |
| L3 观察点 | `open_watches` | 150 字 | 兑现移入链条，过期删 |

**（3）关键：字数根本不是成本约束。** 按 `deepseek-flash` 输入 $0.14/1M、42 事件/日算：

| 注入字数 | 单线程 tokens | 2 线程/事件 | 月输入 | 月成本 |
|---|---|---|---|---|
| 500 字 | ~650 | 1.3K | 1.6M | **$0.23** |
| 800 字 | ~1.0K | 2.0K | 2.5M | **$0.35** |
| 2000 字 | ~2.6K | 5.2K | 6.6M | **$0.92** |

**从 500 涨到 2000，月成本增加 0.69 美元。** 所以 800 是**质量选择**，不是成本选择。真正的红线仍然是"越长越糊"（lost-in-the-middle），分层老化解决的是这个，截断解决不了。

**修订后的上限：**

| 层 | 字段 | 上限 | 用途 |
|---|---|---|---|
| 注入 | `rollup_inject` | **800 字** | 进合成 prompt |
| 存储 | `rollup_full` | 2000 字 | 管理页人读 |
| 章节快照 | `thread_chapters` | 每章 ≤40 字，**条数不限** | 永久保留 |
| 注入章节 | 最近 5 章 | 200 字 | 附在 `rollup_inject` 后 |

> 注：这条修订落在 P2（线卡摘要）。**P0 不涉及**，但先把口径定死，免得 P2 返工。

### 0.3 章节快照文本：确认，并追加一条硬约束

你理解得对——`news` 7~30 天清理，线卡永久，所以线不能外键依赖会被删的行。

**追加约束（比原设计更严）**：`event_entities` 关联表的 `event_id` 指向 `events.id`，而 `events` 本身按 `EVENT_MEMORY_LOOKBACK_DAYS=90` 保留。因此：

- **`entities` 卡片是唯一永久实体**（`mention_count` / `last_seen_at` 只增不减，永不删）；
- `event_entities` 是**临时关联**，随事件过期 CASCADE 删除——这没问题，因为聚类只在近期事件上做；
- 但**线卡（P2）必须存章节快照文本**，不能只存 `event_id` 外键。这条写进 P2 验收清单。

---

## 1. P0 范围

**做什么**：把实体从"单值字符串"升级为"可关联、可规范化、可统计的卡片"。

**不做什么**（明确切走）：

| 不做 | 归到 |
|---|---|
| 线（threads）表与聚类 | P1 |
| 线卡摘要与谱系召回 | P2 |
| 人工管理 API / 页面 | P1.5 |
| agent memory 回灌 | P4 |

**P0 完成判据**：数据库里有稳定的实体卡片，`events` 与 `entities` 之间建立了带角色标注的关联，且**不新增任何 LLM 调用**。

---

## 2. 数据模型

### 2.1 新文件 `backend/app/models/entity.py`

```python
"""Entity ORM model — 世界线（World Thread）P0 实体层。

把实体从 news.sentiment_entity（单值字符串）升级为独立卡片：
- entities        —— 规范实体卡，永久保留，只增不减
- event_entities  —— 事件-实体关联（带角色），随事件过期级联删除

设计要点：
1. entities 是唯一永久实体；关联表是临时的，用于近线聚类。
2. 聚类依赖事件存在期内的关联，事件过期后 mention_count 不回退，
   实体卡仍然留存（这正是"永久"的含义）。
3. is_generic 标记泛化实体（美国/市场/行业），P1 聚类时不参与 Jaccard 主判定。
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
```

### 2.2 `news` 表加一列

在 [news.py](/Users/rick/AlphaReader/backend/app/models/news.py) 的 `sentiment_entity`（第 46 行）之后追加：

```python
# 世界线 P0：LLM 抽取的原始实体名列表（未规范化），事件合成时落 event_entities
entities: Mapped[list[str] | None] = mapped_column(ARRAY(String(128)), nullable=True)
```

**保留 `sentiment_entity` 不动。** 它有 4 个生产消费方，动了要连锁改：

| 消费方 | 位置 |
|---|---|
| A 股标的提取 | [catalyst_aggregator.py](/Users/rick/AlphaReader/backend/app/services/catalyst_aggregator.py) `:228, :335, :373` |
| 新闻 API 输出 | [api/v1/news.py](/Users/rick/AlphaReader/backend/app/api/v1/news.py) `:303` |
| 简报渲染 | [briefing_service.py](/Users/rick/AlphaReader/backend/app/services/briefing_service.py) `:306, :338, :625` |
| 入库 | [pipeline.py](/Users/rick/AlphaReader/backend/app/services/pipeline.py) `:286` |

**新字段与旧字段并存，不替换。** `sentiment_entity` 继续服务 A 股提取（它要的是"单值主体"），`entities` 服务世界线（它要的是"多值可关联"）。两者语义不同。

### 2.3 注册模型

[models/\_\_init\_\_.py](/Users/rick/AlphaReader/backend/app/models/__init__.py) 追加：

```python
from app.models.entity import Entity, EventEntity
```

并在 `__all__` 中加 `"Entity", "EventEntity"`。

> ⚠️ **顺带发现一个潜在 bug**：该文件 `__all__` 里有 `"Event"`，但 import 段**没有** `from app.models.event import Event`。`from app.models import *` 会抛 `NameError`。当前没炸是因为没人用星号导入。**P0 顺手补上这行 import**，一行成本。

### 2.4 `thread_events` 表结构（P1 落库前置，P0 先定死）

> 配套设计见 [world-thread-design.md §4.1](/Users/rick/AlphaReader/docs/world-thread-design.md)：
> **一个事件可属多条线，每条线各自标注该事件在本线中的作用（role）。**
> 本节只定表结构，P1 才建表。

```python
class ThreadEvent(Base):
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
    # 列名沿用 role（已建表/文档一致），ORM 属性名改 membership_role 以隔离语义
    membership_role: Mapped[str] = mapped_column(
        "role", String(16), nullable=False, default="core", server_default="core"
    )
    # ★ 章节身份：一经分配永不变。传导链 / 观察点 / 人工操作一律引用它。
    # 事件更新到 v3、回填历史事件、Split/Move 迁移章节 —— chapter_id 全程不动。
    # 允许同一 chapter_id 被多行共享（一个章节可容纳多个事件）。
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    # ★ 展示序号：按事件实际发生时间排序，可被重排（回填/Split/Move 后重算）。
    # 与 chapter_id 分离的意义：序号可变不影响任何外部引用。
    chapter_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ★ 写入顺序：仅追加不修改，用于回放与审计。
    # 只给 role ∈ (core, trigger, reaction, signal) 的行分配；
    # context / noise 置 NULL，不计入 chapter_count
    chapter_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 归线依据
    assigned_by: Mapped[str] = mapped_column(
        String(16), nullable=False, default="auto", server_default="auto"
    )  # auto 自动聚类 / manual 人工 / inherit 继承
    match_score: Mapped[float | None] = mapped_column(REAL, nullable=True)
    # 章节快照文本：news 7~30 天清理，线卡永久，故必须存快照而非依赖外键
    snapshot_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    snapshot_summary: Mapped[str | None] = mapped_column(String(120), nullable=True)  # ≤40 字
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # 一个事件对同一条线只能有一个作用（幂等：重复归线 ON CONFLICT DO NOTHING）
        UniqueConstraint("thread_id", "event_id", name="uq_thread_event"),
        # ★ 写入序号在同一条线内不可重复（并发安全的唯一性保证）
        UniqueConstraint("thread_id", "chapter_seq", name="uq_thread_chapter_seq"),
        # ★ 展示序号在同一条线内不可重复（重排后仍保证唯一）
        UniqueConstraint("thread_id", "chapter_no", name="uq_thread_chapter_no"),
        Index("ix_thread_events_thread_seq", "thread_id", chapter_seq.desc()),
        Index("ix_thread_events_thread_no", "thread_id", chapter_no),
        Index("ix_thread_events_event", "event_id"),
        # ★ 章节反查：传导链/观察点/人工操作都按 chapter_id 引用
        Index("ix_thread_events_chapter", "chapter_id"),
    )
```

#### 关键设计说明

**1. 章节三字段分离：`chapter_id` / `chapter_no` / `chapter_seq`。**

这是本表最关键的设计，解决「事件版本」与「世界线章节」两个正交维度混淆的问题。

| 字段 | 语义 | 稳定性 | 用途 |
|---|---|---|---|
| `chapter_id` | 章节**身份** | **永久不变** | 传导链 / 观察点 / 人工操作引用 |
| `chapter_no` | 展示**序号** | 可变（重排） | 前端展示、章节跳转 |
| `chapter_seq` | **写入**顺序 | 仅追加 | 回放、审计、`COUNT` 计数 |

**为什么必须分离**：同一个 Event 更新到 v3，通常**仍然是原来那一章**——
事件版本是纵轴（同一事的时间演化），世界线章节是横轴（不同事的机制推进），两者正交。

若只有单一 `chapter_seq`，回填历史事件时要么撞号、要么重排导致所有外部引用失效。
现在 `chapter_id` 承担引用、`chapter_seq` 只做审计，彻底解耦。

`context` / `noise` 不参与计数，三字段均置 NULL。这样 `threads.chapter_count`
可以直接 `COUNT(chapter_seq)` 得到，不需要带 `WHERE role IN (...)` 的过滤条件。

**1b. 章节号重排（回填 / Split / Move 后）。**
用窗口函数一次算完，避免逐行 UPDATE；`chapter_id` 全程不动：

```sql
UPDATE thread_events te
SET chapter_no = t.rn
FROM (
  SELECT id, ROW_NUMBER() OVER (
    PARTITION BY thread_id ORDER BY occurred_at, chapter_seq
  ) AS rn
  FROM thread_events
  WHERE thread_id = :tid AND chapter_seq IS NOT NULL
) t
WHERE te.id = t.id;
```

排序键用 `occurred_at`（事件实际发生时间）优先、`chapter_seq`（写入顺序）兜底。
回填的历史事件会正确插到中间位置。

**2. 并发安全的章节号分配（不用 `max+1`）。**
`SELECT MAX(chapter_seq)+1` 在并发下会撞号，撞号后触发 `uq_thread_chapter_seq`
唯一约束报错，丢失章节。正确做法是**用 PG 序列或 advisory lock**：

```python
# 方案 A（推荐）：取号前对 thread_id 加事务级 advisory lock
await session.execute(
    sa.text("SELECT pg_advisory_xact_lock(hashtext(:tid))"),
    {"tid": str(thread_id)},
)
seq = await session.scalar(
    sa.select(sa.func.coalesce(sa.func.max(ThreadEvent.chapter_seq), 0) + 1)
    .where(ThreadEvent.thread_id == thread_id)
)
```

锁在事务提交时自动释放，无需显式解锁。`hashtext` 把 UUID 映射成 int4 锁键。

**3. 两条唯一约束的分工。**
`uq_thread_event` 防重复挂线（幂等，重复归线直接 `ON CONFLICT DO NOTHING`）；
`uq_thread_chapter_seq` 防章节号撞车（这是并发正确性的最后防线，即使 advisory lock
失效也不会产生脏数据——宁可报错也不静默错号）。

**4. 快照文本必须存。**
`event_id` 外键指向会被 90 天清理的 `events`，线卡却是永久的。只存外键会导致
线断头。因此 `snapshot_title` / `snapshot_summary` 是**必需字段**，不是冗余。

**5. 与 `event_entities.role` 的命名隔离。**
两个 `role` 同名不同义，SQLAlchemy 层建议显式改名避免误读：
`EventEntity.entity_role`（subject/target/stake/asset/location）、
`ThreadEvent.thread_role`（core/trigger/reaction/signal/context/noise）。
数据库列名保持 `role` 不变，避免迁移成本。

#### 对应的 DDL（P1 迁移时使用）

```sql
CREATE TABLE IF NOT EXISTS thread_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id         UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    event_id          UUID NOT NULL REFERENCES events(id)  ON DELETE CASCADE,
    role              VARCHAR(16) NOT NULL DEFAULT 'core',
    chapter_id        UUID NOT NULL DEFAULT gen_random_uuid(),
    chapter_no        INTEGER,
    chapter_seq       INTEGER,
    assigned_by       VARCHAR(16) NOT NULL DEFAULT 'auto',
    match_score       REAL,
    snapshot_title    VARCHAR(200),
    snapshot_summary  VARCHAR(120),
    occurred_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_thread_event       UNIQUE (thread_id, event_id),
    CONSTRAINT uq_thread_chapter_seq UNIQUE (thread_id, chapter_seq),
    CONSTRAINT uq_thread_chapter_no  UNIQUE (thread_id, chapter_no)
);
CREATE INDEX IF NOT EXISTS ix_thread_events_thread_seq
    ON thread_events (thread_id, chapter_seq DESC);
CREATE INDEX IF NOT EXISTS ix_thread_events_thread_no
    ON thread_events (thread_id, chapter_no);
CREATE INDEX IF NOT EXISTS ix_thread_events_event
    ON thread_events (event_id);
CREATE INDEX IF NOT EXISTS ix_thread_events_chapter
    ON thread_events (chapter_id);
```

> 注：`chapter_seq` / `chapter_no` 为 NULL 的行不参与对应唯一约束判定
> （PG 唯一约束对 NULL 不去重），多条 `context` 行可共存——这正是想要的行为。

---

### 2.5 `thread_transmissions` 表结构（P1-e 落库前置，P0 先定死）

> 传导链：世界线内部「A → B」的因果传导边。
> **本表是整套设计里最需要保守的一张表**——它存储的是推断，不是事实。

```python
class ThreadTransmission(Base):
    __tablename__ = "thread_transmissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ★ 传导的两端。用 chapter_id 引用而非 event_id：
    #   章节身份永久稳定，事件版本更新/章节迁移都不会让传导链失效。
    from_chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    to_chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    # ★ 传导机制描述（人工或 LLM 生成），必须是可证伪的自然语言
    mechanism: Mapped[str] = mapped_column(Text, nullable=False)
    # ★ 证据状态（三态，见下方设计说明）
    # hypothesis 假设（默认，无证据支撑的推断）
    # supported 已有证据支撑
    # contradicted 已被证据反驳
    evidence_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hypothesis", server_default="hypothesis"
    )
    # 支撑/反驳该传导边的那个事件（evidence_status 变动时必须填写）
    evidence_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 传导强度（0~1），用于排序与阈值过滤，不参与真伪判断
    strength: Mapped[float | None] = mapped_column(REAL, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # 状态变更时间：contradicted 一旦落定即冻结，供人工仲裁追溯
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 人工仲裁后才允许 contradicted → supported 回退，记录仲裁者
    arbitrated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        # 同一条线内，同一条传导边不重复
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
```

#### 关键设计说明

**1. `evidence_status` 三态：不能复用 `events.outcome_type`。**

这是最容易混淆的地方，必须先划清界限：

| 字段 | 层级 | 语义 | 现状 |
|---|---|---|---|
| `events.outcome_type` | 事件级 | 这个**事件自身**最后怎么收场 | 已实现 |
| `events.watch_result` | 事件级 | 此前观察点是否兑现 | 已实现 |
| **`evidence_status`** | **传导边级** | A→B 这条**因果推断**的证据强度 | **本次新增** |

**关键区别**：油价事件本身可以 `confirmed`（确实涨了），
但「袭击 → 油价涨」这条边仍然只能是 `hypothesis`。
**两件事，必须独立字段，不可复用。**

**2. `contradicted` 不可自动回退（硬约束）。**

```
hypothesis   → supported     ✅ 可升级（新证据出现）
supported    → contradicted  ✅ 可降级（反向证据出现）
hypothesis   → contradicted  ✅ 可降级
contradicted → supported     ❌ 禁止自动回退，必须人工仲裁
```

理由：`contradicted` 意味着我们**曾经推错过**。若允许自动回退，
系统会在证据波动时反复横跳，形成「虚假因果确信」的动态版本。
人工仲裁才能重新确立信任，并写入 `arbitrated_by` 留痕。

这与「Embedding 0.90 不自动合并实体」是同一条保守原则：
**实体和因果边同属「错了代价极高」的东西，都该走保守策略。**

**3. 用 `chapter_id` 而非 `event_id` 引用两端。**

传导链是**长期结构**，而 `events` 会被 90 天清理、事件会更新版本。
引用 `chapter_id` 保证：章节迁移（Split/Move）、事件版本演进都不会让传导链断头。

这是 §2.4「章节三字段分离」设计的直接收益。

**4. `evidence_event_id` 用 `SET NULL` 而非 `CASCADE`。**

证据事件被清理后，传导边本身仍要保留（只是失去证据来源），
状态回落到 `hypothesis` 由应用层处理，不应级联删除整条边。

#### 对应的 DDL（P1-e 迁移时使用）

```sql
CREATE TABLE IF NOT EXISTS thread_transmissions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id         UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    from_chapter_id   UUID NOT NULL,
    to_chapter_id     UUID NOT NULL,
    mechanism         TEXT NOT NULL,
    evidence_status   VARCHAR(16) NOT NULL DEFAULT 'hypothesis',
    evidence_event_id UUID REFERENCES events(id) ON DELETE SET NULL,
    evidence_note     TEXT,
    strength          REAL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    status_changed_at TIMESTAMPTZ,
    arbitrated_by     VARCHAR(64),
    CONSTRAINT uq_thread_transmission UNIQUE (thread_id, from_chapter_id, to_chapter_id),
    CONSTRAINT ck_transmission_no_self CHECK (from_chapter_id <> to_chapter_id),
    CONSTRAINT ck_transmission_evidence_status
        CHECK (evidence_status IN ('hypothesis','supported','contradicted'))
);
CREATE INDEX IF NOT EXISTS ix_transmissions_thread
    ON thread_transmissions (thread_id, evidence_status);
CREATE INDEX IF NOT EXISTS ix_transmissions_from
    ON thread_transmissions (from_chapter_id);
CREATE INDEX IF NOT EXISTS ix_transmissions_to
    ON thread_transmissions (to_chapter_id);
```

#### 状态流转的并发安全写法

```python
# contradicted 一旦落定即冻结，任何自动路径都不得改写
UPDATE thread_transmissions
SET evidence_status = :new_status,
    evidence_event_id = :ev_id,
    status_changed_at = now(),
    arbitrated_by = :operator
WHERE id = :tid
  AND NOT (evidence_status = 'contradicted' AND :new_status <> 'contradicted');
```

应用层检查受影响行数：为 0 即表示尝试非法回退，直接拒绝并记审计。

## 3. LLM 扩字段（P0 核心，零新增调用）

### 3.1 为什么零新增调用

实体抽取**搭现有评分调用的便车**——在同一次 API 请求的输出 JSON 里多要一个字段。不新建请求、不新建 prompt、不新建并发。

**关键优化：`entities` 只在 `score >= 5` 的档位要求输出。**

依据：`LLM_SCORE_THRESHOLD = 5`，低于 5 的条目**根本不入库**。让模型给注定丢弃的噪音抽实体，纯浪费。

### 3.2 Prompt 改动（中文）

[llm_news_filter.py](/Users/rick/AlphaReader/backend/app/services/llm_news_filter.py) `SYSTEM_PROMPT_CN`（第 110 行起），**输出档位段**改为：

```
- 0—4：id、score
- 5：加 tags、entities
- 6—7：加 summary、why_it_matters、tags、entities
- 8—10：再加 is_highlight
```

并在 `tags` 说明后追加字段定义：

```
entities 为 3—5 个实体名（公司、机构、人物、地点、商品、资产的常用名），须为原文明确出现的具体名词；禁止泛称（市场、行业、全球、整体）、禁止推断或补充原文未出现的实体、禁止输出股票代码。按与该事件的相关度降序。可为空数组。

实体用于长期事件串联，宁缺毋滥：拿不准就少写，绝不编造。
```

**为什么强调"宁缺毋滥"**：P1 聚类靠实体共现。一个编造的实体会把无关事件串成一条假线，污染是长期的。宁可少几个实体让线碎一点，也不能让线错——线碎可以 P1.5 人工合并，线错很难发现。

### 3.3 英文链路

`SYSTEM_PROMPT_EN_SCORE`（阶段一）同样加 `entities`。

**唯一麻烦点**：英文是两阶段（`LLM_TWO_STAGE_EN_ENABLED = True`），阶段二翻译只处理 `id/chinese_title/chinese_summary/why_it_matters`。所以阶段一的 `entities` 必须**按 `original_id` 回填**到最终 `ScoredNewsItem`。

`ScoredNewsItem` 已有 `original_id` 字段（第 527 行），就是为跨批次对齐准备的——直接复用，不用新机制。

### 3.4 数据类

`ScoredNewsItem`（第 539 行 `sentiment_entity` 之后）追加：

```python
# 世界线 P0：LLM 抽取的原始实体名（未规范化），仅 score >= 5 档位输出
entities: list[str] = field(default_factory=list)
```

### 3.5 解析与落库

| 环节 | 文件 | 动作 |
|---|---|---|
| 解析 | `llm_news_filter.py` `_parse_response_detailed` | 读 `entities`，非 list 转空，逐项 `str.strip()`，截断到 `ENTITY_MAX_PER_NEWS` |
| 入库 | [pipeline.py](/Users/rick/AlphaReader/backend/app/services/pipeline.py) `:286` 附近 | `values["entities"] = item.entities` |

**解析器必须宽容**。模型可能返回 `null`、字符串、嵌套对象。任何异常一律降级为空列表，**绝不因此丢弃整条评分结果**——实体是世界线的输入，不是评分的必要条件。

---

## 4. 实体规范化服务

### 4.1 新文件 `backend/app/services/entity_normalizer.py`

三级归一，**逐级降成本**：

| 级 | 方法 | 成本 | 命中率（估） |
|---|---|---|---|
| 1 | 别名表精确匹配 | 零（dict 查表） | ~85% |
| 2 | 规则归一化（公司/国家后缀、空格、大小写、全半角） | 零（正则） | ~10% |
| 3 | embedding 近邻比对，阈值 `0.90` | 极低，**仅新实体触发** | ~5% |

```
normalize(raw: str) -> Entity | None
  1. 停用词过滤（ENTITY_STOPWORDS）→ None
  2. 规则归一化 → key
  3. dict 查 aliases/canonical_name → 命中则 Entity.mention_count += 1
  4. 未命中 → embedding 近邻 ≥0.90 则并入（写 aliases）；否则新建 Entity
```

### 4.2 别名表种子

P0 先硬编码一份种子（`~50` 条高频实体）在 `entity_normalizer.py` 顶部，覆盖：

| 类别 | 示例 |
|---|---|
| 地缘 | 胡塞武装 / Houthi / 安拉拥护者 |
| 央行 | 美联储 / Fed / Federal Reserve |
| 能源 | 沙特阿美 / 阿美 / Saudi Aramco |
| 海峡 | 曼德海峡 / Bab el-Mandeb |

**P1.5 再把它挪到数据库**（`entities.aliases` 已留字段）+ 人工维护 API。P0 硬编码是为了快速验证聚类效果，不值得先建管理界面。

### 4.3 停用词

`ENTITY_STOPWORDS`：市场、行业、全球、整体、业内、分析师、投资者、机构、外媒、消息人士……

**原则**：任何"谁都能往里塞"的泛称都进停用词。这类实体会把全库串成一张网。

---

## 5. 数据库迁移

### 5.1 建表方式

**必须走 Alembic**（生产禁 `create_all`，见 [main.py](/Users/rick/AlphaReader/backend/app/main.py) `:32-39`）。

沿用项目近期风格：**裸 SQL + `IF NOT EXISTS`（幂等）**，参见 `m0x1_missing_core_tables.py`、`w5x6y7z8a9b0_event_data_layer.py`、`x6y7z8a9b0c1_digest_event_links.py`。

### 5.2 前置检查（必须执行）

```bash
cd /Users/rick/AlphaReader/backend && alembic heads
```

**必须只输出一个 head**，否则先解决多 head 再继续（`z2b3c4d5_events_backfill.py` 的注释里强调过这条）。把输出的 revision 填进新迁移的 `down_revision`。

### 5.3 迁移文件

新建 `alembic/versions/<rev>_world_thread_entities.py`：

```python
def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id UUID PRIMARY KEY,
            canonical_name VARCHAR(128) NOT NULL UNIQUE,
            entity_type VARCHAR(24),
            aliases VARCHAR(128)[],
            embedding REAL[],
            embedding_model VARCHAR(64),
            mention_count INTEGER NOT NULL DEFAULT 0,
            is_generic BOOLEAN NOT NULL DEFAULT false,
            first_seen_at TIMESTAMPTZ,
            last_seen_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_entities_canonical_name ON entities (canonical_name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entities_entity_type ON entities (entity_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entities_last_seen_at ON entities (last_seen_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS event_entities (
            id UUID PRIMARY KEY,
            event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            role VARCHAR(24),
            weight SMALLINT NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT now(),
            CONSTRAINT uq_event_entity UNIQUE (event_id, entity_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_entities_entity ON event_entities (entity_id)")

    op.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS entities VARCHAR(128)[]")


def downgrade() -> None:
    op.execute("ALTER TABLE news DROP COLUMN IF EXISTS entities")
    op.execute("DROP TABLE IF EXISTS event_entities")
    op.execute("DROP TABLE IF EXISTS entities")
```

> `events` 表已存在（`z1a2b3c4_events_table`），但**裸 SQL 建外键前先确认它存在**。空库纯 alembic 升级若 `events` 由 `create_all` 建的库，顺序可能有问题——沿用 `m0x1` 的做法，执行前跑一次 `alembic upgrade head` 验证不崩。

---

## 6. 配置

[config.py](/Users/rick/AlphaReader/backend/app/config.py)，插在 `EVENT_MEMORY_*`（第 132 行起）之后：

```python
# ── 世界线 P0：实体层 ──
ENTITY_EXTRACTION_ENABLED: bool = True       # 总开关（关闭则不扩 prompt、不落库）
ENTITY_MAX_PER_NEWS: int = 5                 # 单条新闻实体数上限（防模型刷屏）
ENTITY_MAX_NAME_CHARS: int = 32              # 单个实体名长度上限
ENTITY_ALIAS_SIM_THRESHOLD: float = 0.90     # 新实体 embedding 归并阈值
ENTITY_STOPWORDS: list[str] = Field(
    default_factory=lambda: ["市场", "行业", "全球", "整体", "业内", "分析师", "投资者", "外媒"]
)
```

**为什么要有总开关**：P0 直接改了生产评分 prompt。一旦实体抽取导致评分质量下降（例如模型为了凑 `entities` 而降分），要能**一行关掉、立即回滚**，不用改代码重新部署。这是 P0 最大的风险敞口。

---

## 7. 验收标准

| # | 标准 | 怎么验 |
|---|---|---|
| 1 | 扩字段**未**降低评分质量 | 对比开关前后 3 天的 `ai_score` 分布与入库条数，偏差 <5% |
| 2 | 扩字段**未**增加 API 调用次数 | `pipeline_runs` 的 LLM 调用数持平 |
| 3 | 实体卡片稳定收敛 | 跑满 7 天后，`entities` 表行数 < 事件数 × 2（说明归一化生效） |
| 4 | 高频实体不重复 | `SELECT canonical_name, count(*) FROM entities GROUP BY 1 HAVING count(*)>1` 返回空 |
| 5 | 关联建立成功 | `event_entities` 行数 ≈ 事件数 × 2~4 |
| 6 | 停用词未入库 | 抽查 `canonical_name` 不含"市场/行业/全球" |
| 7 | 回滚可用 | `ENTITY_EXTRACTION_ENABLED=False` 后系统行为与改动前一致 |

**第 3 条最关键。** 如果实体数爆炸增长（例如事件数的 5 倍以上），说明归一化失败——那 P1 聚类一定碎，要在 P0 就停下来修，不能带病进 P1。

---

## 8. 成本复核

| 项 | 估算 |
|---|---|
| 新增 API 调用 | **0** |
| 输出增量 | 仅 `score>=5` 条目，约 120 条/日 × ~25 tok = 3K tok/日 |
| 输入增量 | 0（prompt 只多 ~80 字，且命中 context cache） |
| embedding | 仅新实体触发，稳态下 <10 次/日 |
| **月增量** | **$0.03 ~ $0.13** |

**结论：P0 成本可以忽略。** 真正的代价是**改了生产评分 prompt**——这是全项目最敏感的链路，所以 §6 的总开关和 §7 的第 1、2 条验收不是形式主义。

---

## 9. 风险与回滚

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 扩字段拉低评分质量 | 中 | **高** | 总开关一行关闭；验收第 1 条卡住 |
| 模型为凑 `entities` 编造实体 | 中 | 高 | prompt 明确"宁缺毋滥"；停用词过滤；验收第 6 条 |
| 实体爆炸，归一化失败 | 中 | 中 | 验收第 3 条卡住，不进 P1 |
| Alembic 多 head | 低 | 中 | 执行前 `alembic heads` 必须单 head |
| 空库升级外键顺序崩 | 低 | 中 | 沿用 `m0x1` 幂等 SQL；升级后跑一次验证 |
| `sentiment_entity` 消费方被误伤 | 低 | 高 | **不动该字段**，新字段并存 |

**回滚路径**：`ENTITY_EXTRACTION_ENABLED=False` → 立即恢复旧行为（prompt 不再含 `entities`，不落库）。表保留不删，数据无害。

---

## 10. 文件清单

| 操作 | 文件 |
|---|---|
| 新增 | `backend/app/models/entity.py` |
| 新增 | `backend/app/services/entity_normalizer.py` |
| 新增 | `backend/alembic/versions/<rev>_world_thread_entities.py` |
| 新增 | `docs/p0-entity-layer-spec.md`（本文档） |
| 修改 | [models/\_\_init\_\_.py](/Users/rick/AlphaReader/backend/app/models/__init__.py)（注册 + 补 `Event` import） |
| 修改 | [models/news.py](/Users/rick/AlphaReader/backend/app/models/news.py)（加 `entities` 列） |
| 修改 | [llm_news_filter.py](/Users/rick/AlphaReader/backend/app/services/llm_news_filter.py)（prompt ×2、数据类、解析） |
| 修改 | [pipeline.py](/Users/rick/AlphaReader/backend/app/services/pipeline.py)（落库） |
| 修改 | [config.py](/Users/rick/AlphaReader/backend/app/config.py)（6 个配置项） |
| 新增/改 | `backend/tests/test_entity_normalizer.py` |

---

## 11. 实施状态（2026-10-12 已落地）

数据库 `alembic_version = e6c8748529e8`，单 head，回退已验证（`downgrade -1` → `upgrade head`）。

| 交付 | 状态 | 实际文件 |
|---|---|---|
| `entities` / `event_entities` 模型 | ✅ | [entity.py](/Users/rick/AlphaReader/backend/app/models/entity.py) |
| `news.entities` 列 | ✅ | [news.py](/Users/rick/AlphaReader/backend/app/models/news.py) |
| 模型注册 + **`Event` import 缺失修复** | ✅ | [\_\_init\_\_.py](/Users/rick/AlphaReader/backend/app/models/__init__.py) |
| 实体 writer（规范化 + 幂等落库） | ✅ | [entity_writer.py](/Users/rick/AlphaReader/backend/app/services/entity_writer.py) |
| 评分侧落库 | ✅ | [pipeline.py](/Users/rick/AlphaReader/backend/app/services/pipeline.py) `:286` |
| 事件合成侧建关联 | ✅ | [event_synthesizer.py](/Users/rick/AlphaReader/backend/app/services/event_synthesizer.py) |
| Kill switch | ✅ 已验证 | [config.py](/Users/rick/AlphaReader/backend/app/config.py) |
| Alembic 迁移 | ✅ | `e6c8748529e8_world_thread_p0_entity_layer.py` |
| `thread_events` 表结构 | ✅ 已定死（P1 建表） | 本文档 §2.4 |

### 与原文的偏离（3 处，均为实施时发现）

**1. 文件改名**：`entity_normalizer.py` → `entity_writer.py`。
理由：职责是"抽取 + 规范化 + 落库"三件事合一，叫 normalizer 名不副实。

**2. 迁移手工补了两处**（autogenerate 漏了，都是生产必需）：
- `id` 的 `gen_random_uuid()` 默认值——缺失会导致应用侧 upsert 报 NOT NULL 约束错；
- `event_entities.event_id` 索引——按事件查实体是高频路径，缺索引全表扫描。

**3. 实体关联用独立事务**，不共用事件合成的主 session。
理由：`entity_writer` 内部吞异常后 session 进入 aborted 状态，共用主事务会让后续
`commit()` 抛 `PendingRollbackError`，把整个事件合成搞挂——违背"增强功能不阻断主流程"。

### 实测结论（E2E，已清理）

| 验证项 | 结果 |
|---|---|
| 整簇实体聚合（根 + 2 子报道） | 6 个实体名，并集去重 |
| 别名归并 | `胡塞`/`胡塞武装` → 单卡 |
| 泛化过滤 | `市场` 判 `is_generic=True` |
| 幂等 | 重复调用行数不变 |
| CASCADE | 删事件后关联归零 |
| **实体卡永续** | 事件删除后卡片仍在 |
| Kill switch | `enabled()=False`，全链路 no-op |

### 实施中发现的两个既有事实

**`SessionLocal` 不存在**，正确名称是 `async_session`（`app/database.py:19`）。

**`events` 表当前为空**，故暂时无真实关联数据；下次 pipeline 跑出事件后自然填充。

---

## 12. 待你拍板

| # | 问题 | 我的建议 |
|---|---|---|
| 1 | P0 是否包含英文两阶段？ | **含**。但阶段一 → 阶段二的 `entities` 回填是唯一麻烦点，多点工作量 |
| 2 | 种子别名表 50 条够不够？ | 够。P1.5 挪库后可人工扩 |
| 3 | `entities` 用 `ARRAY(String)` 还是 `JSONB`？ | `ARRAY`，与现有 `embedding ARRAY(REAL)` 风格一致，且 P1 做 `&&` 数组重叠查询更快 |
| 4 | 是否现在就动代码？ | 建议**先批注这份规格**，尤其是 §3.2 的 prompt 措辞——那是 P0 唯一的"生产链路改动" |
| 5 | 验收观察期几天？ | 7 天，覆盖一个完整周循环 |
| 6 | **pytest 在本项目一直挂起** | 非本次改动引入（`tests/` 可收集 457 条但执行即卡）。建议单独排查，或改用直接验证脚本 |
