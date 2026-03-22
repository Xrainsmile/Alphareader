# AlphaReader 开发进度记录

## 2026-03-22: Phase 4 — 美股定时任务 + 前端接入真实数据

### 问题/需求
Phase 3 完成了 Screener 市场抽象层，但还缺：(1) 美股定时调度任务（行情更新 + VCP/趋势 Screener），(2) 前端美股 VCP/趋势 Tab 仍为占位组件。

### 解决方案
**4 个文件修改**，完成后端调度 + 前端接入：

| 序号 | 任务 | 涉及文件 | 说明 |
|------|------|----------|------|
| 4.1 | 美股行情定时更新 | `scheduler.py` | 每天 05:30 北京时间（≈美东 16:30 盘后），yfinance 增量更新 |
| 4.2 | 美股 VCP/趋势 Screener 定时任务 | `scheduler.py` | VCP 05:40 + 趋势 05:45，使用 `market="US"` 的 Pipeline |
| 4.3 | 前端美股 VCP Tab 接入真实数据 | `VcpTab.vue`, `index.vue` | VcpTab 新增 `market` prop，替换 UsStockPlaceholder |
| 4.4 | 前端美股趋势 Tab 接入真实数据 | `TrendTab.vue`, `index.vue` | TrendTab 新增 `market` prop，替换 UsStockPlaceholder |

### 修改文件清单

| 文件 | 改动 |
|------|------|
| `services/scheduler.py` | 新增 3 个 async job 函数（`_us_quotes_job`/`_us_screener_job`/`_us_trend_screener_job`）+ 3 个 CronTrigger 注册 + 启动日志 |
| `components/stocks/VcpTab.vue` | 新增 `market` prop（默认 `'CN'`）；`fetchVCPWatchlist`/`fetchVCPFilters` 传递 market 参数 |
| `components/stocks/TrendTab.vue` | 新增 `market` prop（默认 `'CN'`）；`fetchTrendWatchlist`/`fetchTrendFilters` 传递 market 参数 |
| `pages/stocks/index.vue` | 美股 VCP/趋势 Tab 从 `<UsStockPlaceholder>` 替换为 `<VcpTab market="US" />`/`<TrendTab market="US" />`；移除 `usVcpFeatures`/`usTrendFeatures` 预告数据；新增 `usVcpRef`/`usTrendRef` |

### 调度时间设计（北京时间，Asia/Shanghai）

| 任务 | 时间 | 说明 |
|------|------|------|
| 美股行情更新 | 05:30 | 对应美东 16:30 盘后，确保收盘数据可用 |
| 美股 VCP Screener | 05:40 | 行情更新后 10 分钟 |
| 美股趋势 Screener | 05:45 | VCP 之后 5 分钟，避免同时占用资源 |

### 向后兼容
- `VcpTab`/`TrendTab` 的 `market` prop 默认 `'CN'`，A 股 Tab 无需改动，行为与之前完全一致
- 美股催化剂 Tab 保持占位（Phase 5 实现）
- 后端 API 层（`vcp_watchlist`/`trend_watchlist` 端点）已在 Phase 2 完成 market 参数支持

### Lint 检查
- 全部 4 个文件 0 errors, 0 warnings ✅

---

## 2026-03-22: Phase 3 — 美股 Screener 适配（市场抽象层）

### 问题/需求
Phase 2 完成了后端数据基建（数据库 market 字段 + 美股数据获取模块 + API 层市场参数），但 Screener 模块（VCP + 趋势策略）全部硬编码为 A 股逻辑，无法对美股运行筛选。

### 解决方案
**8 个文件修改/新增**，给 Screener 模块添加市场抽象层：

| 序号 | 任务 | 涉及文件 | 说明 |
|------|------|----------|------|
| 3.1 | DataLoader 添加 market 参数 | `data_loader.py` | 4 个 SQL 查询（load_ohlcv/load_today_close/load_price_extremes）加 `WHERE market = :market` |
| 3.2 | ST 过滤条件化 | `pipeline.py`, `trend_pipeline.py` | `market='CN'` 时才查询 ST 股票，美股跳过 |
| 3.3 | DB 写入带 market 字段 | `pipeline.py`, `trend_pipeline.py` | ScreenerRun/WatchlistDaily/TrendScreenerRun/TrendWatchlistDaily 写入时带 market；DELETE 旧数据按 market 过滤 |
| 3.4 | 基本面 bypass for US | `data_loader.py` | `load_fundamentals()` + `load_financial_details()` 美股时返回空 DataFrame |
| 3.5 | enricher 美股分支 | `enricher.py` | 美股时跳过 akshare/东方财富数据补充，字段填充默认值 |
| 3.6 | CLI --market 参数 | `runner.py`, `trend_runner.py` | 新增 `--market CN/US`，传入 pipeline |
| 3.7 | 抽取公共 utils | `utils.py`（新增） | `load_st_codes()` + `load_stock_names()` 从两个 pipeline 抽取到共享模块 |

