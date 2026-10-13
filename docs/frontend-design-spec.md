# AlphaReader 前端设计规范

> **权威性声明**：本文档是 AlphaReader 前端视觉与交互的**唯一权威规范**，本地研发（人工或 AI 编码助手）在新增、修改、重构任何 UI 前必须先阅读并遵守。与本文档冲突的旧写法以本文档为准。
> 版本：v1.0 · 生成日期：2026-10-13
> 适用范围：`/Users/rick/AlphaReader/frontend`（uni-app + Vue3 + Vite，编译至 H5 / 小程序）
> 权威源文件：[App.vue](/Users/rick/AlphaReader/frontend/src/App.vue)（全局令牌定义）、[pc-layout.css](/Users/rick/AlphaReader/frontend/src/styles/pc-layout.css)（响应式骨架）
> 关联文档：[design-token-map.md](/Users/rick/AlphaReader/docs/design-token-map.md)、[design-system-project.md](/Users/rick/AlphaReader/docs/design-system-project.md)、[front.md](/Users/rick/AlphaReader/front.md)

---

## 一、设计原则

1. 令牌优先：任何色值、圆角、间距、层级、字体都必须走 CSS 变量，禁止在业务组件内写死十六进制色值。
2. 双档单位：移动端档用 `rpx`（基准 375px，750rpx 满宽），PC 档用 `px`，两套令牌不可跨档混用。
3. 语义命名：令牌按用途命名（`--color-bg-card`），不按外观命名（`--color-white`）。
4. 内容优先：中文正文阅读舒适区 640–720px，PC 主内容区固定上限 680px。
5. 涨跌语义：全站采用美股惯例，红涨绿跌 `--color-up` 红 / `--color-down` 绿（**待人工确认是否按 A 股反转**）。

---

## 二、色彩系统

### 2.1 基础色

| 令牌 | 色值 | 用途 |
|---|---|---|
| `--color-bg` | `#f6f7fb` | 页面根背景 |
| `--color-bg-card` | `#ffffff` | 卡片 / 面板 / 侧栏底 |
| `--color-bg-secondary` | `#f4f6fa` | 次级区块底 |
| `--color-bg-hover` | `#fafbfc` | 悬停态底 |
| `--color-bg-active` | `#f5f6f8` | 激活态 / 输入框底 |
| `--color-bg-tag` | `#e8f0fe` | 标签底 |
| `--color-bg-code` | `#f5f5f7` | 代码 / 引用底 |

### 2.2 文字色（四级灰阶）

| 令牌 | 色值 | 用途 |
|---|---|---|
| `--color-text-primary` | `#1c263c` | 标题、正文主文字 |
| `--color-text-secondary` | `#6b7587` | 副标题、摘要 |
| `--color-text-body` | `#4a5568` | 长文正文 |
| `--color-text-muted` | `#8590a2` | 元信息、时间戳 |
| `--color-text-placeholder` | `#9ba8bc` | 占位符、空状态 |
| `--color-text-white` | `#ffffff` | 反色文字 |

### 2.3 品牌色

| 令牌 | 色值 | 用途 |
|---|---|---|
| `--color-brand` | `#365fda` | 品牌主色、选中态、链接 |
| `--color-brand-hover` | `#3b78e7` | 品牌 hover |
| `--color-brand-light` | `#edf2ff` | 品牌浅底 |
| `--color-brand-alt` | `#1677ff` | 品牌替代蓝 |
| `--color-brand-ios` | `#007aff` | iOS 系统蓝 |
| `--color-brand-deep` | `#3b78dc` | 品牌深压态 |

### 2.4 语义色

| 令牌 | 色值 | 用途 |
|---|---|---|
| `--color-up` | `#ff3b30` | 涨（红） |
| `--color-down` | `#34c759` | 跌（绿） |
| `--color-warning` | `#ff9500` | 警告橙 |
| `--color-info` | `#3b82f6` | 信息蓝 |
| `--color-danger` | `#eb4b4b` | 危险红 |
| `--color-success` | `#30b86e` | 成功绿 |
| `--color-neutral` | `#6b7280` | 中性灰 |
| `--color-up-alt` / `--color-down-alt` | `#ef4444` / `#22c55e` | 涨跌替代色 |
| `--color-danger-dark` | `#c62828` | 危险深文字 |
| `--color-success-dark` | `#16a34a` | 成功深文字 |
| `--color-info-deep` | `#1565c0` | 信息深文字 |

