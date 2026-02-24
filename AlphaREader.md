# AlphaReader — 高频金融情报聚合平台

> **最后更新：2026-02-24**
> **Slogan：** 高频金融情报 · 信噪比优先

## 1. 项目概述

AlphaReader 是面向专业投资人的自动化金融情报系统。每 15 分钟自动抓取中英文金融新闻源，经**长短文本路由四层去重** + **DeepSeek AI 评分/翻译**后，将高价值新闻存入数据库，通过 Web 前端以"时间衰减热度排序"方式展示。同时提供 **A 股 RS 相对强度排行**和**每日复盘报告**功能。

**核心流程：** 多源采集 → 长短文本路由四层去重 → AI 评分过滤 → 英文翻译 → 入库 → 前端展示

---

## 2. 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | uni-app (Vue 3) | H5 网页，未来可扩展小程序 |
| 后端 | Python FastAPI | 异步高性能，含定时调度 |
| AI 评分 | DeepSeek V3 (`deepseek-chat`) | 批量评分/翻译，成本低 |
| AI 去重 | 智谱 Embedding-3 (256 维) | 短文本语义去重 + 长文本标题语义去重 |
| 数据库 | PostgreSQL 16 | 结构化存储，asyncpg 异步驱动，全文搜索 (TSVECTOR) |
| 缓存 | Redis 7 | URL 去重 + SimHash 索引 + Embedding 索引持久化 |
| 部署 | Docker Compose | 4 容器：frontend + web + db + cache |
| 服务器 | 腾讯云 Lighthouse | 2 核/4G/6M |
| 反代/HTTPS | Nginx + Let's Encrypt | SSL 证书自动续期 |

---

## 3. 系统架构图

```
┌──────────── 定时调度 (APScheduler) ────────────────────────────┐
│                                                                  │
│  news_pipeline: 每15分钟 (0:00~23:00)                           │
│  ┌──────────┐    ┌───────────────────┐   ┌──────────┐  ┌─────┐ │
│  │ 6 个信源  │    │ 四层去重引擎       │   │DeepSeek  │  │ PG  │ │
│  │ 2中文 API │───→│ 长文本：SimHash    │──→│ 中文评分  │─→│UPSERT│ │
│  │ 4英文 RSS │    │  +标题相似度+TF-IDF│   │ 英文评分  │  │     │ │
│  └──────────┘    │  +标题语义(智谱)   │   │  +翻译   │  └─────┘ │
│       │          │ 短文本：智谱Emb     │   └──────────┘    │     │
│  Redis URL去重    └───────────────────┘    score≥6过滤  URL标记  │
│                                                                  │
│  rs_rating: 周一~五 11:30 & 15:00                               │
│  ┌──────────┐    ┌──────────────┐    ┌─────┐                    │
│  │ akshare  │───→│ 4周期ROC加权  │───→│ PG  │                    │
│  │ A股日线   │    │ 百分位排名1~99│    │写入 │                    │
│  └──────────┘    └──────────────┘    └─────┘                    │
│                                                                  │
│  sandbox_nav: 周一~五 15:35（模拟仓净值计算）                   │
└──────────────────────────────────────────────────────────────────┘
                             ↓
┌──────────── REST API (FastAPI) ───────────────────────────────┐
│ News: 列表(Gravity排序) / 全文搜索(混合排序+高亮) / 热门话题    │
│ Bridge: Gemini Prompt 生成 (Top 66 条新闻 → 策略分析 Prompt)   │
│ Reports: 每日复盘报告 CRUD (Bearer Token 鉴权)                 │
│ Stocks: RS Rating 排行(≥80) / 股票搜索(代码/名称/拼音首字母)   │
│ Sandbox: 净值曲线 / 观察池 / 推演 / 交易                        │
└───────────────────────────────────────────────────────────────┘
                             ↓
┌──────────── 前端 (uni-app / Vue 3) ──────────────────────────┐
│ 首页: 新闻Feed + 筛选面板 + 全文搜索                           │
│ 复盘: 报告列表 + Markdown详情渲染                               │
│ 股票: RS Rating排行 + 搜索 + 模拟仓Tab                          │
│ 彩蛋: 三击Logo → 复制Gemini分析Prompt到剪贴板                   │
└───────────────────────────────────────────────────────────────┘
```