### 修改文件清单

| 文件 | 改动 |
|------|------|
| `services/screener/data_loader.py` | `DataLoader.__init__` 接受 `market` 参数；4 个 SQL 查询加 `market` 过滤；基本面方法美股 bypass |
| `services/screener/pipeline.py` | `ScreenerPipeline.__init__` 接受 `market`；ST 条件化；enricher 传 market；DB 写入带 market；删除重复方法 |
| `services/screener/trend_pipeline.py` | `TrendPipeline.__init__` 接受 `market`；同上改造 |
| `services/screener/enricher.py` | `enrich_watchlist()` 接受 `market`；美股跳过 akshare 补充 |
| `services/screener/runner.py` | 新增 `--market CN/US` CLI 参数 |
| `services/screener/trend_runner.py` | 新增 `--market CN/US` CLI 参数 |
| `services/screener/utils.py` | **新文件**：`load_st_codes(market)` + `load_stock_names(codes, market)` |
| `services/screener/__init__.py` | 模块文档更新 |

### 向后兼容
- 所有 `market` 参数默认值为 `"CN"`，不传参时行为与改造前完全一致
- A 股定时任务无需修改（默认 CN），美股可通过 `--market US` 启动

### 运行方式
```bash
# A 股（默认，与改造前一致）
python3 -m app.services.screener.runner
python3 -m app.services.screener.trend_runner

# 美股
python3 -m app.services.screener.runner --market US
python3 -m app.services.screener.trend_runner --market US
```

### Lint 检查
- 全部 8 个文件 0 errors, 0 warnings ✅

---

## 2026-03-22: 层级2 — 催化剂标的聚合 × 技术面交叉验证

### 问题/需求
新闻情报和技术面选股之间缺少桥梁。VCP 白名单和新闻催化剂是两个独立运行的孤岛，交叉验证完全靠人肉在两个 Tab 之间切换。

### 部署状态
- ✅ 测试通过：153/153（53 个催化剂新测试 + 100 个原有测试零回归）
- ✅ Git commit: `d152490` (feat) + `c03fe98` (fix: 迁移脚本兼容 asyncpg)
- ✅ 数据库迁移：`news_catalyst_stocks` 表 + 4 个索引 + 唯一约束
- ✅ 后端部署：docker compose build + up（web 容器重建，API 端点已验证）
- ✅ 前端部署：docker compose build + up（frontend 容器重建，CatalystTab 已集成）
- ✅ API 验证：3 个端点（/stocks, /check, /batch_check）全部正常返回

### 解决方案
实现「催化剂标的聚合服务」— 自动化「新闻催化剂 × 技术面」交叉验证：

**后端（4 个新文件 + 3 个文件修改）：**

| 文件 | 说明 |
|------|------|
| `models/catalyst.py` | 新增 `NewsCatalystStock` ORM 模型，存储催化剂标的聚合数据 |
| `services/catalyst_aggregator.py` | 核心聚合服务：高分新闻 → 实体提取 → LLM 公司名映射 → 按 ticker 聚合 → 交叉验证 → 入库 |
| `api/v1/catalyst.py` | 3 个 API 端点：催化剂排行榜 / 单票检查 / 批量检查 |
| `scripts/migrate_catalyst.py` | 数据库迁移脚本 |
| `models/__init__.py` | 注册新模型 |
| `api/v1/router.py` | 注册催化剂路由 |
| `services/scheduler.py` | 注册定时任务（工作日 08:45 盘前 + 15:50 盘后） |

**前端（1 个新文件 + 4 个文件修改）：**

