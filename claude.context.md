# AlphaReader 架构与上下文索引 (AI 专用)

## 1. 项目定位与技术栈
* **定位**：面向专业投资人的自动化金融情报系统，核心突出“高频”与“信噪比优先”。
* **后端**：Python FastAPI (纯异步架构) + PostgreSQL 16 (asyncpg 驱动) + Redis 7。
* **前端**：uni-app (Vue 3 组合式 API)。
* **AI 依赖**：DeepSeek V3 (负责评分与翻译) + Embedding API 多提供商 (负责语义去重，默认硅基流动 BAAI/bge-m3 免费，备选智谱)。

## 2. 核心业务闭环 (The Pipeline)
数据流向严格遵循以下 4 步 (`backend/app/services/pipeline.py`)：
1.  **Fetch (多源抓取)**：并发抓取 6 个信源 (财联社、华尔街见闻、MarketWatch 等)，通过 Redis SHA-256 URL 去重。
2.  **Dedup (长短文本四层去重)** (`utils/deduplicator.py`)：
    * 长文本 (>150字)：SimHash (汉明距离≤5) -> 标题包含比对 -> TF-IDF (余弦>0.65) -> Embedding语义 (余弦>0.80)。
    * 短文本 (≤150字)：Embedding语义直接比对 (90分钟窗口)，事件聚合区(0.70~0.80)标记 related_to_id。
    * 前端聚合折叠：related_to_id 驱动父子分组，主卡片展示聚合热度(+0.2/子)，子卡片折叠显示。
3.  **Filter (AI 评分翻译)**：多线程请求 DeepSeek，评分 < 6 分的数据丢弃。英文新闻自动翻译中英双语存储。
4.  **Store (入库)**：PG `INSERT ... ON CONFLICT DO NOTHING`。

## 3. 其他关键模块与算法
* **新闻排序 (Gravity 算法)**：`rank = (ai_score - 1) / (hours_elapsed + 2) ^ 1.8`。
* **RS Rating (相对强度)**：每天 11:30/15:00 触发，使用 akshare -> 腾讯 K线 -> 本地 DB 三级降级策略获取 A 股全市场前复权数据计算。**注意：前端页面已隐藏（代码注释保留），后端定时任务继续运行。**
* **模拟仓 NAV**：四级降级策略获取不复权实时价（新浪实时 -> akshare -> DB -> 历史交易价）。每个交易日 11:35/15:35 自动计算。
* **Daily Screener (Minervini Stage2)**：每个交易日 15:40 自动运行。从全市场 5000+ 只 A 股中，经过 ST 剔除、8 项技术面过滤（均线排列/底部反弹/前高逼近/筹码POC/箱体突破/放量/VCP收缩/大阳线）+ 基本面过滤（扣非净利润>0/营收降幅<10%）+ 商誉防雷，筛出约 30-50 只白名单写入 DB。代码位于 `backend/app/services/screener/`。
* **Stocks 前端页面**：默认 Tab 为「VCP 策略」（含行业/概念板块胶囊搜索筛选器），「模拟仓」需密码验证。RS Rating Tab 已隐藏（代码注释保留）。

## 4. 文件寻址地图 (File Routing)
当你需要修改特定功能时，请直接访问对应路径：
* **API 路由层**：`backend/app/api/v1/*.py` (包含 news, reports, bridge, stocks, sandbox)。
* **服务逻辑层**：`backend/app/services/*.py` (核心业务逻辑，包括抓取、去重、指标计算、调度器等)。
* **Screener 选股**：`backend/app/services/screener/` (data_loader, filters, pipeline, runner)。
* **数据模型库**：`backend/app/models/*.py` (所有 DB 表结构，修改表必须在此同步)。
* **前端页面**：`frontend/src/pages/` (包含 index, reports, stocks 下的 .vue 文件)。
* **前端组件**：`frontend/src/components/` (stocks/StocksTabBar, stocks/SandboxPasswordModal, common/EmptyState, common/SiteFooter)。

## 5. 前端标准化组件规范

### 搜索栏组件 (Capsule Search Bar)
项目统一使用胶囊圆角搜索栏风格，参考实现位于 `frontend/src/pages/stocks/index.vue` 的 VCP 筛选器区域。新增搜索功能时 **必须复用** 以下 CSS 类名体系，禁止另起一套样式。

**HTML 结构模板：**
```html
<view class="vcp-filters">
  <view class="vcp-search-section">
    <view class="vcp-search-bar" :class="{ 'vcp-search-bar-focus': focused }">
      <view class="vcp-search-input-wrap">
        <text class="vcp-search-icon">🔍</text>
        <input class="vcp-search-input" placeholder="搜索..." />
        <!-- 可选：右侧已选数量角标 -->
        <text class="vcp-search-badge">N</text>
        <!-- 可选：清除按钮 -->
        <view class="vcp-search-clear"><text class="vcp-search-clear-icon">×</text></view>
      </view>
    </view>
    <!-- 可选：浮动下拉列表 -->
    <view class="vcp-dropdown">
      <scroll-view scroll-y class="vcp-dropdown-scroll">
        <view class="vcp-dropdown-item">...</view>
      </scroll-view>
    </view>
    <!-- 可选：已选标签 -->
    <view class="vcp-tags"><text class="vcp-tag">标签 ✕</text></view>
  </view>
</view>
```

**核心 CSS 类名速查：**
| 类名 | 用途 |
|---|---|
| `.vcp-filters` | 搜索区容器，提供间距与 z-index 层叠上下文 |
| `.vcp-search-section` | 单个搜索栏区块（含下拉与标签） |
| `.vcp-search-bar` | 搜索栏 flex 行 |
| `.vcp-search-bar-focus` | 焦点态修饰（蓝色边框+阴影） |
| `.vcp-search-input-wrap` | 胶囊圆角输入框容器（白底、36rpx圆角、border） |
| `.vcp-search-icon` | 搜索图标 🔍 |
| `.vcp-search-input` | 输入框本体 |
| `.vcp-search-badge` | 右侧蓝色数量角标 |
| `.vcp-search-clear` / `.vcp-search-clear-icon` | 清除按钮 |
| `.vcp-dropdown` | 浮动下拉弹出层（absolute, z-index:100） |
| `.vcp-dropdown-item` / `.vcp-dropdown-item-active` | 下拉选项 |
| `.vcp-tags` / `.vcp-tag` | 已选标签条 |
| `.vcp-overlay` | 透明全屏遮罩（用于点击外部关闭下拉） |

**设计规格：** 胶囊圆角 36rpx (PC 22px)，白色背景，边框 #e8e8ed，焦点态边框 #4285f4 + 蓝色阴影，移动端与 PC 端均已适配。