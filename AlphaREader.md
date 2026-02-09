# 项目名称：AlphaReader - 金融情报中台 (MVP)

## 1. 项目概述 (Overview)
这是一个面向专业投资人的自动化金融情报系统。
**当前阶段目标：** 完成 **模块 A (新闻智能聚合)** 和 **模块 C (Gemini 预处理桥接)**。
**核心逻辑：** 1.  自动抓取全网金融新闻。
2.  使用 DeepSeek API 进行低成本、高精度的清洗和评分（过滤掉 90% 的噪音）。
3.  将高价值新闻转化为结构化的 Prompt Context，供用户一键复制发送给 Google Gemini 进行深度分析。

## 2. 技术栈架构 (Tech Stack)

### 基础设施 (Tencent Cloud)
* **计算资源:** 腾讯云轻量应用服务器 (LightHouse) - 2核/4G/6M (性价比最高)。
* **容器化:** Docker + Docker Compose (单机编排，易于迁移)。
* **数据库:** PostgreSQL (运行在 Docker 中，存储新闻与结构化数据)。
* **缓存/队列:** Redis (运行在 Docker 中，用于去重和任务队列)。

### 后端 (Python)
* **框架:** FastAPI (高性能 Async IO)。
* **任务调度:** APScheduler (定时抓取) 或 Celery (异步处理)。
* **HTTP请求:** `httpx` (异步客户端)。
* **ORM:** Prisma Client Python 或 SQLAlchemy (Async)。

### AI 核心 (DeepSeek)
* **模型:** `deepseek-chat` (DeepSeek-V3)。
* **用途:** 批量新闻洗稿、相关性评分、关键实体提取。
* **优势:** 成本约为 GPT-4 的 1/50，推理速度极快，适合高频调用。

### 前端 (Client)
* **框架:** Uni-app (Vue 3) - 发布为 H5 网页 + 微信小程序。
* **托管:** 腾讯云 Webify 或 Nginx (部署在 LightHouse)。

## 3. 详细功能模块设计 (Specs)

### 🏗️ 模块 A：DeepSeek 驱动的新闻流水线 (The Pipeline)

**流程逻辑：**
`RSS/API 源` -> `去重(Redis)` -> `规则初筛(Regex)` -> `DeepSeek 批处理(API)` -> `入库(PG)`

**Step 1: 采集与去重 (Fetch & Dedupe)**
* 使用 `feedparser` 抓取财联社、格隆汇、36Kr 等主流金融 RSS。
* **Cursor 指令:** "Implement an async RSS fetcher. Use Redis sets to store `url_hash`. Only process new URLs. If title contains '盘前' or '收盘', keep it; if contains '推广', drop it."

**Step 2: DeepSeek 批量清洗 (Batch Filtering)**
* **策略:** 不要一条一条调 API。每攒够 20 条新闻标题+摘要，发送一次 API 请求。
* **System Prompt:** "你是一个资深金融分析师。我会给你 20 条新闻摘要。请判断哪些对'A股/港股/美股'有实质性财务影响。忽略口水文、政策喊话和无数据新闻。返回 JSON 格式：`[{id: 1, score: 9, reason: '含具体营收数据'}, ...]`"
* **代码指令:** "Create a service `DeepSeekFilter`. It should buffer incoming news items. When buffer size >= 20, send a prompt to `https://api.deepseek.com/v1/chat/completions`. Parse the JSON response and discard items with score < 6."

### 🌉 模块 C：Gemini 桥接层 (The Context Bridge)

**核心痛点解决:** 投资人需要把筛选过的新闻喂给 Gemini 做深度推理，但手动复制粘贴效率太低。

**功能 1: 动态 Context 生成器**
* **后端接口:** `GET /api/v1/generate_prompt?sector=新能源&date=today`
* **逻辑:** 1.  从数据库查询当天该板块 Score Top 10 的新闻。
    2.  拼接成一段结构化文本（Markdown）。
    3.  加上一段 "Meta-Prompt"（引导 Gemini 如何思考）。

**功能 2: 剪贴板优化 (前端)**
* **前端交互:** 增加一个 "✨ 复制为 Gemini 资料" 按钮。
* **输出格式示例:**
    ```text
    # Role: 金融助手
    # Context: 以下是今日[新能源]板块的关键异动：
    1. [宁德时代] 净利润同比增长 20%... (来源: 财联社)
    2. [比亚迪] 宣布新的出海计划...
    
    # Task:
    请基于上述信息，分析该板块下周的短线情绪，并给出 3 个潜在的风险点。
    ```

## 4. 数据库设计 (Schema)
* **Table `news`:**
    * `id`: UUID
    * `title`: String
    * `content`: Text
    * `source`: String
    * `published_at`: DateTime
    * `ai_score`: Int (0-10)
    * `ai_summary`: String (DeepSeek 生成的一句话摘要)
    * `tags`: Array<String> (e.g., ["新能源", "财报"])

## 5. 部署说明 (Deployment)
* 提供 `docker-compose.yml` 文件，包含服务：`web` (FastAPI), `db` (Postgres), `cache` (Redis)。
* 后端使用 `uvicorn` 启动。
* DeepSeek API Key 通过环境变量 `DEEPSEEK_API_KEY` 注入。


P1 — 近期推进（功能完善） 
4. 新闻列表 API 增加分页（offset + limit 或 cursor-based） 
5. Scheduler 启动后立即执行一次 pipeline 
6. 前端 H5 对接后端 API（目前前端是 uni-app 空壳？需确认前端完成度）

P2 — 后续优化 
7. CORS 生产环境白名单配置 
8. SimHash 索引的原子更新（Redis RENAME 替代 delete + rewrite） 
9. 数据库迁移从 create_all 切换到 Alembic 
10. 日志接入（腾讯云 CLS 或 ELK） 
11. 监控告警（pipeline 失败通知）