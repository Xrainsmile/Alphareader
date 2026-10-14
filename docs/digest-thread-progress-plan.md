# 简报「世界线进展」区块 — A 方案（零 LLM 改动）

> 状态：已定稿，待开发执行。
> 创建：2026-10-14
> 关联：[world-thread-design.md](./world-thread-design.md) ｜ [frontend-design-spec.md](./frontend-design-spec.md)

## 一、目标与边界

在阶段简报中新增「世界线进展」区块，回答 **「我跟踪的世界线，本期推进到第几章了」**。

**边界（必须遵守）**

1. **不替换 `what_changed`**。两者并列：`what_changed` 讲话题轮换（时间轴，相邻两期对比），`thread_progress` 讲因果推进（因果轴，纵向位置）。只替换会丢信息。
2. **零 LLM 改动**。A 方案不修改 `DIGEST_SYSTEM_PROMPT`、不调 `_call_llm_briefing`、不新增任何 prompt。
3. **零 LLM 成本增量**。线名、章号、章节标题均为数据库现成字段，程序直接拼装。

### 为什么可以完全不碰 LLM

`threads.rollup`（4 段式滚动摘要）虽在模型中定义，但**当前无任何代码写入**（设计文档列为 P2）。A 方案主动绕开它，只依赖已稳定写入的字段，因此：

- 无需等待 P2 落地；
- 无 LLM 参与 → 无幻觉源 → **无需 `thread_id` 防编造校验**（`_clean_entries` 那套不套用）。

代价：文案是模板句，非自然语言润色。作为形态验证够用，确认价值后再升 B 方案（补 rollup + LLM 润色）。

## 二、已确认的现成资产

| 资产 | 位置 | 状态 | 用途 |
|---|---|---|---|
| 事件→线关联接口 | `backend/app/api/v1/workbench.py:702` `digest_thread_links` | 已上线 | 复用其 SQL 骨架 |
| 前端世界线入口 | `frontend/src/pages/reports/index.vue:539` `threadLinksOf` | 已上线 | 复用容错模式 |
| API 封装位置 | `frontend/src/utils/api.js:625` `fetchDigestThreadLinks` | 已上线 | 新函数紧邻其后 |
| 章号 `chapter_no` | 2026-10-14 实测 441/441 非空 | 可用 | 「第 N 章」成立 |
| 章节总数 `chapter_count` | `thread_router.py:806` `_sync_chapter_count` 维护 | 真实递增 | 总章数 |
| 样式体系 | `index.vue:1222` 起 `.dc-tl-*` | 已上线 | 新增 `.dc-tp-*` 对齐 |

**关键结论**：不需新写「按事件反查线」逻辑——`digest_event_links` JOIN `thread_events` 即可，接口已在跑。

## 三、改动清单（4 处）

### 改动 1 — 新增聚合端点

位置：`backend/app/api/v1/workbench.py`，紧邻 `digest_thread_links`（约 L702 之后）。