| 文件 | 说明 |
|------|------|
| `components/stocks/CatalystTab.vue` | 新增催化剂 Tab，展示排行榜 + 分类筛选（双确认/强RS/观察池） |
| `components/stocks/StocksTabBar.vue` | 新增「🔥催化剂」Tab 按钮 |
| `pages/stocks/index.vue` | 集成 CatalystTab 组件 |
| `components/stocks/VcpTab.vue` | VCP 白名单标的旁加 🔥 标记 + 展开行催化剂信息 |
| `components/stocks/TrendTab.vue` | 趋势白名单标的旁加 🔥 标记 + 展开行催化剂信息 |
| `utils/api.js` | 新增 `fetchCatalystStocks` / `batchCheckCatalyst` API 函数 |

**核心逻辑流程：**
```
每日新闻(ai_score ≥ 7) → 提取 tags/sentiment_entity 中的公司名
  → LLM 批量映射公司名 → A 股 ts_code（SiliconFlow Qwen3-8B，免费）
  → 按 ticker 聚合（出现次数 × 最高分 = 催化剂热度）
  → 与 VCP/趋势白名单 + RS Rating 交叉验证
  → 分类：🎯 双确认 / 💪 强RS / 👀 观察池
  → 写入 news_catalyst_stocks 表
```

**交叉验证分类说明：**
- `double_confirmed`：催化剂 + 技术面双确认（在 VCP 或趋势白名单中）
- `strong_rs`：催化剂 + RS ≥ 80
- `catalyst_only`：有催化剂但技术面未就绪（观察池）

**定时调度：**
- 08:45 盘前催化剂聚合 → 09:00 盘前研报
- 15:50 盘后催化剂聚合 → 16:00 盘后研报

### 防范措施
- 催化剂聚合失败不影响现有 pipeline（独立服务，try/except 包裹）
- LLM 映射失败时 graceful degradation（只返回空映射，不崩溃）
- 前端 batchCheckCatalyst 失败不影响 VCP/趋势白名单的主功能展示
- 数据库迁移使用 IF NOT EXISTS，幂等安全

---

## 2026-03-21: Phase 3 — 代码整洁（B-7 / B-2 / B-3 / F-4）

### 问题/需求
Code Review Phase 3 四项代码整洁修复：调试脚本清理、API 响应格式统一、Pydantic 输入校验、前端重复代码。

### 解决方案
**4/4 项全部完成**：

| 条目 | 状态 | 说明 |
|------|------|------|
| B-7: 调试脚本散落 | ✅ 已修复 | 根目录调试脚本已删除，运维脚本已整理到 `backend/scripts/`，`.gitignore` 已加 `backend/debug_*.py` |
| B-2: API 响应格式统一 | ✅ 已修复 | 创建 `schemas/response.py` 定义 `APIResponse` / `PaginatedResponse`；所有 API 端点已改用统一包装；前端 `request()` 已内置自动解包 |
| B-3: Pydantic 输入校验 | ✅ 已修复 | briefings/digests 的 `target_date` 改为 `date`，`period_label` 加 `Literal` 约束，stocks backfill 改为 `date` |
| F-4: 前端重复代码 | ✅ 已修复 | `utils/formatters.js` 含 15+ 公共函数，6 个文件引用 |

### B-2 修复详情（本次检查发现遗漏并修复）
另一个 agent 完成了大部分工作，但遗留 5 个端点未改造：
- `stocks.py` 的 `vcp_watchlist` / `trend_watchlist` / `trend_watchlist/filters` / `value_watchlist`（4 个端点仍返回裸 Pydantic model + `response_model` 约束）
- `news.py` 的 `/search`（返回裸字典）
本次修复：移除 `response_model` 约束，统一改用 `APIResponse(data=...)` 包装。

### 修改文件清单

| 文件 | 改动 |
|------|------|
| `backend/app/api/v1/stocks.py` | 4 个端点（vcp_watchlist / trend_watchlist / trend_watchlist/filters / value_watchlist）改用 `APIResponse` 包装；移除 3 个 `response_model` |
| `backend/app/api/v1/news.py` | `/search` 端点改用 `APIResponse` 包装 |
| `doc/code-review-2026-03-20.md` | B-2 标记完成，Phase 3 全部完成 |

---

## 2026-03-21: Phase 2 — 数据可靠性（M-1 / M-2 / M-3 / B-9）

### 问题/需求
Code Review Phase 2 四项数据可靠性修复：缺失索引、冗余索引、列类型修正、连接池回收。

### 解决方案
**全部 4 项在之前的开发中已修复**，本次仅验证并更新文档：

