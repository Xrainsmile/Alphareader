# 归线算法与七表模型：代码对齐评估

> 评估对象：你提出的「三、数据模型（七张核心表）」+「四、自动归线算法（机制门控）」
> 评估日期：2026-10-12
> 结论：**算法设计完全采纳**，但有 3 处字段名对不上、1 个 token 冲突、1 个认知已被代码印证。

---

## 0. 一句话结论

你的两段设计**我全部采纳，不做方向性修改**。

需要处理的分三类：

| 类型 | 数量 | 说明 |
|---|---|---|
| 字段名对不上（必须对齐） | 3 处 | `why_it_matters` / `role` / `type` |
| 代码现状印证你的判断 | 2 处 | 0.90 别名陷阱、`unknown` 保留 |
| 新增约束（你没提但必须解） | 2 处 | token 预算、Jaccard 分母定义 |

---

## 1. 七张表：字段差异核对

你给的表结构与已建的 `entities` / `event_entities` 对比：

### 1.1 已建两表（P0 完成）

| 你的字段 | 实际字段 | 状态 |
|---|---|---|
| `entities.id` | `id` UUID | ✅ |
| `entities.canonical_name` | `canonical_name` | ✅ |
| `entities.type` | **`entity_type`** | ⚠️ 见下 |
| `entities.aliases` | `aliases` ARRAY | ✅ |
| `entities.description` | **无** | ❌ 待加 |
| `entities.embedding` | `embedding` ARRAY(REAL) | ✅ |
| `entities.mention_count` | `mention_count` | ✅ |
| `event_entities.role` | `role` | ⚠️ 见 §1.2 |
| `event_entities.confidence` | **`weight`** (SmallInt) | ⚠️ 语义不同 |

### 1.2 三处必须对齐的字段名

**① `entities.type` → `entity_type`**

代码已用 `entity_type`（`entity.py:38`）。`type` 是 Python 内置名，做 ORM 属性名会遮蔽内置函数。**建议沿用 `entity_type`**，你文档里的 `type` 视为简写。

**② `event_entities.role` 与 `thread_events.role` 撞名**

这是上次就标记的陷阱，现在你第三段里 `thread_events` 用的是 `membership_role`——**很好，你自己已经规避了**。

所以最终命名定为：

| 字段 | 语义 | 枚举 |
|---|---|---|
| `event_entities.role` | 实体级：实体在事件中的角色 | `subject/target/stake/asset/location` |
| `thread_events.membership_role` | 线级：事件在世界线中的作用 | `core/trigger/reaction/signal/context/noise` |

**`membership_role` 这个名字比 `thread_role` 更准确**，我采纳你的，废弃我之前提的 `thread_role`。

**③ `confidence` vs `weight`**

你写 `confidence`（置信度 0~1），代码已建成 `weight`（SmallInt，1=次要 2=核心）。

两者语义不同：
- `confidence` = 抽取质量的置信度
- `weight` = 聚类时的加权倍率

**建议两个都留**，因为你的公式 `S = 0.55E + 0.30M + 0.15R` 里 E 要做"核心实体 3 倍加权"，这正是 `weight` 的用途。加 `confidence` 用于低置信关联过滤。

### 1.3 缺 `description` 字段

你的 `entities.description` 目前没有。

**建议加，但 P0 不填**。理由：实体卡是"永久"的，将来人工治理、别名合并、类型纠正都需要一个人类可读的说明位。P1.5 挪库时再批量补。

### 1.4 五张未建表

`threads` / `thread_events` / `thread_links` / `thread_transmissions` / `thread_watchpoints` —— 全部零代码。

`thread_operations`（审计表）你单列了，我同意。但建议**再加两列**：

| 建议加 | 理由 |
|---|---|
| `operator` | 谁做的（人工治理要可追溯） |
| `reason` | 为什么做（合并/拆分的依据，将来回放调参要用） |

---

## 2. 归线算法：三步走，全部采纳

你的拆解（硬条件筛选 → 兼容机制内打分 → 影子运行）**完全正确**，我不改。

### 2.1 第一步：硬条件筛选

你的 `eligible()` 伪代码我逐条核对：

```python
def eligible(event, thread):
    if thread.status in {"merged", "split"}: return False
    if is_manually_excluded(event.id, thread.id): return False
    return mechanism_compatible(...)
```

