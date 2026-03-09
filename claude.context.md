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
* **RS Rating (相对强度)**：每天 11:30/15:00 触发，使用 akshare -> 腾讯 K线 -> 本地 DB 三级降级策略获取 A 股全市场前复权数据计算。
* **模拟仓 NAV**：四级降级策略获取不复权实时价（新浪实时 -> akshare -> DB -> 历史交易价）。

## 4. 文件寻址地图 (File Routing)
当你需要修改特定功能时，请直接访问对应路径：
* **API 路由层**：`backend/app/api/v1/*.py` (包含 news, reports, bridge, stocks, sandbox)。
* **服务逻辑层**：`backend/app/services/*.py` (核心业务逻辑，包括抓取、去重、指标计算、调度器等)。
* **数据模型库**：`backend/app/models/*.py` (所有 DB 表结构，修改表必须在此同步)。
* **前端页面**：`frontend/src/pages/` (包含 index, reports, stocks 下的 .vue 文件)。