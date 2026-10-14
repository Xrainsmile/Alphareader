# 世界线人工治理：设计落地评估

> 评估对象：你提出的「六、人工治理（五个核心操作 + API）」
> 评估日期：2026-10-12
> 结论：**全部采纳**。你强调的「人工排除持久化」是整套设计的命门，我把它提升为一级约束。

---

## 0. 一句话结论

五个操作、API 清单、事务要求——**全部采纳，不改方向**。

核对代码后发现三件必须处理的事：

| 类型 | 内容 |
|---|---|
| ✅ 已印证 | 「排除规则」在代码里已有同类实现（去重器排除表），可直接复用模式 |
| ⚠️ 需修正 | 项目里有**三套**认证并存，必须选对一套，否则"管理身份校验"落空 |
| 🔴 需补强 | 你的五操作缺一个**反向操作**（撤销排除），否则治理不可逆 |

---

## 1. 🔴 人工排除持久化：这是命门，不是可选项

你这句是整段最重要的：

> 人工把一条军事新闻摘除航运传导线，下一轮算法仍然可能因为共享实体将它重新归入。只有记录显式排除关系，并在归线入口检查，才能保证人工治理持续生效。

**完全正确。** 我把它从"建议"提升为**一级约束**。

### 为什么必须如此

归线打分公式 `S = 0.55E + 0.30M + 0.15R` 里，E（实体重合）是主导项。军事新闻和航运线共享"红海""胡塞武装"等实体，E 天然就高。**只要没排除表，算法必然反复加回。**

这不是概率问题，是**必然**——因为算法根本不知道有人为判断介入过。

### 代码印证：排除表模式已在去重器实现

项目里已有同类设计（去重器的排除表），说明这个模式在本项目是成熟的、被验证过的。P1 的 `thread_operations` 直接复用同样的结构即可。

### 落地要求（硬约束，三条）

**① 排除是三元组，不是二元组**

```
(thread_id, event_id)  ← 不够
(thread_id, event_id, reason, operator, created_at)  ← 必须有
```

理由：将来要能回答"为什么这条被摘除""谁摘的"。你 §1.4 我建议加的 `operator`/`reason` 正好用在这里。

**② 在归线入口检查，不在出口过滤**

必须在 `eligible()` 的第一步就查排除表：

```python
def eligible(event, thread):
    if is_manually_excluded(event.id, thread.id):
        return False          # ← 第一道，最优先
    if thread.status in {"merged", "split"}: return False
    return mechanism_compatible(...)
```

**放在出口过滤是错的**——出口过滤会让事件先被打分、先进影子表、再被丢弃，污染调参数据。

**③ 排除要有作用域（建议新增）**

你没提这个，但我认为必要：

| 作用域 | 语义 |
|---|---|
| `event` | 只排除这一个事件（默认） |
| `entity` | 排除该实体在这条线上的所有关联 |

理由：如果你摘除的是因为"某实体不该属于这条线"，逐事件摘除会永远摘不完。`entity` 作用域一次性解决。

### 🔴 我补强的一条：撤销排除

你的五操作里**没有"撤销排除"（Restore）**。

后果：误摘后无法恢复，只能等算法重新归入——但算法被排除表挡住了，永远归不回。**治理变成单向下坡。**

建议补第六个操作：

```
POST /api/v1/threads/{id}/events/{event_id}/restore
```

或者在 `thread_operations` 里加 `operation_type = "restore"`，与 `remove` 配对。这样 `DELETE` 不是真删除，只是软排除（你的表里已有 `thread_operations` 记录，天然支持）。

---

## 2. ⚠️ 认证：项目里有三套，必须选对

你说"沿用已有后台认证体系"——我查了代码，**实际有三套并存**：

| 认证方式 | 实现 | 用途 | 适用度 |
|---|---|---|---|
| `require_api_key` | 全局 `X-API-Key` | 所有 v1 路由基础保护 | ❌ 不够（Key 编译进公开 H5 bundle，等同公开） |
| `require_admin_key` | `X-Admin-Key` | 烧钱/重资源端点 | ✅ **推荐** |
| `verify_access_token` | `X-Access-Token`（7 天 HMAC） | 模拟仓/SEPA 私密数据 | 🟡 可用但偏重 |

### 关键发现

`auth.py` 的注释里写着一条重要事实：

> 全局 API Key 编译进公开 H5 bundle，等同公开，"私密"是假的。

所以**只用 `require_api_key` 等于没鉴权**——任何人拿到前端 bundle 就能调你的 merge/split。

### 我的建议