```python
@router.get("/digests/{digest_id}/thread-progress")
async def digest_thread_progress(
    digest_id: int, db: AsyncSession = Depends(get_db)
):
    """简报 → 世界线进展：本期各条线推进到第几章、新增了哪些章节。

    与 digest_thread_links 同源（digest_event_links JOIN thread_events），
    但聚合粒度不同：links 是「事件→线」（每条事件挂哪些线），
    本端点是「线→本期增量」（本期哪些线有推进）。

    ★ 运行时关联而非随简报存储：理由同 digest_thread_links——
      归属是活数据，归线会被人工修正（移线/拆线），写死会让历史简报指向错误。
    """
    rows = (await db.execute(text("""
        SELECT t.id AS thread_id, t.title AS thread_title,
               t.status AS thread_status, t.chapter_count,
               COUNT(DISTINCT l.event_id) AS new_chapters,
               MAX(te.chapter_no) AS latest_chapter_no,
               array_agg(te.snapshot_title ORDER BY te.chapter_no DESC) AS new_titles
        FROM digest_event_links l
        JOIN thread_events te ON te.event_id = l.event_id
        JOIN threads t ON t.id = te.thread_id
        WHERE l.digest_id = :d
          AND COALESCE(te.role, 'core') <> 'noise'
        GROUP BY t.id, t.title, t.status, t.chapter_count, t.pinned, t.last_event_at
        ORDER BY t.pinned DESC, COUNT(DISTINCT l.event_id) DESC, t.last_event_at DESC
        LIMIT 5
    ```
    """), {"d": digest_id})).mappings().all()

    return {
        "digest_id": digest_id,
        "items": [
            {
                "thread_id": str(r["thread_id"]),
                "thread_title": r["thread_title"],
                "thread_status": r["thread_status"],
                "chapter_count": int(r["chapter_count"] or 0),
                "new_chapters": int(r["new_chapters"] or 0),
                "latest_chapter_no": r["latest_chapter_no"],
                "new_titles": [t for t in (r["new_titles"] or []) if t][:3],
            }
            for r in rows
        ],
    }
```

**排序口径**：`pinned`（人工钉住）优先 → 本期新增章节数降序 → `last_event_at` 降序。取 Top 5。

### 改动 2 — schema 加字段

`structured_content` 新增 `thread_progress: []`。

**填充方式**：由**程序**在保存简报时填充，**不进 `_parse_briefing_json`**（该函数清洗 LLM 输出，A 方案 LLM 不产出此字段）。

**注意**：因是运行时关联（同 `digest_thread_links` 的设计决策），此处**不写 thread_id 快照**。前端走独立端点拉取，`structured_content` 无需存此字段亦可——若决定不入库，本改动可省略，仅保留改动 1 + 3。

### 改动 3 — 前端区块（★ 常驻首屏）

位置：`frontend/src/pages/reports/index.vue`，插在 **折叠详细解释区（`dc-overview-fold`，约 L147）之前、「必须知道」（`sec-mustknow`，约 L155）之前**。

> **决策记录**：`what_changed` 目前藏在默认折叠区里，平时看不到。新区块**必须放折叠区外、常驻首屏**，否则等于没做。

模板骨架：

```html
<!-- 世界线进展：本期哪些线推进了（常驻首屏，空则不渲染） -->
<view
  v-if="threadProgressOf(item.id).length"
  id="sec-thread-progress"
  class="dc-section dc-tp"
>
  <view class="dc-tp-head">
    <text class="dc-section-title">世界线进展</text>
    <text class="dc-tp-count">{{ threadProgressOf(item.id).length }} 条推进</text>
  </view>
  <view
    v-for="tp in threadProgressOf(item.id)"
    :key="tp.thread_id"
    class="dc-tp-item"
    @click.stop="goThread(tp)"
  >
    <text class="dc-tp-title">{{ tp.thread_title }}</text>
    <text class="dc-tp-chapter">第 {{ tp.chapter_count }} 章</text>
    <text v-if="tp.new_chapters" class="dc-tp-delta">+{{ tp.new_chapters }}</text>
    <text v-if="tp.new_titles.length" class="dc-tp-titles">
      {{ tp.new_titles.join(' / ') }}
    </text>
  </view>
</view>
```

脚本（紧邻 `threadLinksOf` / `loadThreadLinks`，约 L539-560）：

```js
const threadProgressMap = reactive({})   // { [digestId]: item[] }

function threadProgressOf(digestId) {
  return threadProgressMap[digestId] || []
}

async function loadThreadProgress(digestId) {
  if (!digestId || threadProgressMap[digestId]) return
  try {
    const res = await fetchDigestThreadProgress(digestId)
    threadProgressMap[digestId] = (res && res.items) || []
  } catch (e) {
    // 关联失败不阻断简报阅读：世界线进展是增强，不是简报本体
    console.warn('[reports] 世界线进展加载失败:', e)
    threadProgressMap[digestId] = []
  }
}
```

`api.js` 新增（紧邻 `fetchDigestThreadLinks`，L625 之后）：

```js
export function fetchDigestThreadProgress(digestId) {
  return request({ url: `/api/v1/digests/${digestId}/thread-progress`, method: 'GET' })
}
```

**调用时机**：沿用现有 `loadThreadLinks` 的调用点（简报加载/展开时一并触发）。

### 改动 4 — 样式类

新增 `.dc-tp-*`，对齐现有 `.dc-tl-*`（`index.vue:1222` 起）。强制约束：

- **禁止裸色值**，一律用 `--color-*` 令牌；
- **禁止内联 emoji 当图标**；
- 圆角用 `--radius-r-*` / `--radius-p-*`，**不得复用旧 `--radius-sm/md/lg/pill`**；
- 数字（章号、`+N`）用 `--font-numeric` 等宽字体；
- 三档验证：`<768px` / `≥768px` / `≥1200px`。

## 四、预期效果

以 2026-10-14 简报为例：

**改前**：「伊朗原油出口归零」是一条孤立新闻，读不出它在哪条因果链的哪个位置。

**改后**：

```
世界线进展 · 2 条推进
• 霍尔木兹供给冲击   第 9 章  +2
  伊朗原油出口归零 / 海峡油轮改道
• 锂电材料景气回升   第 3 章  +2
  盐湖股份预增 / 恩捷股份预增
```

高盛财报、金佰利并购**不会出现**（未归线）。这不是缺陷——它正好暴露归线覆盖率缺口，也正是「不能替换 `what_changed`」的实证。

## 五、验收清单

- [ ] **章号方向抽查**（★ 最高优先级）：见下方「章号口径（执行时确认）」，代码已按结论实现，仍建议抽查一条真实线复核。
- [ ] 区块常驻首屏，未展开折叠区即可见。
- [ ] 无归线事件时整块不渲染（冷启动期不露空标题）。
- [ ] 接口失败时简报正常展示（容错同 `loadThreadLinks`）。
- [ ] 三档屏幕宽度无溢出。
- [ ] 点击条目跳转 `/pages/worldline/detail?id=<thread_id>` 正常。

## 六、风险与后续

**唯一实质风险：归线质量。** 归线当前仍处影子期调参阶段（基线清洗进行中）。因是程序化展示、无 LLM 缓冲，误归会**直接裸露**在简报首屏。

**建议**：上线后观察 3 天误归率，再决定是否升级 B 方案（补 `threads.rollup` 生成 + LLM 润色文案）。B 方案预估 LLM 成本 +$0.24/月 量级（全局摊销，非简报独占）。

## 六之二、章号口径（执行时确认，2026-10-14）

执行阶段核对代码后确认并已落地两处：

1. **方向**：`chapter_no` 为「最早章 = #1、最新章 = #N」。依据是 `workbench.py` 中 `display_no` 的回退式 `total - i + 1`（`i=1` 对应最新章）。故 `MAX(chapter_no)` 即最新章，可直接拼「第 N 章」。
2. **noise 过滤**：必须加 `AND COALESCE(te.role,'core') <> 'noise'`，与世界线详情页 `_chapter_rows` 口径一致。原因：`threads.chapter_count` 由 `_sync_chapter_count` 维护、**包含 noise 章节**；若不排除，本端点算出的章号会大于详情页实际展示的最大章号，出现「第 12 章」但详情页只到「第 9 章」。

**因此**：
- 字段 `chapter_no`（展示用，`MAX(chapter_no)`，已排除 noise）→ 前端拼「第 N 章」用它；
- 字段 `chapter_count`（含 noise，仅供参考）→ **前端不要用它当章号**。

## 七、不做的事（明确排除）

- 不改 `DIGEST_SYSTEM_PROMPT`；
- 不新增 LLM 调用；
- 不套用 `_clean_entries` 的 `thread_id` 校验（无 LLM 参与即无编造源）；
- 不依赖 `threads.rollup`（当前无写入）；
- 不把 `thread_id` 写进 `structured_content` 快照（归属是活数据）。