| 条目 | 状态 | 说明 |
|------|------|------|
| M-1: 缺失索引 | ✅ 已修复 | pipeline_runs.started_at、news.tags GIN、watchlist/trend 复合索引均已存在 |
| M-2: 冗余索引 | ✅ 已修复 | sandbox_nav 和 stock_daily_quote 的冗余索引已清理 |
| M-3: 列类型不当 | ✅ 已修复 | reports.date→Date、volume→BigInteger、nav/pnl→Numeric(16,4)、score→Numeric(3,1) |
| B-9: pool_recycle | ✅ 已修复 | database.py 已有 `pool_recycle=3600` + `pool_pre_ping=True` |

### 修改文件清单（0 个代码改动，仅文档更新）

| 文件 | 改动 |
|------|------|
| `doc/code-review-2026-03-20.md` | Phase 2 四项标记为已完成 |

---

## 2026-03-21: Phase 1 — 安全加固（S-1 / S-2 / S-3 / S-4 / I-1 / B-5 / B-6）

### 问题/需求
Code Review Phase 1 六项安全加固：API Key 泄露检查、时序攻击防护、DEBUG 默认值、500 响应信息泄露、Redis 密码、CORS 收紧、敏感字段 repr。

### 解决方案
**2 个文件修改 + 4 项确认已修复**：

| 条目 | 状态 | 说明 |
|------|------|------|
| S-1: API Key 泄露风险 | ✅ 已验证 | `git log --all -- .env` 无历史提交，密钥从未泄露 |
| S-2: API Key 时序攻击 | ✅ 本次修复 | `auth.py:41` 改用 `hmac.compare_digest()` |
| S-3: `DEBUG=True` 默认值 | ✅ 已修复 | `config.py:39` 已为 `False` |
| S-4: 500 暴露内部异常 | ✅ 已修复 | briefings/digests 返回通用错误信息，详细错误仅写日志 |
| I-1: Redis 无密码 | ✅ 已修复 | docker-compose.yml 已配置 `--requirepass` |
| B-5: CORS 过宽 | ✅ 本次修复 | origins 限定域名 + methods/headers 从 `*` 收紧为具体值 |
| B-6: repr=False | ✅ 已修复 | 所有 10 个敏感字段均已使用 `Field("", repr=False)` |

### 修改文件清单（2 个）

| 文件 | 改动 |
|------|------|
| `backend/app/auth.py` | `!=` → `hmac.compare_digest()` |
| `backend/app/main.py` | CORS `allow_methods`/`allow_headers` 从 `["*"]` 收紧 |

---

## 2026-03-21: Phase 5 — 基础设施优化（I-2 / I-3 / I-5 / T-1）

### 问题/需求
Code Review Phase 5 四项基础设施优化：Backend Dockerfile 过大、Docker 无内存限制、Nginx 无速率限制、缺少 CI/CD。

### 解决方案
**7 个文件新增/修改**：

| 文件 | 改动 |
|------|------|
| `backend/Dockerfile` | 多阶段构建：builder 编译 C 扩展 → runtime 仅复制 venv + 最小运行时库 |
| `backend/requirements.txt` | 移除 pytest/pytest-asyncio/aiosqlite（测试依赖） |
| `backend/requirements-dev.txt` | 新增：`-r requirements.txt` + 测试依赖，CI 和本地开发使用 |
| `docker-compose.yml` | 为 4 个服务添加 `mem_limit`（web 1536m / db 768m / cache 384m / frontend 128m） |
| `deploy/nginx/conf.d/default.conf.template` | 添加两级速率限制 zone + AI 端点单独限流 |
| `.github/workflows/ci.yml` | 新增 GitHub Actions CI（后端 pytest + 前端 build 检查） |
| `doc/code-review-2026-03-20.md` | 更新 I-2/I-3/I-5/T-1 状态为 ✅，Phase 5 checklist 全勾 |

### I-2: Backend Dockerfile 多阶段构建
- **Stage 1 (builder)**：`python:3.12-slim` + gcc/g++/libpq-dev 等编译工具，pip 安装到 `/opt/venv`
- **Stage 2 (runtime)**：`python:3.12-slim` + 仅 `libpq5/libxml2/libxslt1.1/curl` 运行时库
- **效果**：最终镜像减小 ~200MB（移除 gcc/g++/dev headers/pip 缓存）
- **附带**：测试依赖分离到 `requirements-dev.txt`，生产镜像不含 pytest

