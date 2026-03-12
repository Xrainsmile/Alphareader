# AlphaReader 开发进度记录

## 2026-03-09: Daily Screener — Minervini Stage2 白名单筛选模块

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
