# 世界线最终架构：代码对齐评估

> 评估对象：你提出的「二、推荐的最终架构」流程图
> 评估日期：2026-10-12
> 结论：**架构成立，但类比通道已实现、谱系通道零代码**；且有 1 处硬约束冲突必须先解。

---

## 0. 一句话结论

架构方向正确，**不需要改设计**。

但它的两个通道在代码里的成熟度完全不对称：

| 通道 | 代码状态 | 你要做的事 |
|---|---|---|
| **类比通道**（Embedding top-3） | **已完整实现**，阈值与你图上数字一致 | 无。P1 只扩它 |
| **谱系通道**（机制门控 + 实体匹配） | **零代码** | P1 全量新建 |
| 两个区块合并成一次调用 | 基础设施已就绪（拼字符串） | 加一个区块即可 |

---

## 1. 类比通道：已经存在，且数字对得上

你图上写的是 `0.50 ≤ sim < 0.67`。代码里：

```python
# backend/app/config.py:138-139
EVENT_MEMORY_MIN_SIM: float = 0.50
EVENT_MEMORY_MAX_SIM: float = 0.67
```

**完全一致。** 这不是巧合——这个区间是"召回同类但排除同一事件"的语义边界，`event_memory.py:98` 的 `recall()` 注释写明了：

- `sim >= 0.50` 才算同类事件；
- `sim >= 0.67` 视为**同一事件的不同表述**（不是历史参照），排除——避免把去重器漏掉的重复事件当成"历史规律"误导 LLM。

上界这一条很关键，是你这套设计里容易被忽略但正确的细节。**保留。**

### 已实现的配套

| 能力 | 位置 |
|---|---|
| 整批只调 1 次 Embedding API | `_recall_memory()` `event_synthesizer.py:892` |
| 静默降级为无记忆 | 同上，`except` 返回 `{}, 0` |
| prompt 区块渲染 | `format_memory_block()` `event_memory.py:313` |
| 结局规律归纳 | `summarize_pattern_evidence()` |
| 摘要截断 60 字 | `EVENT_MEMORY_SUMMARY_CHARS` |

`format_memory_block` 里还有一条我认可的设计：**当结局方向不一致时，显式提醒"逐条引用、勿臆断'通常/往往'"**——封堵单样本臆断。这条要带到谱系通道。

---

## 2. 谱系通道：零代码，但接口位置已确定

`grep` 全 `models/` 目录：只有 `entity.py:82` 一行注释提到 `thread_events.role`，**没有任何模型、表、服务**。

所以 P1 要从零建：

| 组件 | 状态 |
|---|---|
| `threads` 表 | §2.4 已定死结构，未建表 |
| `thread_events` 表 | 同上 |
| 机制门控（mechanism_key） | 无 |
| 章节 rollup | 无 |
| 谱系 prompt 区块 | 无 |

### 好消息：注入点现成

`_build_user_prompt()` 的组装方式是**字符串列表拼接**：

```python
parts: list[str] = []
if memory_block:
    parts.append(memory_block)          # ← 类比通道（已有）
if prev and prev.get("event_title"):
    parts.append("【此前事件状态】...")   # ← 已有
# ... 报道列表
parts.append("\n\n".join(lines))
return "\n\n".join(parts)
```

加谱系通道 = **再加一个 `parts.append(...)`**。不用改签名，不用改调用链。

唯一要动的是 `_synthesize_one` 的 `memory_block` 参数——建议扩成 `context_blocks: list[str]`，或者另加一个 `thread_block` 参数。

---

## 3. ⚠️ 必须解决的硬约束：768 token 不够

这是我在代码里扒出的**真实冲突**，不解决 P1 会静默降级。

| 项 | 当前值 | 位置 |
|---|---|---|
| `max_tokens` | **768** | `event_synthesizer.py:601` |
| 每簇最多报道 | 8 篇 | `_MAX_ARTICLES_PER_EVENT` |
| 摘要预览截断 | 200 字 | `_SUMMARY_PREVIEW_CHARS` |
| 历史同类事件 | 3 条 × 60 字 | `EVENT_MEMORY_TOP_K=3` |

现在已经有 4 个输入区块（历史同类 / 此前状态 / 报道列表 / 系统 prompt）。**再加谱系区块（章节 + 线卡 rollup）必然挤压输出空间。**

而且输出侧字段很多：`event_title / event_summary / latest_change / why_important / uncertainty / watch_next / status / version`——768 token 现在已经吃紧。

### 我的建议（三选一）