---

## 4. 数据源（信源）

### 当前活跃信源（2026-02-19）

| # | 信源 | 类型 | API 方式 | 每次抓取量 |
|---|------|------|----------|-----------|
| 1 | **财联社** | 中文 | JSON API (`cls.cn`) | 30 条 |
| 2 | **华尔街见闻** | 中文 | JSON API (`api-one.wallstcn.com`) | 30 条 |
| 3 | MarketWatch | 英文 | RSS Feed | ~20 条 |
| 4 | Seeking Alpha | 英文 | RSS Feed | ~20 条 |
| 5 | TechCrunch | 英文 | RSS Feed | ~20 条 |
| 6 | Finnhub | 英文 | REST API (`finnhub.io`) | ~30 条 |

### 已移除信源
- 同花顺、东方财富公告、东方财富快讯、第一财经（2026-02-11）
- 新浪财经、CNBC World、CNBC US Markets（2026-02-19）

---

## 5. Pipeline 完整流程详解

Pipeline 是系统的核心，定义在 `backend/app/services/pipeline.py` 的 `run_pipeline()` 函数中。

### Step 1：多源并发抓取（Fetch）

**文件：** `backend/app/services/rss_fetcher.py`

- 使用 `httpx.AsyncClient` 并发请求所有 6 个信源
- 中文源通过 JSON API 抓取，英文源通过 RSS/Atom XML + `feedparser` 解析，Finnhub 通过 REST API
- 每个信源独立 try/except，单源失败不影响其他源
- **预过滤规则：**
  - 标题含「推广/广告/赞助/课程/直播预告/星座/彩票」等关键词 → 丢弃
  - 财联社标题含「研选」→ 丢弃
  - 标题 < 4 字符 → 丢弃
- **Redis URL 去重：** 对每条新闻 URL 做 SHA-256 哈希，检查 Redis Set `alphareader:seen_urls`，已见过的跳过
- **容错机制：** 支持 fallback URL 列表 + 指数退避重试（429/503 时触发）

### Step 2：长短文本路由四层去重（Dedup）

**文件：** `backend/app/utils/deduplicator.py`

不同信源经常报道同一事件，需要消除重复。系统采用**长短文本路由**策略，根据"清洗后标题+正文"长度做分流：

#### 【长文本通道】长度 > 150 字 → 四层去重

**Layer 1：SimHash 指纹（快速粗筛）**
- 对标题+正文做 jieba 分词 → 计算 64 位 SimHash 指纹
- 新条目与 Redis 中已有索引逐一比较 Hamming 距离
- **Hamming 距离 ≤ 5 → 判定重复**
- 24 小时滑动窗口，过期条目自动清除

**Layer 2：SequenceMatcher 标题相似度（精确比较）**
- 对 **2 小时内所有索引**逐条执行，不受 SimHash 汉明距离限制
- 清洗标题：去除 `【xxx】` 括号标记 + 标点空格
- 子串包含判断：A 是 B 的子串 → 直接判重
- **SequenceMatcher.ratio() > 0.5 → 判定重复**

**Layer 3：TF-IDF 余弦相似度（当前批次内部比对）**
- 文本构建：`标题×3 + 正文前200字`（加权标题重要性）
- jieba 分词 → TfidfVectorizer(max_features=5000) → 余弦相似度矩阵
- **余弦相似度 > 0.65 → 判定重复**
- 贪婪策略：高优先级信源保留，低优先级被去除

**Layer 4：标题语义去重（跨批次跨源跨措辞）**
- 对 L3 幸存者的标题调用**智谱 Embedding-3** 获取 256 维向量
- 与 Embedding 索引（含短文本历史）做余弦相似度比对
- 与当前批次已通过的幸存者做批内比对
- **余弦相似度 > 0.85 → 判定重复**
- 0.78~0.85 灰度区域 → 数值抗误杀检测
- 有效识别不同措辞描述同一事件的情况（如中英文翻译差异、改写）