### 2.5 边框

| 令牌 | 色值 | 用途 |
|---|---|---|
| `--color-border` | `#e7ebf2` | 默认描边 |
| `--color-border-light` | `#e7ebf2` | 分隔线 |
| `--color-border-subtle` | `#eef1f6` | 极弱描边 |
| `--color-border-strong` | `#c0c4cc` | 强描边 / 输入框 |
| `--color-border-hover` | `#c0c0cc` | 悬停描边 |

### 2.6 评分色阶（与涨跌语义解耦）

设计原则：`<7` 分属低优先级，用中性灰并降低对比；`≥7` 才逐级加色加重。此处红色仅表示「重要/值得关注」，**不表示涨跌**。

| 等级 | 背景令牌 | 文字令牌 |
|---|---|---|
| score-5（最低） | `--score-5-bg` `#f0f2f5` | `--score-5-text` `#9aa3b2` |
| score-4 | `--score-4-bg` `#f0f2f5` | `--score-4-text` `#8590a2` |
| score-3 | `--score-3-bg` `#eef3ff` | `--score-3-text` `#466ed0` |
| score-2 | `--score-2-bg` `#fff5e6` | `--score-2-text` `#a7792c` |
| score-1（最高） | `--score-1-bg` `#fff0ee` | `--score-1-text` `#c15244` |

### 2.7 渐变

```
--gradient-vcp-hot     135deg #ff3b30 → #ff6b5a     VCP 过热
--gradient-vcp-warm    135deg #ff9500 → #ffb340     VCP 偏热
--gradient-vcp-normal  135deg #34c759 → #5dd67a     VCP 正常
--gradient-vcp-cool    135deg #8e8e93 → #a8a8ae     VCP 冷却
--gradient-sentiment-strong-bull / mild-bull / caution / mild-bear / neutral   情绪五档
--gradient-info-bar    90deg  #3b82f6 → #60a5fa     信息条
--gradient-info-bg     180deg #f0f7ff → #ffffff     信息区背景
--gradient-briefing-bg 135deg #f7f8fa → #eef1f5     简报背景
```

### 2.8 时段色（简报时段切片）

| 时段 | 前景 | 背景 |
|---|---|---|
| 早间 morning | `--color-time-morning` `#FF9800` | `--color-bg-time-morning` `#FFF3E0` |
| 午间 midday | `--color-time-midday` `#F44336` | — |
| 晚间 evening | `--color-time-evening` `#9C27B0` | `--color-bg-time-evening` `#F3E5F5` |
| 夜间 night | `--color-time-night` `#3F51B5` | `--color-bg-time-night` `#E8EAF6` |

---

## 三、字体与排版

### 3.1 字体族

| 令牌 | 值 | 用途 |
|---|---|---|
| `--font-sans` | PingFang SC / SF Pro Text / system | 全局默认 |
| `--font-display` | SF Pro Display / PingFang SC | 标题、大数字 |
| `--font-mono` | SF Mono / Roboto Mono / Menlo | 代码、原文 |
| `--font-numeric` | SF Pro Display / DIN Alternate | **所有数字、价格、涨跌幅** |

强制：财务数字、KPI、涨跌幅必须使用 `--font-numeric`，保证等宽对齐。

### 3.2 字号刻度（实测高频值收敛）

移动端档（rpx，基准 375px）：

| 级别 | 值 | 用途 |
|---|---|---|
| 正文 | `24rpx`（80 次） | 卡片正文、列表项 |
| 次要 | `22rpx`（77 次） | 摘要、辅助文字 |
| 小标题 | `28rpx`（47 次） | 区块标题 |
| 标题 | `26rpx`（41 次） | 卡片主标题 |
| 辅助 | `20rpx`（22 次） | 元信息、角标 |
| 大标题 | `30–32rpx` | 页面主标题 |
| 特大 | `36–44rpx` | 数字强调、KPI |

PC 档（px，≥768px）：

