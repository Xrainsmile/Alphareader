# AlphaReader — 金融情报聚合中台

## 1. 项目概述

AlphaReader 是面向专业投资人的自动化金融情报系统。每小时自动抓取中英文金融新闻源，经三层去重 + DeepSeek AI 评分/翻译后，将高价值新闻存入数据库，通过 Web 前端以"时间衰减热度排序"方式展示。

**核心流程：** 多源采集 → 三层去重 → AI 评分过滤 → 英文翻译 → 入库 → 前端展示

---

## 2. 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | uni-app (Vue 3) | H5 网页，未来可扩展小程序 |
| 后端 | Python FastAPI | 异步高性能，含定时调度 |
| AI | DeepSeek V3 (`deepseek-chat`) | 批量评分/翻译，成本低 |
| 数据库 | PostgreSQL 16 | 结构化存储，asyncpg 异步驱动 |
| 缓存 | Redis 7 | URL 去重 + SimHash 索引持久化 |
| 部署 | Docker Compose | 4 容器：frontend + web + db + cache |
| 服务器 | 腾讯云 Lighthouse | 2 核/4G/6M |
| 反代/HTTPS | Nginx + Let's Encrypt | SSL 证书自动续期 |

---

## 3. 系统架构图

```
┌─────────────── 每小时定时触发 (APScheduler Cron) ───────────────┐
│                                                                   │
│  ┌───────────┐    ┌──────────────┐    ┌─────────────┐   ┌──────┐│
│  │ 8 个信源   │    │ 三层去重引擎  │    │ DeepSeek V3 │   │PostgreSQL│
│  │ 3中文 API  │───→│ L1: SimHash  │───→│ 中文评分     │──→│ UPSERT   │
│  │ 5英文 RSS  │    │ L2: SeqMatch │    │ 英文评分+翻译│   │          │
│  └───────────┘    │ L3: TF-IDF   │    └─────────────┘   └──────┘│
│       │           └──────────────┘          │                │   │
│  Redis URL去重     Redis SimHash索引    score≥6 过滤     URL标记seen│
└───────────────────────────────────────────────────────────────────┘
                              ↓
            ┌──── REST API (FastAPI) ────┐
            │ GET /api/v1/news/          │
            │ sort=hot, gravity=1.8      │
            │ rank=(score-1)/(hours+2)^g │
            └────────────────────────────┘
                              ↓
            ┌──── 前端 (uni-app / Vue 3) ────┐
            │ 排序切换 · 来源筛选 · 评分过滤  │
            │ 热度Badge · 一键生成 Prompt     │
            └─────────────────────────────────┘
```

---

## 4. 数据源（信源）

### 当前活跃信源

| # | 信源 | 类型 | API 方式 | 每次抓取量 |
|---|------|------|----------|-----------|
| 1 | **财联社** | 中文 | JSON API (`cls.cn`) | 30 条 |
| 2 | **新浪财经** | 中文 | JSON API (`feed.mix.sina.com.cn`) | 30 条 |
| 3 | **华尔街见闻** | 中文 | JSON API (`api-one.wallstcn.com`) | 30 条 |
| 4 | MarketWatch | 英文 | RSS Feed | ~20 条 |
| 5 | CNBC World | 英文 | RSS Feed | ~20 条 |
| 6 | CNBC US Markets | 英文 | RSS Feed | ~20 条 |
| 7 | Seeking Alpha | 英文 | RSS Feed | ~20 条 |
| 8 | TechCrunch | 英文 | RSS Feed | ~20 条 |

### 已移除信源（2026-02-11）
- 同花顺、东方财富公告、东方财富快讯、第一财经

---

## 5. Pipeline 完整流程详解

Pipeline 是系统的核心，定义在 `backend/app/services/pipeline.py` 的 `run_pipeline()` 函数中。

### Step 1：多源并发抓取（Fetch）

**文件：** `backend/app/services/rss_fetcher.py`