#### 【短文本语义通道】长度 ≤ 150 字（金融快讯等）
- 调用**智谱 Embedding-3** API 获取 256 维向量，计算余弦相似度
- 仅与过去 90 分钟内的短文本向量对比
- **余弦相似度 > 0.85 → 判定重复**
- 0.78~0.85（灰色地带）→ 数值抗误杀检测：提取核心数值实体，若数值集合不同 → 保留
- **降级策略：** 若 API 调用失败，回退到 SequenceMatcher 标题相似度

#### 信源优先级（数值越小越优先，2026-02-19）
| 优先级 | 信源 |
|--------|------|
| 1 | 财联社 |
| 2 | 华尔街见闻 |
| 3 | 第一财经 |
| 4 | Reuters / MarketWatch |
| 6 | Seeking Alpha |
| 7 | TechCrunch |
| 8 | Finnhub |

#### Redis 持久化
- `alphareader:simhash_index` — 24 小时 SimHash 索引（Redis Hash）
- `alphareader:embedding_index` — 90 分钟短文本 Embedding 索引（Redis Hash）
- 写入均采用"先写临时 key → 原子 RENAME"策略

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

## 6. RS Rating 相对强度排行

**文件：** `backend/app/services/indicators.py` + `backend/app/services/data_fetcher.py`

### 算法（IBD/Minervini 方法）
1. 通过 akshare 获取 A 股全市场前复权日线数据（回溯 365 天）
2. 计算 4 个周期的涨跌幅 (ROC)：3 月(63 日) / 6 月(126 日) / 9 月(189 日) / 12 月(252 日)
3. 加权得分：`Score = 0.4×P3 + 0.2×P6 + 0.2×P9 + 0.2×P12`
4. 全市场百分位排名映射为 **1~99**（99 = 最强）
5. 结果写入 `stock_rs_rating` 表

### 数据缓存策略
- 当天已有数据则从 PostgreSQL 直接加载，不重新下载
- `stock_daily_quote` 表缓存前复权日线行情

---

## 7. Context Bridge — AI Prompt 生成

**文件：** `backend/app/services/context_bridge.py`

从当天 ai_score >= 6 的新闻中取 Top 66 条，组装成**对冲基金首席策略师**角色的 Markdown Prompt，供用户复制给 Gemini/大模型使用。

Prompt 输出结构要求：
1. **市场图谱与情绪博弈** — 核心驱动力 + 情绪定性
2. **核心投资信号挖掘** — 2-3 个 High-Conviction Signals
3. **风险雷达** — 显性/隐性风险 + 合规预警
4. **短线情绪展望** — 下周展望 + 观察哨位

前端彩蛋：**三击 Logo** 触发 Prompt 复制到剪贴板。

---

## 8. 定时调度

**文件：** `backend/app/services/scheduler.py`

| 任务 | 频率 | 说明 |
|------|------|------|
| `news_pipeline` | 每天 0:00~23:00，每 15 分钟 | 新闻抓取+评分 Pipeline，启动时立即执行一次 |
| `rs_rating` | 周一至周五 11:30, 15:00 | A 股 RS Rating 计算 |
| `sandbox_nav` | 周一至周五 15:35 | 模拟仓净值计算（基于收盘价） |

| 配置项 | 值 |
|--------|------|
| 时区 | Asia/Shanghai |
| misfire_grace_time | 600 秒（容忍容器冷启动延迟） |
| max_instances | 1（防止重复触发） |

异常时通过 Webhook 发送告警（支持飞书/钉钉/企业微信/Slack）。

---

## 9. API 接口

### 全部端点