| 级别 | 值 | 用途 |
|---|---|---|
| 正文 | `13px`（89 次） | 列表正文 |
| 正文强 | `14px`（53 次） | 卡片正文、右看板 |
| 小标题 | `15px`（39 次） | 区块标题 |
| 辅助 | `11–12px`（105 次） | 元信息、标签、注释 |
| 标题 | `16–18px` | 页面标题、强调 |
| 大数字 | `20–36px` | KPI、评分 |

渲染基线：全局开启 `-webkit-font-smoothing: antialiased`，中文正文行高 1.5–1.6，PC 窄栏 1.4。

---

## 四、圆角系统

分两套刻度。**旧的 rem 令牌（`--radius-sm/md/lg/pill`）已被引用，不得覆盖**；新刻度用独立命名。

移动端档（rpx）：

```
--radius-r-xs:4  --radius-r-sm:6  --radius-r-md:8  --radius-r-lg:12
--radius-r-xl:16 --radius-r-2xl:20 --radius-r-3xl:24 --radius-r-4xl:32
--radius-r-full:999
```

PC 档（px）：

```
--radius-p-xs:3  --radius-p-sm:4  --radius-p-md:6  --radius-p-lg:8
--radius-p-xl:10 --radius-p-2xl:12 --radius-p-3xl:14 --radius-p-4xl:16
--radius-p-5xl:20 --radius-p-full:999
```

使用约定：卡片 12–16rpx / 8–12px；按钮与输入框 36rpx / 22px（胶囊）；标签 pill 用 `full`。

---

## 五、间距与阴影

间距刻度（4 的倍数，PC 用 px、移动用 rpx 双档）：

```
--space-half:2 --space-1:4 --space-2:8 --space-3:12 --space-4:16
--space-5:20 --space-6:24 --space-7:28 --space-8:32 --space-10:40
--space-r-half:4rpx --space-r-1:8rpx --space-r-2:16rpx --space-r-3:24rpx
--space-r-4:32rpx --space-r-5:40rpx --space-r-6:48rpx
```

阴影（仅三级，克制使用）：

| 令牌 | 值 | 用途 |
|---|---|---|
| `--shadow-sm` | `0 0.03125rem 0.25rem rgba(0,0,0,.04)` | 卡片常态 |
| `--shadow-md` | `0 0.0625rem 0.5rem rgba(0,0,0,.05)` | 悬浮、焦点 |
| `--shadow-lg` | `0 0.25rem 1.25rem rgba(0,0,0,.12)` | 弹出层、模态 |

---

## 六、层级（z-index）

| 令牌 | 值 | 层级 |
|---|---|---|
| `--z-base` | 1 | 基础内容 |
| `--z-sticky` | 10 | 吸顶导航 / 列表头 |
| `--z-overlay` | 100 | 下拉、浮层、遮罩 |
| `--z-modal` | 1000 | 模态框、密码门 |

---

## 七、响应式布局

断点仅两个：`768px`、`1200px`。移动优先，逐级增强。

| 断点 | 布局 | 说明 |
|---|---|---|
| `<768px` | 单列 | 底部 tabBar 导航，容器 `padding: 0 24rpx` |
| `≥768px` | 左导航 + 内容 | 侧栏固定 190px，内容区 `max-width: 680px` |
| `≥1200px` | 三栏 | 侧栏 218px，比例 左:中:右 = 2:14:4，右看板 sticky |

共用类（来自 [pc-layout.css](/Users/rick/AlphaReader/frontend/src/styles/pc-layout.css)）：`.page-layout` 外层 flex；`.container` 主内容；`.pc-right-panel` 右看板（<1200px 时 `display:none`）。

右看板子结构：`.right-section` / `.right-section-title` / `.right-news-item`（hover 用 `--color-bg-hover`）/ `.right-news-rank`（品牌色 800 字重）/ `.right-news-title`（2 行截断）/ `.right-news-meta` / `.right-account-row`（`.k` 标签 + `.v` 数值，数值用 `--font-numeric`）。

---

## 八、组件规范

### 8.1 通用组件（components/common）

