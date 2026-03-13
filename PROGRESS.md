# AlphaReader 开发进度记录

## 2026-03-13: News API — 全端点 API Token 鉴权

### 问题/需求
News API 所有端点（公开 GET + Pipeline 管理）均无鉴权保护，任何人可随意调用。

### 解决方案
**1 个文件修改**（`backend/app/api/v1/news.py`）：

| 端点 | 方法 | 改动 |
|------|------|------|
| `GET /news/` | list_news | 新增 `_: str \| None = Depends(require_api_key)` |
| `GET /news/search` | search | 新增 `require_api_key` |
| `GET /news/search/suggest` | search_suggest | 新增 `require_api_key` |
| `GET /news/search/hot` | search_hot | 新增 `require_api_key` |
| `POST /news/pipeline/run` | trigger_pipeline | 新增 `require_api_key` |
| `GET /news/pipeline/status` | pipeline_status | 新增 `require_api_key` |
| `DELETE /news/pipeline/cache` | clear_dedup_cache | 新增 `require_api_key` |

新增导入：`from app.auth import require_api_key`

### 技术要点
- `require_api_key` 来自 `app/auth.py`，已有实现，支持 `X-API-Key` Header 和 `?api_key=` Query 两种方式
- `settings.API_KEY` 为空时自动跳过鉴权（开发环境不受影响）
- 未修改 `auth.py` 和 `config.py`

### 防范措施
- 开发环境不配置 `API_KEY` 时行为不变，零侵入
- 生产环境配置 `API_KEY` 后所有 7 个端点均强制鉴权

---



### 问题/需求
需要一个每日收盘后自动运行的量化筛选脚本，基于 Mark Minervini 趋势交易体系（Stage 2 & VCP），
从全市场 5000+ 只 A 股中筛选出约 50-80 只符合严格技术面 + 基本面条件的准入白名单。

### 解决方案
创建模块化的 `backend/app/services/screener/` 包，包含 4 个核心文件：

| 文件 | 类 | 职责 |
|------|-----|------|
| `data_loader.py` | `DataLoader` | 从 PostgreSQL 加载 OHLCV、从 Parquet 加载/更新 EMA、从 akshare 批量拉取基本面 |
| `filters.py` | `MinerviniScreener` | Stage2 趋势过滤器（8 项量化条件：均线排列/底部反弹/前高逼近/筹码POC/箱体突破/放量/VCP收缩/大阳线） |
| `filters.py` | `FundamentalFilter` | 基本面过滤器（财务防雷/营收驱动/EPS环比加速） |
| `pipeline.py` | `ScreenerPipeline` | 串行管道编排（7 步流水线） |
| `runner.py` | CLI 入口 | 命令行参数支持，`python3 -m app.services.screener.runner` |

### 技术要点
1. **数据复用**：直接从现有 `stock_daily_quote` 表（175 万+行情记录）读取 OHLCV，
   无需额外数据源。EMA 使用增量公式更新，避免全量重算。
2. **性能**：SQL 窗口函数在数据库端完成极值计算；Pandas 向量化处理 5000+ 只股票；
   POC 等需要逐股计算的使用 groupby apply。
3. **容错**：每个过滤步骤独立 try/except；单只股票数据缺失不崩溃；
   基本面拉取失败时跳过基本面过滤。
4. **扩展性**：所有过滤阈值通过 dataclass 配置，支持 CLI 参数覆盖。

### 运行方式
```bash
# 服务器 Docker 环境
docker compose run --rm web python3 -m app.services.screener.runner

# 本地开发（需连 DB）
cd backend && python3 -m app.services.screener.runner --dry-run

# 定时任务（每个交易日 15:35）
35 15 * * 1-5 cd /home/Alphareader && docker compose run --rm web python3 -m app.services.screener.runner >> /tmp/screener.log 2>&1
```

### 输出
- 控制台打印漏斗统计 + Top 20 白名单
- `data/watchlists/watchlist_YYYYMMDD.json`（含 ticker, price, EPS, VCP Score）

### 防范措施
- 所有数据库操作只读（SELECT），不写入任何表
- EMA 快照写入本地文件，不影响线上数据
- akshare 请求带超时和重试

---

## 2026-03-12: Screener V2 — 宽松基本面 + 商誉防雷 + 白名单入库

### 问题/需求
旧策略过于严格（营收同比≥20% + EPS环比加速），导致几乎无股票通过。
需要放宽基本面条件，同时增加商誉防雷，并将筛选结果写入数据库。

### 解决方案
**5 个文件修改**：

| 文件 | 改动 |
|------|------|
| `filters.py` | 旧条件（营收≥20%、EPS加速）注释保留；新增宽松基本面（扣非净利润>0 OR 营收降幅<10%）；新增商誉防雷（商誉/净资产>30%剔除）；B3放量和C2大阳线支持 `[跳过]` 模式 |
| `data_loader.py` | 新增 `load_financial_details()` 从 DB 加载扣非净利润+商誉+净资产；优化基本面数据加载逻辑 |
| `pipeline.py` | 适配新的 `load_financial_details`；B3/C2 默认跳过；漏斗输出中标注 `[跳过]` |
| `runner.py` | CLI 参数适配新配置（`--max-revenue-decline`、`--max-goodwill-ratio`）；旧参数注释保留 |
| `data_fetcher.py` | 增强财务数据获取，支持扣非净利润和商誉字段 |