- 使用 `httpx.AsyncClient` 并发请求所有 8 个信源
- 中文源通过 JSON API 抓取，英文源通过 RSS/Atom XML + `feedparser` 解析
- 每个信源独立 try/except，单源失败不影响其他源
- **预过滤规则：**
  - 标题含「推广/广告/赞助/课程/直播预告/星座/彩票」等关键词 → 丢弃
  - 财联社标题含「研选」→ 丢弃
  - 标题 < 4 字符 → 丢弃
- **Redis URL 去重：** 对每条新闻 URL 做 SHA-256 哈希，检查 Redis Set `alphareader:seen_urls`，已见过的跳过
- **容错机制：** 支持 fallback URL 列表 + 指数退避重试（429/503 时触发）

### Step 2：三层去重（Dedup）

**文件：** `backend/app/utils/deduplicator.py`

不同信源经常报道同一事件，需要消除重复。系统采用三层递进去重：

#### Layer 1：SimHash 指纹（快速粗筛）
- 对标题做 jieba 分词 → 计算 64 位 SimHash 指纹
- 新条目与 Redis 中已有索引逐一比较 Hamming 距离
- **Hamming 距离 ≤ 5 → 判定重复**
- 24 小时滑动窗口，过期条目自动清除

#### Layer 2：SequenceMatcher（精确比较）
- 仅在 SimHash 距离 ≤ 12 时触发（性能优化）
- 清洗标题：去除 `【xxx】` 括号标记 + 标点空格
- 子串包含判断：A 是 B 的子串 → 直接判重
- **SequenceMatcher.ratio() > 0.5 → 判定重复**

#### Layer 3：TF-IDF 余弦相似度（语义级去重）
- 对 L1+L2 幸存者进行批量比较
- 文本构建：`标题×3 + 正文前200字`（加权标题重要性）
- jieba 分词 → TfidfVectorizer(max_features=5000) → 余弦相似度矩阵
- **余弦相似度 > 0.65 → 判定重复**
- 贪婪策略：高优先级信源保留，低优先级被去除

#### 信源优先级（数值越小越优先）
| 优先级 | 信源 |
|--------|------|
| 1 | 财联社 |
| 2 | 华尔街见闻 |
| 3 | 第一财经 |
| 4 | Reuters / MarketWatch |
| 5 | CNBC |
| 6 | Seeking Alpha |
| 7 | TechCrunch |
| 8 | 新浪财经 |

#### Redis 持久化
- `load_index()` — 启动时从 Redis Hash 加载 SimHash 索引
- `save_index()` — 使用原子 RENAME 策略回写（先写临时 key 再 RENAME，避免并发读到空值）

### Step 3：DeepSeek AI 评分与翻译（Filter）

**文件：** `backend/app/services/deepseek_filter.py`

#### 语言分流
- 使用 `langdetect` 自动检测语言，将新闻分为中文组和英文组
- 两组使用不同的 System Prompt

#### 中文新闻评分 Prompt
角色定义为融合 Minervini（趋势交易）/ Buffett（护城河）/ Lynch（基本面）的策略分析师。

**MECE 三维度评分框架：**

| 维度 | 说明 | 高分信号 |
|------|------|---------|
| 企业内生变量 | 财务/业务/治理信息 | 营收超预期、指引上调、毛利改善、技术突破 |
| 外部环境驱动 | 宏观/政策/产业链 | 央行利率变动、行业政策、地缘政治冲击 |
| 非实质性杂音 | 无数据的评论 | ← 这类给低分 |

**输出格式：**
```json
[{"id": 1, "score": 9, "reason": "[内生] 营收同比+35%...", "summary": "≤50字摘要", "tags": ["$AAPL", "财报"]}]
```

#### 英文新闻评分 + 翻译 Prompt
除评分外，额外要求：
- `chinese_title`：翻译标题（≤30 字，纯中文）
- `chinese_summary`：翻译摘要（≤80 字）
- `relevant_tickers`：相关股票代码
- 内置 25+ 金融术语翻译表（Earnings→财报, Fed→美联储 等）