世界线治理端点用 **`require_admin_key` 叠加在 `require_api_key` 之上**（两个 Header 都要传），与 `stocks.py` / `digests.py` 的现有管理端点保持一致。

```
GET（列表/详情/历史）→ require_api_key
POST/PUT/DELETE（pin/merge/split/remove/move）→ require_api_key + require_admin_key
```

读操作可以不加 admin（前端页面要展示），**写操作必须加**——merge/split 是破坏性的。

### 路由注册

`router.py` 里 `_protected` 已经包了 `require_api_key`。新模块挂进去后，写操作在函数签名里再叠一个 `Depends(require_admin_key)` 即可，与 `news.py:64` 的写法一致。

---

## 3. 五个操作：逐条核对

| 操作 | 你的设计 | 代码核对 | 补充 |
|---|---|---|---|
| **Pin** | `pinned=true`，提升保护级别 | 无 threads 表 | 🟡 建议加 `pinned_fields`（JSONB）记录锁定了哪些字段，你提到"人工指定的核心机制字段可锁定" |
| **Merge** | 成员映射目标线，源线 `merged` + 重定向 | 无 | 🟡 重定向建议存 `merged_into_id`，GET 源线时 301 式跳转 |
| **Split** | 创建目标线，迁移章节与证据 | 无 | 🔴 见 §4 章节迁移 |
| **Remove** | 移除关联 + 排除规则 | 无 | 🔴 见 §1，需要 restore 配对 |
| **Move** | 章节迁移到指定线，保留原因 | 无 | 🟡 与 Split 共用章节迁移逻辑 |

### Pin 的一个细节

你说"人工指定的核心机制字段可锁定"——这个我用 JSONB 实现：

```python
pinned_fields: Mapped[dict | None]  # {"mechanism_key": "...", "contested_asset": "..."}
```

归线算法检测到 `pinned_fields` 里有某字段时，**不得覆盖该字段**。这样人工锁定的机制不会被下一轮自动改写。

---

## 4. 🔴 Split / Move 的章节迁移：必须保住 `chapter_id`

这是与你上一条「章节系统设计」直接冲突的点，必须先解。

Split 要"迁移选定章节"。但按你的章节设计：

| 字段 | 稳定性 |
|---|---|
| `chapter_id` | **永久稳定**，外部引用一律用它 |
| `chapter_no` | 可变，按时间重排 |

**迁移时必须保住 `chapter_id` 不变**，否则：

- 传导链（`thread_transmissions`）引用失效
- 观察点（`thread_watchpoints`）引用失效
- 人工操作历史（`thread_operations`）引用失效

### 迁移后重排

章节迁到新线后，`chapter_no` 必须按新线的时间轴**重排**（用我上次给的窗口函数 SQL），但 `chapter_id` 全程不动。

**这也是为什么 `chapter_id` 与 `chapter_no` 必须分离——Split/Move 操作是分离设计的直接受益者。**

### ⚠️ 治理动作依赖章号：排序必须同源（2026-10-14 补）

管理台的摘章 / Split / Move 都是「按章号指认章节」。这意味着**章号是治理动作的寻址依据**，
不是纯展示字段。因此：

- 治理端 `GET /threads/{id}/chapters` 与工作台详情的章节顺序**必须完全一致**；
- 新增任何返回章节列表的接口，排序键一律沿用 `chapter_no DESC`（含三级回退），见
  [world-thread-design.md §4.2](/Users/rick/AlphaReader/docs/world-thread-design.md) 的排序口径与分叉事故；
- 重排 `chapter_no` 后，两处会同步变化——这是**预期行为**，不是 bug。

曾发生两处排序键不一致导致「按章号摘错章」的风险，已在 2026-10-14 统一。修改任一处的
`ORDER BY` 前，先确认另一处同步改。

---

## 5. API 清单：核对与微调

你的 12 个端点我全部采纳，微调三处：

```diff
  GET    /api/v1/threads
  GET    /api/v1/threads/{id}
  GET    /api/v1/threads/{id}/chapters
  POST   /api/v1/threads/{id}/pin
  POST   /api/v1/threads/{id}/merge
  POST   /api/v1/threads/{id}/split
  POST   /api/v1/threads/{id}/events
  DELETE /api/v1/threads/{id}/events/{event_id}
+ POST   /api/v1/threads/{id}/events/{event_id}/restore   ← 撤销排除（我补）
  GET    /api/v1/threads/review-queue
  GET    /api/v1/threads/{id}/history
```

**微调说明：**

