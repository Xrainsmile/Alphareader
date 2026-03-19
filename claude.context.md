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
* **Stocks 前端页面**：默认 Tab 为「VCP 策略」（含行业/概念板块胶囊搜索筛选器），「价投」Tab 展示手动录入的价值投资标的，「模拟仓」需密码验证。RS Rating Tab 已隐藏（代码注释保留）。
* **News 分类标签**：新闻分为「财经」和「科技」两个分类。财联社/MarketWatch/Seeking Alpha/Finnhub 归为「财经」；TechCrunch/Hacker News/OpenAI Blog/Google AI Blog/Anthropic/Hugging Face/MIT Tech Review 归为「科技」。前端首页顶部有「全部/财经/科技」三个平铺 Tab 供切换筛选，独立于筛选面板。
* **Sandbox Admin (`/sandbox-admin`)**：纯后端渲染的独立 HTML 管理页面，**不走前端 Vue**。单文件 `backend/app/sandbox_admin.py` 内嵌全部 HTML/CSS/JS。Dashboard cookie 认证（复用 `app.dashboard._verify_token`）。5 个 Tab：观察池 / 录入推演 / 录入交易 / 录入价投 / 净值计算。API 均走 `backend/app/api/v1/sandbox.py` 中 `/sandbox/admin/*` 路径，依赖 `_require_admin` 校验。新增功能应优先在此页面扩展，而非前端 Vue。

## 4. 部署与容器架构
* **服务器**：腾讯云 Lighthouse `43.136.86.36`（广州），4GB 内存，用户 `ubuntu`，项目路径 `/home/Alphareader`。
* **编排**：`docker-compose.yml`，共 4 个容器：

| 容器名 | 服务 | 镜像/构建 | 端口 | 说明 |
|--------|------|-----------|------|------|
| `alpha-frontend` | Nginx + Uni-app H5 | `./frontend/Dockerfile` (node:20-alpine 构建 → nginx:alpine 运行) | 80, 443 | 静态前端 + 反向代理到后端，SSL 证书挂载 certbot |
| `alpha-web` | FastAPI 后端 | `./backend/Dockerfile` (python:3.12-slim) | 无外部暴露 | 仅通过 Nginx 反向代理访问，healthcheck `/api/v1/health` |
| `alpha-db` | PostgreSQL 16 | `postgres:16-alpine` | 无外部暴露 | 数据卷 `pgdata`，仅 Docker 网络内访问 |
| `alpha-cache` | Redis 7 | `redis:7-alpine` | 无外部暴露 | AOF 持久化，maxmemory 256MB，LRU 淘汰，数据卷 `redisdata` |

* **部署命令**：`ssh ubuntu@43.136.86.36 "cd /home/Alphareader && git pull origin main && docker compose up -d --build frontend web"`（按需指定服务名）。

## 5. 文件寻址地图 (File Routing)
当你需要修改特定功能时，请直接访问对应路径：
* **API 路由层**：`backend/app/api/v1/*.py` (包含 news, reports, bridge, stocks, sandbox)。
* **服务逻辑层**：`backend/app/services/*.py` (核心业务逻辑，包括抓取、去重、指标计算、调度器等)。
* **Screener 选股**：`backend/app/services/screener/` (data_loader, filters, pipeline, runner)。
* **数据模型库**：`backend/app/models/*.py` (所有 DB 表结构，修改表必须在此同步)。
* **Sandbox Admin 页面**：`backend/app/sandbox_admin.py` (单文件内嵌 HTML/CSS/JS，后端渲染)。
* **前端页面**：`frontend/src/pages/` (包含 index, reports, stocks 下的 .vue 文件)。
* **前端组件**：`frontend/src/components/` (stocks/StocksTabBar, stocks/SandboxPasswordModal, common/EmptyState, common/SiteFooter)。