### I-3: Docker 资源限制
| 服务 | `mem_limit` | 说明 |
|------|-------------|------|
| web (FastAPI) | 1536m | pandas/sklearn 重计算需要内存 |
| db (PostgreSQL) | 768m | 主数据库，需充足缓存 |
| cache (Redis) | 384m | maxmemory 256mb + AOF 缓冲 |
| frontend (Nginx) | 128m | 纯静态服务，极低内存 |
| **合计** | ~2.8GB | 为 OS 和突发预留 ~1.2GB |

### I-5: Nginx 速率限制
- **通用 API** (`/api/`): `30r/m` per IP, burst=15, nodelay
- **AI 生成端点** (`/api/v1/(briefings|digests)/generate`): `3r/m` per IP, burst=2, nodelay
- 超限返回 `429 Too Many Requests`
- AI 端点使用 regex location 优先匹配，timeout 提升到 180s

### T-1: GitHub Actions CI
- **触发条件**: push（main/feat/*/fix/*）+ PR（main）
- **Backend Tests job**: PostgreSQL 16 + Redis 7 服务容器，Python 3.12，`pytest -v`
- **Frontend Lint job**: Node.js 20，`npm run build:h5` 编译检查
- **优化**: pip 缓存、并发控制（同分支取消旧 run）、10 分钟超时

### 防范措施
- Dockerfile 多阶段构建保持 CMD 完全一致，运行行为不变
- `mem_limit` 使用 docker-compose v2 语法（`mem_limit` 而非 `deploy.resources`），兼容直接 `docker compose up`
- Nginx 速率限制对内部服务（scheduler 触发的 API 调用）不受影响（走 Docker 内网，不经 Nginx）
- CI 配置中 `API_KEY=""` 确保测试不受鉴权影响

---

## 2026-03-21: F-7 — CSS 变量系统替换全局硬编码颜色

### 问题/需求
Code Review 指出前端 15+ 个 Vue 文件中散布 300+ 处硬编码颜色值（`#1a1a2e`、`#8c8c9a`、`#4285f4` 等），维护困难且无法统一换肤。需引入 CSS Custom Properties（设计 Token）系统统一管理。

### 解决方案
**16 个文件修改**：

| 文件 | 改动 |
|------|------|
| `App.vue` | 新建 `:root` 变量体系：65+ CSS 变量（基础色/文字色/品牌色/语义色/状态背景/边框/渐变色/时段色/字体/圆角/阴影） |
| `pages/index/index.vue` | ~60 处替换：color/background/border/gradient → var(--xxx) |
| `pages/stocks/index.vue` | ~85 处替换：全部 18 种颜色角色 + 渐变 + 字体 |
| `pages/stocks/detail.vue` | ~28 处替换 |
| `pages/reports/index.vue` | ~36 处替换 + 时段色变量 |
| `pages/reports/detail.vue` | ~7 处替换 |
| `pages/briefing/detail.vue` | ~15 处替换 + 渐变背景 |
| `components/stocks/StocksTabBar.vue` | ~5 处替换 |
| `components/stocks/SandboxPasswordModal.vue` | ~11 处替换 |
| `components/stocks/ValueStockAddModal.vue` | ~24 处替换 |
| `components/stocks/TrendTab.vue` | 模板 prop bg 替换 |
| `components/stocks/ValueTab.vue` | 模板 prop bg 替换 |
| `components/stocks/VcpTab.vue` | 模板 prop bg 替换 |
| `components/common/SiteFooter.vue` | ~3 处替换 |
| `components/common/EmptyState.vue` | ~1 处替换 |

### CSS 变量分类

```
:root {
  /* 基础色 (8) */    --color-bg / bg-card / bg-secondary / bg-hover / bg-active / bg-input / bg-tag / bg-code
  /* 文字色 (8) */    --color-text-primary / secondary / tertiary / body / muted / placeholder / hint / white
  /* 品牌色 (5) */    --color-brand / brand-alt / brand-light / brand-hover / brand-ios
  /* 语义色 (13) */   --color-up / up-alt / down / down-alt / warning / warning-alt / info / info-hover / success-dark / success-text / danger-dark / neutral / neutral-light
  /* 状态背景 (13) */ --color-bg-success-light / success-soft / info-light / info-soft / info-accent / info-blend / danger-light / neutral-light / neutral-soft / brand-light / dropdown-hover / tag-hover / active-press / section / subtle
  /* 边框 (6) */      --color-border / border-light / border-hover / border-divider / border-subtle / border-separator
  /* 渐变 (12) */     --gradient-vcp-hot/warm/normal/cool, --gradient-sentiment-xxx, --gradient-info-bar/bg, --gradient-briefing-bg
  /* 时段色 (7) */    --color-time-morning/midday/evening/night + bg 变体
  /* 字体 (4) */      --font-sans / display / mono / numeric
  /* 圆角 (4) */      --radius-sm / md / lg / pill
  /* 阴影 (3) */      --shadow-sm / md / lg
}
```

### 迁移结果
- **迁移前**: 300+ 处硬编码 hex 颜色值散布在 15+ 个 Vue 文件
- **迁移后**: 439 处 `var(--xxx)` 引用 → 65+ 个集中变量定义
- **合理保留**: 9 处不可替换（SandboxTab.vue SVG 内联属性 + JS 动态颜色数组 + mask-image 黑色遮罩）
- **Lint 错误**: 0

### 技术要点
1. **uni-app 全局样式**: `App.vue` 的 unscoped `<style>` 定义 `:root` 变量，所有页面/组件自动继承
2. **渐变色变量**: `linear-gradient()` 值直接存储为变量（如 `--gradient-vcp-hot`），`background: var(--gradient-vcp-hot)` 生效
3. **模板 prop**: EmptyState 的 `bg` prop 传入 `var(--color-bg-card)` 字符串，通过 `:style="{ background: bg }"` 正确解析
4. **批量替换**: 使用 `find + xargs + sed` 对 15+ 文件批量替换，配合手动 `replace_in_file` 处理复杂场景

### 防范措施
- 所有变量值保持与原硬编码值完全相同，视觉效果零变化
- SVG 内联属性和 JS 动态颜色保持原值，不强制迁移
- `mask-image` 中的 `#000` 为技术用途（遮罩），不归入设计 Token