| 组件 | 用途 | 要点 |
|---|---|---|
| [IconSvg.vue](/Users/rick/AlphaReader/frontend/src/components/common/IconSvg.vue) | 全站线形图标 | props `name` / `size`(默认 1em) / `color`(默认 currentColor)；24×24 viewBox、stroke-width 2；`aria-hidden` |
| [PcSidebar.vue](/Users/rick/AlphaReader/frontend/src/components/common/PcSidebar.vue) | PC 左导航 | 品牌区 + 导航组 + GateButton + 底部设置；active 类 `pc-nav-active` |
| [EmptyState.vue](/Users/rick/AlphaReader/frontend/src/components/common/EmptyState.vue) | 空状态 | 移动 `120rpx 0`、PC `80px 0`；文字 `--color-text-placeholder` |
| [GateButton.vue](/Users/rick/AlphaReader/frontend/src/components/common/GateButton.vue) | 侧门解锁 | 解锁后显现 Stocks / SEPA |
| [ScoreInfoDialog.vue](/Users/rick/AlphaReader/frontend/src/components/common/ScoreInfoDialog.vue) | 评分与信源说明 | z-index 用 `--z-modal` |
| [SettingsDialog.vue](/Users/rick/AlphaReader/frontend/src/components/common/SettingsDialog.vue) | 阅读设置 | 同上 |
| [SiteFooter.vue](/Users/rick/AlphaReader/frontend/src/components/common/SiteFooter.vue) | 页脚 | — |

### 8.2 胶囊搜索栏（强制复用）

详见 [front.md](/Users/rick/AlphaReader/front.md)。新增搜索功能**必须复用** `.vcp-*` 类名体系，禁止另起一套。

结构：`.vcp-filters` → `.vcp-search-section` → `.vcp-search-bar`（+ `.vcp-search-bar-focus`）→ `.vcp-search-input-wrap` → `.vcp-search-icon` / `.vcp-search-input` / `.vcp-search-badge` / `.vcp-search-clear`。可选 `.vcp-dropdown`（z-index 100）、`.vcp-tags` / `.vcp-tag`、`.vcp-overlay`。

规格：胶囊圆角 36rpx（PC 22px），白底，边框 `#e8e8ed`，焦点态边框 `--color-brand` + 蓝色阴影。

### 8.3 业务组件分区

`components/news/`：NewsCard、NewsCardGroup、NewsFilterPopover、NewsSearchBar、TickerOverlay
`components/stocks/`：StocksTabBar、MarketSwitcher、VcpTab、TrendTab、ValueTab、CatalystTab、SandboxTab、StrategyObservationPanel、IndustryConceptFilter、ValueStockAddModal、SandboxPasswordModal、UsStockPlaceholder
`components/sepa/`：SepaKpiPanel、SepaPositionsPanel、SepaWatchlistPanel、SepaDecisionPanel、SepaJournalPanel、SepaGatePanel

图标 name 可用值：`change` / `new` / `eye` / `chart` / `news` / `briefing` / `dot` / `target` / `clipboard` / `warning` / `clock` / `sunrise` / `sun` / `sunset` / `moon` / `calendar` / `close`。

---

## 九、页面与导航

tabBar 两项：简报（`pages/reports/index`）、资讯（`pages/index/index`）。选中色 `#365fda`，未选 `#8590a2`，白底。

其余页面走 `navigateTo`：events/detail、stocks/index、stocks/detail、reports/detail、sepa/index、bookmarks/index。

导航栏统一：`navigationBarBackgroundColor #ffffff`、`navigationBarTextStyle black`、`backgroundColor #f6f7fb`。配置见 [pages.json](/Users/rick/AlphaReader/frontend/src/pages.json)。

---

## 十、交互与状态

| 状态 | 规范 |
|---|---|
| hover | 背景 `--color-bg-hover`，过渡 `0.15s` |
| active/press | 背景 `--color-bg-active-press`（`#e8e8f0`） |
| focus | 边框 `--color-brand` + 蓝色阴影 `--shadow-md` |
| disabled | 文字 `--color-text-placeholder`，禁止交互 |
| 加载 | 骨架屏优先，避免布局跳动 |
| 空态 | 统一用 `EmptyState` 组件 |
| 文本截断 | 多行用 `-webkit-line-clamp`，单行 `text-overflow: ellipsis` |

PC 增强（≥768px）：滚动条宽度 6px、thumb `rgba(0,0,0,.15)`、hover `.25`；`::selection` 背景 `rgba(66,133,244,.2)`。

---

## 十一、当前合规状态（2026-10-13 实测）