| 方法 | 路径 | 说明 |
|------|------|------|
| **Health** | | |
| GET | `/api/v1/health` | 健康检查（验证 PG + Redis 连通性） |
| **News** | | |
| GET | `/api/v1/news/` | 新闻列表（排序/筛选/分页） |
| GET | `/api/v1/news/search` | 全文搜索（混合排序: ts_rank_cd × ln(ai_score) × 时间衰减） |
| GET | `/api/v1/news/search/suggest` | 搜索自动补全 |
| GET | `/api/v1/news/search/hot` | 热门话题标签（24h 内高分新闻高频标签 Top 8） |
| POST | `/api/v1/news/pipeline/run` | 手动触发 pipeline（后台执行） |
| GET | `/api/v1/news/pipeline/status` | 查询 pipeline 状态 |
| DELETE | `/api/v1/news/pipeline/cache` | 清除 Redis 去重缓存 |
| **Bridge** | | |
| GET | `/api/v1/bridge/generate_prompt` | 生成 Gemini 结构化提示词 |
| **Reports** | | |
| GET | `/api/v1/reports/` | 复盘报告列表（日期倒序） |
| GET | `/api/v1/reports/{id}` | 单篇报告详情 |
| POST | `/api/v1/reports/sync` | 上传/更新报告（Bearer Token 鉴权） |
| DELETE | `/api/v1/reports/{id}` | 删除报告（需鉴权） |
| **Stocks** | | |
| GET | `/api/v1/stocks/rs_rating` | RS Rating 排行榜（支持 target_date/top_n/min_rating） |
| POST | `/api/v1/stocks/rs_rating/compute` | 手动触发 RS Rating 计算 |
| GET | `/api/v1/stocks/rs_rating/status` | 计算任务状态查询 |
| GET | `/api/v1/stocks/search` | 股票搜索（代码/名称/拼音首字母） |
| **Sandbox** | | |
| GET | `/api/v1/sandbox/overview` | 模拟仓概览（净值曲线/收益指标） |
| GET | `/api/v1/sandbox/stocks` | 观察池列表（含最新推演摘要） |
| GET | `/api/v1/sandbox/stocks/{id}` | 单只股票详情（推演卡片流 + 交易记录） |
| POST | `/api/v1/sandbox/admin/stocks` | 新增观察池股票（管理端） |
| DELETE | `/api/v1/sandbox/admin/stocks/{id}` | 移除观察池股票（管理端） |
| POST | `/api/v1/sandbox/admin/analyses` | 新增推演记录（管理端） |
| POST | `/api/v1/sandbox/admin/trades` | 新增交易记录（管理端） |
| POST | `/api/v1/sandbox/nav/compute` | 计算净值（管理端/定时） |

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

### 搜索混合排序算法

```
final_score = ts_rank_cd(文本相关度) × ln(ai_score + 1) × 1/(hours+2)^0.5
```

---

## 10. 前端功能（5 个页面）

### 首页 — 新闻 Feed
**文件：** `frontend/src/pages/index/index.vue`

- **排序切换：** Gravity 热度 / 最新 / 评分
- **评分筛选：** ≥6 / ≥7 / ≥8 / ≥9
- **时效筛选：** 24h / 48h / 3 天 / 7 天 / 不限
- **来源筛选：** 中文源（财联社/华尔街见闻）+ 英文源（MarketWatch/Seeking Alpha/TechCrunch/Finnhub）
- **全文搜索：** 搜索历史 + 热门话题 + 高亮结果
- **新闻卡片：** 标题、摘要、来源、评分色值、热度 Badge、相对时间
- **下拉刷新 + 上拉加载更多**
- **三击 Logo 彩蛋：** 生成 Gemini 分析 Prompt 复制到剪贴板

### 复盘列表
**文件：** `frontend/src/pages/reports/index.vue`
- 每日复盘报告列表，API 优先加载，本地 Mock 兜底

### 复盘详情
**文件：** `frontend/src/pages/reports/detail.vue`
- Markdown 渲染报告详情（mp-html 组件）

### RS 排行
**文件：** `frontend/src/pages/stocks/index.vue`
- RS Rating > 80 的股票排行榜
- 股票搜索（代码/名称/拼音首字母，如 "GZMT" 匹配 "贵州茅台"）
- 模拟仓 Tab：净值曲线、收益指标、观察池快照