| # | 建议 | 理由 |
|---|---|---|
| 1 | 加 `restore` | 否则治理单向下坡，误摘无法恢复（§1） |
| 2 | `review-queue` 建议支持 `?type=suggested_split` | 你的「建议拆分队列」需要独立筛选 |
| 3 | `history` 建议支持分页 | 治理历史会持续累积，长线可能上千条 |

### 关于 `chapter_no` 重排的 API

Split/Move 后要不要暴露一个重排端点？我建议**不暴露**——重排在事务内自动完成，避免人工误触导致序号混乱。

---

## 6. 事务要求：完全同意，另加一条

你说"使用数据库事务保证拆分、合并和关系重定向的一致性"——**完全同意**。

Split 典型要动 5 张表：`threads` / `thread_events` / `thread_transmissions` / `thread_watchpoints` / `thread_operations`。任何一张写失败都必须整体回滚。

### 我加的一条：并发保护

上次 §2.4 里我提过 `chapter_seq` 自增用 **PG advisory lock**。治理操作同样需要：

```python
# merge/split/move 前先取线级锁，防止并发治理互相覆盖
await db.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:tid))"), {"tid": thread_id})
```

理由：两个人同时 merge 同一条线，或者一个人在 merge 另一个人在 split，没有锁会产生脏数据。advisory lock 是事务级的，回滚自动释放，比应用层锁靠谱。

---

## 7. 拆分三条件：保留 + 降级为建议

你建议：

> >30 章 + 实体子群分离 + 独立可交易标的 三条件保留，但先把满足条件的线放入「建议拆分」队列，验证聚类效果后再考虑自动执行。

**完全同意。** 这跟 `T_JOIN=0.45 影子运行 7 天` 是同一套方法论：**先观察，再自动化**。

落地建议：

| 阶段 | 行为 |
|---|---|
| 阶段 1（影子） | 三条件命中 → 写入 `review-queue`，不自动拆 |
| 阶段 2（建议） | 人工确认后执行 |
| 阶段 3（自动） | 影子期验证准确率达标后才开启 |

**不要跳过阶段 2。** 自动拆分一旦误判，章节迁移的代价很高（要动 5 张表）。

---

## 8. 落地顺序（更新版，合并治理）

```
P0（已完成）实体抽取 + 落库 + 事件关联 ✅
#1 max_tokens 1024 ✅ 已完成

P1-a  存储层
  ├─ thread_operations 审计表（先建，eligible() 依赖）
  ├─ threads / thread_events（chapter_id + chapter_no + chapter_seq 三字段）
  ├─ membership_role 枚举（6 值）
  └─ thread_transmissions.evidence_status（3 值 + 不可回退约束）

P1-b  机制识别（P0 关键词 → P1 JSON 字段）

P1-c  归线打分（含排除表入口检查）+ 影子 7 天

P1-d  治理 API（12+1 端点，admin 鉴权，事务 + advisory lock）

P1-e  传导链 + 线级观察点
```

**`thread_operations` 排在 P1-a 第一位**——`eligible()` 的排除检查依赖它，没有它整个治理体系不成立。

---

## 9. 需要你拍板

| # | 问题 | 我的建议 |
|---|---|---|
| 1 | 加 `restore` 撤销排除端点吗？ | **加**。否则治理单向下坡 |
| 2 | 排除作用域支持 `entity` 级吗？ | **支持**。逐事件摘除永远摘不完 |
| 3 | 认证用 `require_admin_key` 叠加？ | **是**。全局 API Key 等同公开，不够 |
| 4 | `pinned_fields` 用 JSONB 记锁定字段？ | **是**。否则"锁定核心机制字段"落不了地 |
| 5 | 治理操作加 advisory lock？ | **加**。防并发治理互相覆盖 |
| 6 | 自动拆分走三阶段？ | **是**。跳过阶段 2 风险太高 |

---

## 附：代码位置索引

| 设计节点 | 代码位置 |
|---|---|
| 三套认证 | [auth.py](/Users/rick/AlphaReader/backend/app/auth.py) `:53` |
| 管理端点写法范例 | [news.py](/Users/rick/AlphaReader/backend/app/api/v1/news.py) `:64` |
| SEPA admin 范例 | [sepa.py](/Users/rick/AlphaReader/backend/app/api/v1/sepa.py) `:60` |
| 路由注册 | [router.py](/Users/rick/AlphaReader/backend/app/api/v1/router.py) `:26` |
| 归线入口 `eligible()` | 待建（P1-c） |
| 章节三字段设计 | [world-thread-routing-assessment.md](/Users/rick/AlphaReader/docs/world-thread-routing-assessment.md) §2 |
| `evidence_status` 三态 | 见本文档 §0（待写入表结构） |