| 指标 | 数值 | 状态 |
|---|---|---|
| 全局令牌总数 | 130+ | 良好 |
| 非 App.vue 硬编码色值 | 41 处（原 158） | 已收敛 74% |
| 剩余硬编码文件 | reports/index 12、events/detail 6、stocks-shared.css 5、index/index 4、SandboxTab 2 | 待清理 |
| 圆角散值 | ≤10 种 | 达标 |
| 间距刻度 | 已定义，引用率待提升 | 进行中 |

剩余待办：清理上述 5 个文件的 41 处硬编码；批次 4 间距/字号刻度化；`rgba()` 半透明值与图表系列色（`#a855f7` / `#06b6d4` / `#ec4899` / `#8b5cf6`）是否令牌化待定。

---

## 十二、强制约束（硬性，AI 与人工均须遵守）

### 12.1 硬性禁令（违反即为走偏）

1. **禁止裸色值**：业务 `.vue` / `.css` 中不得出现十六进制色值、不得新增 `rgb()/rgba()` 字面量（阴影除外，须用 `--shadow-*`）。唯一允许写死色值的位置是 [App.vue](/Users/rick/AlphaReader/frontend/src/App.vue) 的 `:root` 令牌定义区。
2. **禁止跨档混用单位**：移动端档只用 `--*-r-*`（rpx），PC 档（`@media min-width:768px`）只用 `--*-p-*`（px），不得互换。
3. **禁止覆盖旧令牌**：`--radius-sm/md/lg/pill`（rem 单位）已被引用，不得改名或改值；新圆角一律用 `--radius-r-*` / `--radius-p-*`。
4. **禁止新造搜索样式**：任何搜索/筛选交互必须复用 `.vcp-*` 类名体系，不得另写一套 `.search-*` / `.filter-*`。
5. **禁止内联 emoji 当图标**：图标一律用 `IconSvg` 的 `name` 枚举（见 8.3），不得用 🟢🔴🟡 等 emoji 传达状态。
6. **禁止写死 z-index**：层级一律用 `--z-base/sticky/overlay/modal`。
7. **禁止只做单端**：任何 UI 变更必须同时验证 `<768px`、`≥768px`、`≥1200px` 三档。
8. **禁止新增断点**：全站只有 768px 与 1200px 两个断点，不得引入 992/1024 等新断点。
9. **禁止新造空态**：空数据一律用 `EmptyState` 组件，不得手写「暂无数据」。
10. **禁止数字用默认字体**：价格、涨跌幅、KPI、评分必须用 `--font-numeric`。

### 12.2 变更流程

| 场景 | 动作 |
|---|---|
| 需要新色值 | 先在 App.vue 定义语义化令牌，再引用；不得就地写死 |
| 需要新圆角/间距 | 先就近收敛到现有刻度，确无匹配才新增令牌 |
| 需要新组件 | 先在本文档 8.x 登记，再实现 |
| 规范本身需变更 | 更新本文档并同步 `AGENTS.md` / `CLAUDE.md` / `claude.context.md` |

### 12.3 提交前自检（8 项）

1. 色值是否全部走 `var(--color-*)`，无裸十六进制。
2. 移动端用 `--*-r-*`（rpx）、PC 用 `--*-p-*`（px），未跨档混用。
3. 数字类文本是否应用 `--font-numeric`。
4. 新增浮层是否使用 `--z-*` 令牌，未写死 z-index。
5. 搜索类交互是否复用 `.vcp-*` 体系，未新造类名。
6. 新增页面是否在 `≥768px` / `≥1200px` 两个断点下验证。
7. 空态是否复用 `EmptyState` 组件。
8. 新增图标是否走 `IconSvg` 的 `name` 枚举，未内联 emoji。

### 12.4 验收命令

```bash
# 硬编码色值残留（目标：仅 App.vue 定义处，其余 0）
grep -rn "#[0-9a-fA-F]\{6\}" /Users/rick/AlphaReader/frontend/src --include=*.vue --include=*.css | grep -v "src/App.vue"

# 写死 z-index（目标：0）
grep -rnE "z-index: *[0-9]+" /Users/rick/AlphaReader/frontend/src --include=*.vue --include=*.css | grep -v "var(--z-"
```