---

## 2026-03-21: F-1 — index/index.vue 重构为 `<script setup>` + 子组件拆分

### 问题/需求
`index/index.vue` 是项目中唯一使用 Options API 的页面（2207 行），违反 `claude.rules.mdc` 第四章前端规范。需要重构为 `<script setup>` 组合式 API，并拆分为多个子组件降低单文件复杂度。

### 解决方案
**11 个文件新增/修改**：

| 文件 | 类型 | 职责 |
|------|------|------|
| `utils/formatters.js` | 新增 | 公共格式化工具（scoreClass/formatScore/formatTime/gravityClass/sentimentClass 等），多页面可复用 |
| `composables/useNewsFeed.js` | 新增 | 新闻 Feed composable（列表加载、分页、聚合分组、关联报道展开） |
| `composables/useNewsSearch.js` | 新增 | 搜索 composable（搜索模式、搜索历史、热门话题、搜索结果分页） |
| `composables/useNewsFilter.js` | 新增 | 筛选 composable（排序/时效/来源/评分筛选 + 面板临时状态 + 分类 Tab） |
| `components/news/NewsCard.vue` | 新增 | 单条新闻卡片（复用于普通列表和搜索结果，支持高亮/Gravity/情绪指标） |
| `components/news/NewsCardGroup.vue` | 新增 | 聚合卡片组（主卡片 + 关联报道折叠区） |
| `components/news/NewsSearchBar.vue` | 新增 | 搜索栏 + 搜索面板（历史/热门话题）+ 搜索结果列表 |
| `components/news/NewsFilterPopover.vue` | 新增 | 筛选按钮 + 浮窗面板（排序/时效/来源/评分） |
| `pages/index/index.vue` | 重写 | Options API → `<script setup>`，引用 4 个子组件 + 3 个 composable |

### 架构变化
```
旧：1 个 2207 行巨型 Options API 文件
新：
├── index.vue（~280 行模板 + 组装逻辑）
├── composables/
│   ├── useNewsFeed.js（数据加载）
│   ├── useNewsSearch.js（搜索逻辑）
│   └── useNewsFilter.js（筛选逻辑）
├── components/news/
│   ├── NewsCard.vue（单卡片）
│   ├── NewsCardGroup.vue（聚合卡片）
│   ├── NewsSearchBar.vue（搜索栏）
│   └── NewsFilterPopover.vue（筛选面板）
└── utils/formatters.js（公共工具）
```