#### 批处理参数
| 参数 | 值 | 说明 |
|------|------|------|
| batch_size | 20 | 每批发送 20 条 |
| temperature | 0.1 | 近确定性输出 |
| max_tokens | 4096 | 响应上限 |
| score_threshold | 6 | < 6 分丢弃 |
| max_retries | 2 | 最大重试次数 |

#### 错误处理
- 内容审查触发（Content Exists Risk）→ 跳过整个 batch，不重试
- 429/500/502/503 → 指数退避重试 `sleep(3 × attempt)`
- 单 batch 失败不影响其他 batch
- `FilterResult.had_errors` 标记是否有 batch 出错

### Step 4：存储入库（Store）

**文件：** `backend/app/services/pipeline.py`

- 使用 PostgreSQL `INSERT ... ON CONFLICT (url) DO NOTHING` 防重复
- 英文新闻使用翻译后的中文标题/摘要存入
- `relevant_tickers` 合并为 `$TICKER` 格式加入 tags
- **逐条 Savepoint** (`session.begin_nested()`)：单条失败不回滚整批

### Step 5：标记已处理（Mark Seen）

- 存储成功的 URL → 标记到 Redis Set `alphareader:seen_urls`
- 低分被过滤的 URL → **仅在 filter 无 batch 错误时**才标记
- 这个设计防止「URL 被标记但数据丢失」的 bug

---

## 6. 定时调度

**文件：** `backend/app/services/scheduler.py`

| 配置项 | 值 | 说明 |
|--------|------|------|
| 频率 | 每小时整点 | Cron: `minute=0, hour=0-23` |
| 时区 | Asia/Shanghai | |
| misfire_grace_time | 600 秒 | 容忍容器冷启动延迟 |
| max_instances | 1 | 同时只允许一个 pipeline 实例 |
| 启动时 | 立即执行一次 | `next_run_time=datetime.now()` |

异常时通过 Webhook 发送告警（支持飞书/钉钉/企业微信/Slack）。

---

## 7. API 接口

### 主要端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/news/` | 新闻列表（支持排序/筛选/分页） |
| POST | `/api/v1/news/pipeline/run` | 手动触发 pipeline |
| GET | `/api/v1/news/pipeline/status` | 查询 pipeline 状态 |
| DELETE | `/api/v1/news/pipeline/cache` | 清除 Redis 去重缓存 |
| GET | `/api/v1/health` | 健康检查 |
| GET | `/debug` | 调试面板（仅 DEBUG 模式） |

### GET /api/v1/news/ 参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `sort` | enum | `hot` | 排序模式：hot / latest / score |
| `limit` | int | 20 | 每页条数（1-100） |
| `offset` | int | 0 | 分页偏移 |
| `min_score` | int | 6 | 最低 AI 评分（0-10） |
| `source` | string | 全部 | 来源筛选 |
| `gravity` | float | 1.8 | 热度衰减因子（0.5-5.0） |
| `max_age_hours` | int | 72 | 最大新闻年龄（小时） |
| `sector` | string | 全部 | 板块/标签筛选 |

### Gravity 热度排序算法

```
rank = (ai_score - 1) / (hours_elapsed + 2) ^ gravity
```

- 改良自 Hacker News 排名算法
- `-1` 使 score=1 的噪音条目排名趋零
- `+2` 防止除零并缓冲前 2 小时
- `gravity=1.8` 适合金融新闻的快速衰减特性

---

## 8. 前端功能

**文件：** `frontend/src/pages/index/index.vue`

### 页面功能
- **排序切换：** 🔥热度 / 🕐最新 / ⭐评分
- **评分筛选：** ≥6 / ≥7 / ≥8 / ≥9
- **时效筛选：** 24h / 48h / 3 天 / 7 天（仅热度模式）
- **来源筛选：** 中文源（财联社/新浪财经/华尔街见闻）+ 英文源（5 个）
- **新闻卡片：** 标题、摘要、来源、评分色值、热度 Badge、相对时间
- **下拉刷新 + 上拉加载更多**
- **一键生成 Prompt：** 将 Top 10 新闻格式化为 Gemini 分析用 Prompt，复制到剪贴板