| 条件 | 代码现状 | 需要新增 |
|---|---|---|
| `thread.status in {merged, split}` | 无 threads 表 | 建表时定 |
| `is_manually_excluded` | 无 | 依赖 `thread_operations` 审计表 |
| `mechanism_compatible` | 无 | P0 用关键词，P1 用 `mechanism_hints` |

**关键点：你的 `is_manually_excluded` 依赖审计表**——这正好印证了 §1.4 里"先建 `thread_operations`"的必要性。人工摘除过的线不能再自动归回去，否则治理失效。

### 2.2 P0 机制识别（关键词组合）

你建议用 `标题 / tags / catalyst_type / why_it_matters / 摘要` 组合。

**核对结果：字段名对不上 1 处，位置对不上 1 处。**

| 你的表述 | 实际 | 位置 |
|---|---|---|
| `why_it_matters` | **`why_important`** | `event.py:41` |
| `catalyst_type` | 存在，但**在 `news` 表不在 `events` 表** | `news.py:45` |
| `tags` | 在 `news` 表 | `news.py:35` |

所以 P0 识别机制时，数据源是**跨两张表**的：

```
events:  title, summary, why_important
news:    tags, catalyst_type      ← 来自簇的根报道与子报道
```

`catalyst_type` 只在 news 上，取簇内**众数**（多数子报道的 catalyst_type）比取根报道更稳——根报道可能是快讯，类型标得粗糙。

### 2.3 P1 机制识别（复用合成 JSON）

你建议在 `event_synthesizer.py` 的 JSON 输出加：

```json
{
  "mechanism_hints": ["military_control", "shipping_disruption"],
  "contested_assets": ["曼德海峡", "红海航线"]
}
```

**方向同意，但有硬约束必须先解。**

#### ⚠️ token 冲突（我上次已标记，这里更严重）

| 项 | 当前值 | 位置 |
|---|---|---|
| `max_tokens` | **768** | `event_synthesizer.py:601` |
| 现有输出字段 | 8 个（含 `event_summary`/`latest_change`/`why_important`/`uncertainty`/`watch_next` 等长文本） | `:93-94` |
| 现有输入区块 | 4 个（历史同类/此前状态/报道列表/系统 prompt） | `_build_user_prompt` |

现在再加**两个数组字段** + 谱系通道的 rollup 区块，**768 必然不够**。

后果不是报错，是**静默降级**：模型输出被截断，JSON 不完整 → `_parse_llm_response` 返回 None → 触发重试 → 再失败 → 该簇本轮不合成。这种故障很难排查。

**建议（必须做，否则 P1 别上）**：

```
max_tokens: 768 → 1024
EVENT_MEMORY_SUMMARY_CHARS: 60 → 50
谱系区块只注当前章节 + rollup 摘要（不注全量历史章节）
```

#### ⚠️ 第二个约束：字段必需性

`_parse_llm_response` 的必需字段是 `event_title / event_summary / has_material_update`（`:189`）。

**新增的两个字段必须是可选的**（缺失不触发失败）。原因：老模型/降级模型可能不返回，硬要求会导致整批合成失败。

建议解析时用 `.get()` + 默认值 `[]`，与 `entities` 的处理方式一致。

### 2.4 打分公式

```
S = 0.55E + 0.30M + 0.15R
```

**采纳**，权重作为启动参数。三点补充：

**① Jaccard 分母必须定义清楚**

"核心实体加权 Jaccard" 有两种算法，结果差异很大：

| 算法 | 分母 | 特点 |
|---|---|---|
| 加权 Jaccard | `Σmin(w) / Σmax(w)` | 标准，推荐 |
| 覆盖率 | `Σ(交集权重) / Σ(事件权重)` | 偏向把事件塞进大线 |

**建议用标准加权 Jaccard**，否则长线（实体多）会天然吸走所有事件，这正是你要防的"强行归类"。

**② `is_generic` 必须排除在 E 之外**

代码已有 `GENERIC_ENTITIES` 集合和 `is_generic` 标记（`entity_writer.py:36`）。

如果"美国/市场/行业"这类泛化实体参与 Jaccard，两条不相关的线会因为都提到"市场"而被判相似。**必须排除。**

**③ `R`（活跃度奖励）要有上限——你已提到，代码里这样落**

建议 `R = min(days_since_update_bonus, CAP)`，且 CAP 建议 **0.15 内的一个小数**（如 `R ∈ [0, 1]` 后乘 0.15）。否则活跃线会滚雪球。

### 2.5 T_JOIN = 0.45 影子运行

**完全同意，这是最稳妥的落地方式。**