**方案 A（推荐）**：`max_tokens` 提到 **1024**，同时把 `EVENT_MEMORY_SUMMARY_CHARS` 从 60 降到 **50**。
理由：768→1024 成本增量极小（单次调用），但给足输出余量；摘要降 10 字几乎无感。

**方案 B**：谱系区块只注入**当前章节** + **rollup 摘要**，不注入完整历史章节。
理由：符合"章节快照老化"设计，L0/L1/L2/L3 分层本来就不该全塞。

**方案 C**：A + B 都做。最稳。

我建议 **C**。

---

## 4. 一个命名陷阱（延续上次）

架构图里"章节 + 线卡 Rollup"用的是**世界线语境**，但代码里 `role` 字段已经有两个不同义的用法：

| 字段 | 语义 | 位置 |
|---|---|---|
| `event_entities.role` | **实体级**：实体在事件中的角色 | 已建表 |
| `thread_events.role` | **线级**：事件在世界线中的作用 | 未建表 |

上次已约定 SQLAlchemy 层分别命名为 `entity_role` / `thread_role`。

**架构图落到代码时，谱系通道一律用 `thread_role`**，枚举 6 值：`core / trigger / reaction / signal / context / noise`。

---

## 5. 传导链与观察点：架构图最后一层的缺口

你图最后一层是「世界线章节 / 传导链 / 观察点 / 人工治理」。当前代码状态：

| 组件 | 状态 | 依赖 |
|---|---|---|
| 世界线章节 | 无 | `thread_events.chapter_seq` |
| **传导链** | 无 | `thread_transmissions` 表 |
| **观察点** | **有部分** | `watch_next` 字段（事件级，非线级） |
| 人工治理 | 无 | `thread_operations` 审计表 |

观察点这块有个**已有的近似物**：`events.watch_next` + `watch_result` + `watch_result` 兑现机制。

P1 做 `thread_watchpoints` 时**不要另起炉灶**，考虑复用兑现逻辑（`auto_stabilize_events` 里已有部分）。

---

## 6. 落地顺序建议

基于代码现状，我建议这样排：

```
P0（已完成）
  └─ 实体抽取 + 落库 + 事件关联

P1-a  建谱系通道的「存储层」
  ├─ threads / thread_events 建表（§2.4 已定死）
  ├─ thread_role 枚举落地
  └─ 机制门控：mechanism_key 分配逻辑

P1-b  建谱系通道的「召回层」
  ├─ 实体匹配 → 候选线
  ├─ 机制门控 → 确认线
  └─ 章节定位 → chapter_seq 自增

P1-c  建谱系通道的「注入层」
  ├─ rollup 生成
  ├─ thread_block 渲染
  └─ 并入 _build_user_prompt（+ max_tokens 提升）

P1-d  传导链 + 线级观察点（可延后）
```

**P1-a 和 P1-b 可以并行做**，没有依赖。

---

## 7. 需要你拍板的 3 件事

| # | 问题 | 我的建议 |
|---|---|---|
| 1 | `max_tokens` 是否现在就提？ | **提**。768 已吃紧，不提 P1 会静默降级（模型输出被截断，字段缺失） |
| 2 | 谱系区块注入多少上下文？ | **只注当前章节 + rollup 摘要**，不注全量历史（方案 B） |
| 3 | `thread_events` 是否现在建表？ | **是**。放在 P1-a 第一步，实体数据跑几天后再建也可以，但结构现在定死 |

---

## 附：代码位置索引

| 架构图节点 | 代码位置 |
|---|---|
| 现有新闻评分链路 | [llm_news_filter.py](/Users/rick/AlphaReader/backend/app/services/llm_news_filter.py) |
| 实体规范化 | [entity_writer.py](/Users/rick/AlphaReader/backend/app/services/entity_writer.py) |
| 事件合成候选 | [event_synthesizer.py](/Users/rick/AlphaReader/backend/app/services/event_synthesizer.py) `:231` |
| 类比通道 | [event_memory.py](/Users/rick/AlphaReader/backend/app/services/event_memory.py) `:98` |
| 谱系通道 | **无**（待建） |
| 两个区块合并 | `_build_user_prompt()` `:132` |
| 事件合成 LLM | `_synthesize_one()` `:519` |
| 三层卡片 | [entity.py](/Users/rick/AlphaReader/backend/app/models/entity.py)（Event/Entity 有，Thread 无） |
| 表结构定义 | [p0-entity-layer-spec.md](/Users/rick/AlphaReader/docs/p0-entity-layer-spec.md) §2.4 |