### 评分色值
| 评分范围 | 颜色 |
|----------|------|
| ≥ 9 | 绿色 |
| ≥ 8 | 橙色 |
| ≥ 7 | 黄橙 |
| < 7 | 淡绿 |

### 热度 Badge
| 热度值 | 颜色 |
|--------|------|
| ≥ 1.0 | 红色（极热） |
| ≥ 0.3 | 橙色（较热） |
| ≥ 0.05 | 绿色（正常） |
| < 0.05 | 灰色（冷却） |

---

## 9. 数据库设计

### news 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | UUID | PK, 自动生成 | 主键 |
| `title` | String(512) | NOT NULL, INDEX | 标题（英文新闻存翻译后的中文） |
| `content` | Text | nullable | 原始正文 |
| `source` | String(128) | NOT NULL, INDEX | 来源名称 |
| `url` | String(2048) | NOT NULL, UNIQUE | 原文链接 |
| `published_at` | DateTime(tz) | nullable | 原始发布时间 |
| `ai_score` | Integer | nullable, INDEX | AI 评分（0-10） |
| `ai_summary` | String(1024) | nullable | AI 摘要 |
| `tags` | ARRAY(String) | nullable | 标签，含 `$TICKER` |
| `created_at` | DateTime(tz) | server_default=now() | 入库时间 |

### 索引
- `ix_news_created_score`: `(created_at DESC, ai_score DESC)` — 热门查询
- `ix_news_source_score`: `(source, ai_score DESC)` — 按源筛选

---

## 10. 部署架构

### Docker Compose 服务

| 容器 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| `alpha-frontend` | Nginx + 前端 dist | 80, 443 | HTTPS 反代 + 静态资源 |
| `alpha-web` | Python FastAPI | 8000（内部） | 后端 API |
| `alpha-db` | postgres:16-alpine | 5432（内部） | 数据库 |
| `alpha-cache` | redis:7-alpine | 6379（内部） | 缓存 |

### 关键环境变量（.env）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | 数据库配置 |
| `DATABASE_URL` | 完整连接串 `postgresql+asyncpg://...` |
| `REDIS_HOST` / `REDIS_PORT` | Redis 连接 |
| `ALERT_WEBHOOK_URL` | 告警 Webhook（飞书/钉钉等） |
| `PIPELINE_START_HOUR` / `PIPELINE_END_HOUR` | 调度时间范围 |

---

## 11. 后端文件索引

| 文件路径 | 职责 |
|----------|------|
| `backend/app/main.py` | FastAPI 应用入口、生命周期、中间件 |
| `backend/app/config.py` | 全局配置（Pydantic Settings） |
| `backend/app/database.py` | 异步数据库引擎 + Session 工厂 |
| `backend/app/redis.py` | Redis 连接池管理 |
| `backend/app/models/news.py` | SQLAlchemy News 数据模型 |
| `backend/app/services/rss_fetcher.py` | **信源抓取**：8 个解析器 + 并发抓取 |
| `backend/app/services/pipeline.py` | **管道编排**：Fetch → Dedup → Filter → Store |
| `backend/app/services/deepseek_filter.py` | **AI 评分**：Prompt + API 调用 + 响应解析 |
| `backend/app/services/scheduler.py` | **定时调度**：APScheduler Cron 任务 |
| `backend/app/services/notifier.py` | **告警通知**：Webhook 多平台推送 |
| `backend/app/utils/deduplicator.py` | **三层去重**：SimHash + SeqMatch + TF-IDF |
| `backend/app/utils/ranking.py` | Gravity 热度排序算法 |
| `backend/app/utils/json_extractor.py` | LLM 响应 JSON 提取器 |
| `backend/app/api/v1/news.py` | 新闻 API 端点 |
| `backend/app/debug_panel.py` | 调试面板（仅 DEBUG 模式） |
| `backend/app/middleware/request_id.py` | 请求 ID 中间件 |
| `backend/app/logging_config.py` | 日志配置（text/json 双格式） |