### 运行结果（2026-03-12）
- 全市场 4945 只 → ST剔除 → 均线+底部+前高+筹码+箱体 → 574 只
- B3放量/C2大阳线跳过 → VCP收敛 38 只 → 商誉防雷 0 剔除 → 基本面通过 **30 只**
- 结果写入 DB `ScreenerRun#7` + 30 条白名单 + JSON 文件

### 防范措施
- 旧的营收驱动和 EPS 加速条件以 `[暂时注释]` 形式保留，后续可快速恢复
- 商誉防雷阈值 30% 可通过 CLI 参数调整
- 宽松条件：两个子条件都缺失数据时放行（防御性设计）

---

## 2026-03-12: VCP 显示优化 + 行业/概念板块筛选

### 问题/需求
1. VCP 分数显示为百分位格式不直观，改为三位小数直接展示原始值
2. VCP 策略页面缺少行业、概念板块筛选功能，用户无法按行业/概念过滤白名单

### 解决方案
**3 个文件修改（409 行新增）**：

| 文件 | 改动 |
|------|------|
| `frontend/src/pages/stocks/index.vue` | VCP 分数 `formatVcp` 从百分位改为三位小数；`vcpClass` 阈值同步调整；新增行业/概念筛选面板（搜索+多选+标签+展开/收起）；列表从 `vcpList` 改为 `vcpFilteredList`；完整移动端+PC 响应式 CSS |
| `frontend/src/utils/api.js` | 新增 `fetchVCPFilters()` 请求 `/api/v1/stocks/vcp_watchlist/filters` |
| `backend/app/api/v1/stocks.py` | 新增 `VCPFilterOptions` 模型；新增 `GET /vcp_watchlist/filters` 端点（返回行业/概念枚举）；`GET /vcp_watchlist` 增加 `industry` + `concepts` 查询参数 |

### 技术要点
1. **前端筛选**：行业精确匹配 `===`，概念包含匹配 `includes()`，支持多选 AND 逻辑
2. **后端筛选**：行业用 SQL `IN` 子句，概念用 `LIKE` OR 组合匹配
3. **响应式**：移动端 rpx 布局 + `@media (min-width: 768px)` PC 适配
4. **枚举动态获取**：从当日白名单数据中提取去重排序的行业/概念列表

### 防范措施
- 筛选为前端二次过滤 + 后端查询参数双重支持，不影响原有数据流
- 概念字段按逗号拆分后去重，兼容多概念逗号分隔格式
- 空选状态显示全量数据，不会误过滤

---

## 2026-03-12: VCP 筛选器 UI 优化

### 问题/需求
1. VCP 筛选器下拉框点击外部区域无法关闭
2. VCP 筛选器样式需要统一为胶囊搜索栏风格，与 RS Rating 搜索组件保持一致

### 解决方案
**2 个文件修改**：

| 文件 | 改动 |
|------|------|
| `frontend/src/pages/stocks/index.vue` | 新增 `.vcp-overlay` 全屏透明遮罩层实现点击外部关闭；重构筛选器为胶囊圆角搜索栏风格（含浮动下拉、已选标签、数量角标）；完整移动端+PC 响应式 CSS |
| `claude.context.md` | 新增"前端标准化组件规范"章节，记录胶囊搜索栏的 HTML 结构模板和 CSS 类名速查表 |

### 技术要点
1. **遮罩层方案**：使用 `position: fixed` 全屏透明 `<view>` 覆盖，`z-index: 50`（低于下拉的 100），点击时关闭所有下拉
2. **组件规范化**：统一 `.vcp-search-*` 类名体系，后续新增搜索功能必须复用
3. **设计规格**：胶囊圆角 36rpx (PC 22px)，白色背景，边框 #e8e8ed，焦点态 #4285f4 蓝色阴影

---

## 2026-03-12: RS Rating 前端隐藏 + Stocks 页面默认 Tab 改为 VCP

### 问题/需求
RS Rating 模块的展示信息不够丰富（缺少行业、概念板块等），为简化先隐藏前端页面。
RS Rating 后端定时计算服务继续运行，前端随时可恢复。

### 解决方案
**2 个文件修改**：

| 文件 | 改动 |
|------|------|
| `frontend/src/components/stocks/StocksTabBar.vue` | 注释掉 RS Rating Tab 入口，只保留「VCP策略」和「模拟仓」两个 Tab |
| `frontend/src/pages/stocks/index.vue` | 默认 `activeTab` 从 `'rs'` 改为 `'vcp'`；RS Rating 整个模板区块用 HTML 注释包裹；`onMounted` 改为默认加载 VCP 数据，RS Rating 数据加载注释掉 |

### 技术要点
1. **后端不动**：`scheduler.py` 中 RS Rating 定时任务（11:30/15:00）继续正常运行
2. **前端可恢复**：RS Rating 相关的 JS 变量、CSS 样式、模板代码均以注释形式保留
3. **默认加载优化**：`onMounted` 直接加载 VCP 数据和筛选项，避免无用的 RS Rating API 请求

### 防范措施
- RS Rating 所有代码以注释保留，恢复时取消注释即可
- 后端 RS Rating 数据持续入库，不影响其他模块（如 VCP）可能的引用