建议影子期记录三张表：

| 记录 | 用途 |
|---|---|
| 每对 (event, thread) 的 S 分 | 调权重 |
| 命中/未命中 T_JOIN 的分布 | 校准阈值 |
| 人工改判记录 | 作为 ground truth |

跑满 **7~14 天**后做一次分布分析再决定是否驱动生产。

---

## 3. 你的两个判断，代码已经印证

### 3.1 "Embedding 0.90 不足以证明同一实体" —— 完全正确

当前 `entity_writer.py` 的规范化走的是**确定性 `ALIAS_MAP`**（`:55`），**没有任何 embedding 语义归并**。

`canonicalize()` 明确注释：`不做语义归并（那是 ALIAS_MAP 的职责）。纯字符串变换，零 LLM。`

所以你的提醒正好是 P1 要加能力时的**护栏**。建议写成硬规则：

```
embedding sim >= 0.90  →  仅作为「别名候选证据」
                          必须结合 entity_type + 上下文验证后才能合并
                          合并进 thread_operations 留痕
```

**绝不允许自动合并。** 宁可重复建卡，不可错误归并——因为实体卡是永久的，错Merge 的纠正成本极高。

### 3.2 "机制不确定时保留 unknown" —— 与现有设计一致

代码里 `entity_type` 是 `nullable=True`，`role` 也是 `nullable=True`。**未知就是 None，不强行填。**

你的 `unknown` 保留策略要落到机制字段上：`mechanism_hints` 为空数组时，**不参与门控筛选**（即对所有线都兼容），而不是归到某条默认线。

---

## 4. 落地顺序（更新版）

```
P0（已完成）
  └─ 实体抽取 + 落库 + 事件关联 ✅

P1-a  存储层
  ├─ thread_operations 审计表（先建，eligible() 依赖它）
  ├─ threads / thread_events 建表
  └─ membership_role 枚举（6 值）

P1-b  机制识别
  ├─ P0 版：关键词组合（跨 events + news 两表）
  ├─ P1 版：合成 JSON 加 mechanism_hints / contested_assets（可选字段）
  └─ ⚠️ max_tokens 768 → 1024（前置）

P1-c  归线打分
  ├─ eligible() 硬筛选
  ├─ S = 0.55E + 0.30M + 0.15R（加权 Jaccard，排除 is_generic）
  └─ T_JOIN=0.45 影子运行 7~14 天

P1-d  传导链 + 线级观察点
```

**`thread_operations` 排在最前面**，因为 `is_manually_excluded` 依赖它。

---

## 5. 需要你拍板

| # | 问题 | 我的建议 |
|---|---|---|
| 1 | `max_tokens` 提到 1024？ | **必须提**。不提 P1 会静默降级，故障难排查 |
| 2 | `confidence` 与 `weight` 是否并存？ | **并存**。前者过滤抽取质量，后者做聚类加权（你的 3x 公式要用） |
| 3 | `entities.description` 现在加吗？ | **加列但 P0 不填**，P1.5 批量补 |
| 4 | Jaccard 用哪种？ | **标准加权 Jaccard**（`Σmin/Σmax`），防长线虹吸 |
| 5 | `thread_operations` 加 `operator`/`reason` 吗？ | **加**。人工治理要可追溯，回放调参要依据 |
| 6 | 影子期多久？ | **7~14 天**，跑满一个完整周循环再加余量 |

---

## 附：代码位置索引

| 你的设计节点 | 代码位置 |
|---|---|
| `why_it_matters` | 实为 [event.py](/Users/rick/AlphaReader/backend/app/models/event.py) `:41` `why_important` |
| `catalyst_type` / `tags` | [news.py](/Users/rick/AlphaReader/backend/app/models/news.py) `:45` / `:35` |
| `entities` / `event_entities` | [entity.py](/Users/rick/AlphaReader/backend/app/models/entity.py) |
| 规范化（无 embedding 归并） | [entity_writer.py](/Users/rick/AlphaReader/backend/app/services/entity_writer.py) `:94` |
| 合成 JSON 输出结构 | [event_synthesizer.py](/Users/rick/AlphaReader/backend/app/services/event_synthesizer.py) `:93` |
| `max_tokens=768` | 同上 `:601` |
| 必需字段校验 | 同上 `:189` |
| 表结构 §2.4 | [p0-entity-layer-spec.md](/Users/rick/AlphaReader/docs/p0-entity-layer-spec.md) |