### 模拟仓详情
**文件：** `frontend/src/pages/stocks/detail.vue`
- 单只观察池股票详情：推演记录、交易记录、风控信息

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

## 11. 数据库设计

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
| `search_vector` | TSVECTOR | GIN INDEX | 全文搜索向量 |
| `created_at` | DateTime(tz) | server_default=now() | 入库时间 |

### reports 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK, 自增 | 主键 |
| `sync_id` | String | UNIQUE | 同步 ID（外部系统标识） |
| `title` | String | NOT NULL | 报告标题 |
| `date` | Date | NOT NULL | 报告日期 |
| `cover` | String | nullable | 封面图 URL |
| `summary` | Text | nullable | 摘要 |
| `content` | Text | NOT NULL | Markdown 正文 |

### stock_daily_quote 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts_code` | String | 股票代码 |
| `trade_date` | Date | 交易日期 |
| `open/high/low/close` | Float | OHLC 价格 |
| `pct_change` | Float | 涨跌幅 |
| `turnover_rate` | Float | 换手率 |

### stock_rs_rating 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts_code` | String | 股票代码 |
| `trade_date` | Date | 计算日期 |
| `p3/p6/p9/p12` | Float | 3/6/9/12 月涨跌幅 |
| `score` | Float | 加权得分 |
| `rs_rating` | Integer | 1~99 百分位排名 |

### sandbox_stocks 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键 |
| `ts_code` | String | 股票代码 |
| `name` | String | 股票名称 |
| `status` | String | watching/holding/exited |
| `reason` | Text | 加入观察池理由 |
| `added_at` | DateTime(tz) | 加入时间 |
| `updated_at` | DateTime(tz) | 更新时间 |

### sandbox_analyses 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键 |
| `stock_id` | Integer | 关联观察池股票 |
| `ts_code` | String | 股票代码 |
| `score` | Float | 综合评分（0~5） |
| `trend` | String | 趋势判断 |
| `pattern` | String | 形态识别 |
| `volume_price` | String | 量价行为 |
| `discipline_action` | String | 纪律动作（retain/gray/research/churn） |
| `risk_type` | String | 风险类型（top/bottom，可空） |
| `risk_price` | Float | 风控价格（可空） |
| `risk_note` | String | 风控备注（可空） |
| `pnl_thinking` | String | 亏盈思考 |
| `verdict` | String | 哨子结论 |
| `created_at` | DateTime(tz) | 创建时间 |

### sandbox_trades 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键 |
| `stock_id` | Integer | 关联观察池股票 |
| `ts_code` | String | 股票代码 |
| `action` | String | buy/sell |
| `price` | Numeric | 成交价 |
| `shares` | Integer | 股数 |
| `trade_date` | Date | 交易日期 |
| `note` | Text | 交易备注 |
| `created_at` | DateTime(tz) | 创建时间 |

### sandbox_nav 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键 |
| `trade_date` | Date | 交易日期 |
| `total_market_value` | Numeric | 持仓总市值 |
| `cash` | Numeric | 现金余额 |
| `nav` | Float | 单位净值 |
| `total_pnl` | Float | 累计盈亏% |
| `created_at` | DateTime(tz) | 创建时间 |

- 初始现金：61,908.99 元（持仓市值按最新价格计算）

### 关键索引
- `ix_news_created_score`: `(created_at DESC, ai_score DESC)` — 热门查询
- `ix_news_source_score`: `(source, ai_score DESC)` — 按源筛选
- `ix_news_search_vector`: GIN 索引 — 全文搜索

---

## 12. 部署架构

### Docker Compose 服务

| 容器 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| `alpha-frontend` | Nginx + 前端 dist | 80, 443 | HTTPS 反代 + 静态资源 |
| `alpha-web` | Python FastAPI | 8000（内部） | 后端 API |
| `alpha-db` | postgres:16-alpine | 5432（内部） | 数据库 |
| `alpha-cache` | redis:7-alpine (256MB LRU) | 6379（内部） | 缓存 |