### 技术要点
1. **`<script setup>`**：严格遵守 claude.rules 第四章规范，所有 Vue 组件使用组合式 API
2. **uni-app 页面生命周期**：通过 `getCurrentInstance().proxy.$options` 挂载 onShow/onHide/onPullDownRefresh/onReachBottom
3. **子组件样式穿透**：父组件通过 `:deep()` 选择器控制子组件样式，保持 scoped CSS 隔离
4. **composable 解耦**：筛选参数通过 `buildFilterParams()` 传递给 Feed，搜索和 Feed 互不干扰
5. **公共 formatters**：scoreClass/formatTime 等从各页面可复用，为后续 F-4（消除重复代码）做准备

### 防范措施
- 所有 API 调用、事件上报、Clipboard 逻辑保持与原版完全一致
- CSS 样式通过 `:deep()` 穿透保持子组件渲染效果不变
- 原有的 PC/移动端响应式适配（768px/1200px 断点）完整保留

---

## 2026-03-20: Daily Briefing — 每日收盘智能简报

### 问题/需求
需要一个每日收盘后自动生成的智能市场简报，整合新闻、行情、策略白名单、价投观察池、模拟仓表现等多维度数据，由 DeepSeek AI 分析生成结构化日报，供用户快速了解当日市场全貌和操作建议。

### 解决方案
**8 个文件新增/修改**：

| 文件 | 类型 | 职责 |
|------|------|------|
| `app/models/daily_briefing.py` | 新增 | DailyBriefing ORM 模型（日期、内容、token数、耗时等） |
| `app/models/__init__.py` | 修改 | 导出 DailyBriefing 模型 |
| `app/services/briefing_service.py` | 新增 | 核心服务：7 大数据源收集 + DeepSeek prompt 构建 + AI 生成 + 入库 |
| `app/api/v1/briefings.py` | 新增 | REST API（GET 列表 + GET 详情 + POST 手动触发） |
| `app/api/v1/router.py` | 修改 | 注册 briefings 路由 |
| `app/services/scheduler.py` | 修改 | 新增每日 16:00 定时任务自动生成简报 |
| `app/services/data_fetcher.py` | 修改 | 增强数据获取支持 briefing 所需字段 |
| `alembic/versions/l1m2n3o4p5q6_add_daily_briefings_table.py` | 新增 | 数据库迁移脚本 |

### 数据源（7 大维度）
1. **新闻概览**：当日 morning + midday 两批新闻摘要
2. **VCP 策略白名单**：当日筛选结果（价格/涨跌/VCP得分/RS/EMA120）
3. **趋势跟踪白名单**：突破追踪标的（价格/MA50/RS）
4. **价投观察池**：长期持仓标的的当日表现和入选理由
5. **模拟仓**：净值/盈亏/仓位/持仓明细
6. **大盘行情**：上证/深证/创业板/科创板/北证指数
7. **RS Rating Top 20**：相对强度排名前 20 标的

### 技术要点
1. **AI 分析**：DeepSeek V3 模型，结构化 prompt 引导输出 5 大板块（大盘→策略→价投→模拟仓→明日关注）
2. **容错机制**：最多 3 次重试（指数退避），单数据源失败不影响整体报告
3. **涨跌幅精度**：统一 `.2f` 格式化，入选理由为空时显示"暂无"
4. **成本控制**：每次生成约 ¥0.02-0.03（~700 prompt tokens + ~1000 output tokens）
5. **定时触发**：工作日 16:00（screener 15:40-15:45 完成后）

### 验证结果（2026-03-20）
- ✅ dry-run 数据收集正常：morning 50 条 + midday 50 条新闻，价投 2 标的，模拟仓净值 0.9839
- ✅ 完整生成成功：2105 字符，53.8s，报告质量高
- ✅ 涨跌幅精度修复：`-0.198...%` → `-0.20%`
- ✅ 数据库迁移成功（alembic stamp + upgrade head）

### 防范措施
- 所有数据库读操作使用现有 Session，写入仅限 `daily_briefings` 新表
- DeepSeek API 调用带重试和超时保护
- 定时任务独立于现有 screener/news pipeline，互不影响

**Commit**: d9fbec0 (branch: feat/daily-briefing)

---

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