### 部署命令

```bash
cd /home/Alphareader
git pull origin main
docker compose build web        # 后端
docker compose build frontend   # 前端
docker compose up -d web frontend
```

### 关键环境变量（.env）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `ZHIPU_API_KEY` | 智谱 API 密钥（Embedding-3 去重） |
| `FINNHUB_API_KEY` | Finnhub API 密钥 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | 数据库配置 |
| `DATABASE_URL` | 完整连接串 `postgresql+asyncpg://...` |
| `REDIS_HOST` / `REDIS_PORT` | Redis 连接 |
| `ALERT_WEBHOOK_URL` | 告警 Webhook（飞书/钉钉等） |
| `PIPELINE_START_HOUR` / `PIPELINE_END_HOUR` | 调度时间范围 |
| `REPORT_SYNC_TOKEN` | 报告同步 Bearer Token |

---

## 13. 后端文件索引

| 文件路径 | 职责 |
|----------|------|
| **入口/配置** | |
| `backend/app/main.py` | FastAPI 应用入口、生命周期、中间件 |
| `backend/app/config.py` | 全局配置（Pydantic Settings） |
| `backend/app/database.py` | 异步数据库引擎 + Session 工厂 |
| `backend/app/redis.py` | Redis 连接池管理 |
| `backend/app/logging_config.py` | 日志配置（text/json 双格式） |
| **数据模型** | |
| `backend/app/models/news.py` | News 数据模型（含 TSVECTOR 全文搜索） |
| `backend/app/models/report.py` | Report 复盘报告模型 |
| `backend/app/models/stock.py` | StockDailyQuote + StockRSRating 模型 |
| `backend/app/models/sandbox.py` | 模拟仓（观察池/推演/交易/NAV）模型 |
| **API 路由** | |
| `backend/app/api/v1/router.py` | API 路由注册 |
| `backend/app/api/v1/news.py` | 新闻 API 端点 |
| `backend/app/api/v1/bridge.py` | Context Bridge Prompt 生成 |
| `backend/app/api/v1/reports.py` | 复盘报告 CRUD |
| `backend/app/api/v1/stocks.py` | RS Rating + 股票搜索 |
| `backend/app/api/v1/sandbox.py` | 模拟仓 API 端点 |
| `backend/app/api/v1/health.py` | 健康检查 |
| **服务层** | |
| `backend/app/services/pipeline.py` | **管道编排**：Fetch → Dedup → Filter → Store |
| `backend/app/services/rss_fetcher.py` | **信源抓取**：6 个解析器 + 并发抓取 |
| `backend/app/services/deepseek_filter.py` | **AI 评分**：Prompt + API 调用 + 响应解析 |
| `backend/app/services/search.py` | **全文搜索**：PostgreSQL TSVECTOR + 混合排序 |
| `backend/app/services/context_bridge.py` | **Prompt 生成**：Top 66 新闻 → 策略分析 Prompt |
| `backend/app/services/data_fetcher.py` | **A 股数据**：akshare 行情获取 + PG 缓存 |
| `backend/app/services/indicators.py` | **RS Rating**：4 周期 ROC 加权百分位计算 |
| `backend/app/services/scheduler.py` | **定时调度**：APScheduler Cron 任务 |
| `backend/app/services/notifier.py` | **告警通知**：Webhook 多平台推送 |
| **工具层** | |
| `backend/app/utils/deduplicator.py` | **四层去重**：SimHash + 标题相似度 + TF-IDF + 智谱语义 |
| `backend/app/utils/ranking.py` | Gravity 热度排序算法 |
| `backend/app/utils/json_extractor.py` | LLM 响应 JSON 提取器 |
| `backend/app/middleware/request_id.py` | 请求 ID 中间件 |
| `backend/app/sandbox_admin.py` | 模拟仓管理后台（HTML 页面） |
| `backend/app/debug_panel.py` | 调试面板（仅 DEBUG 模式） |
