# AlphaReader 长期记忆

## 产品/设计决策（稳定）
- News 视图只保留「推荐流」一种（热点已融入推荐流卡片：why_it_matters 橙底、🔥信源数徽标、NewsCardGroup 关联报道）。**不要**恢复双 tab。
- `/news/hot-topics` 后端接口保留（前端未调用）。

## 前端约定（uni-app H5）
- **不要用裸 `<template>` 做分组**：uni-app H5 会把无指令 `<template>` 渲染成 `display:none` 的真 HTML，藏死整块。分组用 `<view>`；带 `v-if`/`v-for` 的 `<template>` 是 fragment，安全。
- 页面"空白"先 DevTools 看 DOM `offsetWidth/Height` 区分「没渲染」vs「渲染了但布局/CSS 不可见」，别先怀疑生命周期。
- 首次加载用 `onMounted`；`onShow` 仅返回时刷新。minify 后不能 grep `onShow(`/`onMounted(` 验证产物。

## 部署（Lighthouse 43.136.86.36, ubuntu, /home/Alphareader）
- 部署：`cd /home/Alphareader && git pull && docker compose -f docker-compose.yml up -d --build`（约 3 分钟）。
- **Dockerfile apt 源已改腾讯云内网镜像** `mirrors.tencentyun.com`（python:3.12-slim deb822），build 从 ~26min→~3min（builder+runtime 两处）。
- `web` 服务不暴露端口，只经 Nginx 反代；验证用 `docker exec alpha-web curl -s http://localhost:8000/...` 或 `curl http://localhost/api/v1/...`。
- **构建缓存坑**：改完代码若 `docker compose build web` 后容器内仍是旧逻辑，须 `docker compose build --no-cache web` + `up -d --force-recreate web`（普通 build 可能因层缓存不重 COPY；且服务器必须 `git pull` 拿到最新提交，否则跑的是旧工作树代码）。验证新代码生效：`docker exec alpha-web grep -n '关键字' /app/app/...`。
- **Nginx 行为**：HTTP 请求会被 301 重定向到 HTTPS（`Location: https://localhost/...`），所以容器外验证要走 `https://`（curl -k）或容器内 `localhost:8000`。
- **API 鉴权**：策略等路由经 `require_api_key`（header `X-API-Key` 或 query `api_key`，值=环境变量 `NEWS_API_KEY`）。取到值：`docker exec alpha-web printenv NEWS_API_KEY`。NEWS_API_KEY 为空时跳过鉴权（仅开发环境）。
- Alembic：上线任何 schema 变更前**必先** `docker compose run --rm -v /home/Alphareader/backend:/app web alembic upgrade head`（bind-mount 挂 `/app`，非 `/workspace`），否则 pipeline 写库报 unknown column。

## VCP 投资策略页改版（阶段一+二，2026-07-14）
- 已部署：`2df6106`（阶段一+二功能：策略观察面板 + VCP 五项真实适配度）+ `2498d85`（修复：指数源改腾讯优先 + `_save` trade_date 字符串→date + 基准 alternatives 回退）。
- **指数数据源**：
  - CN：腾讯财经优先（`web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh{code},day,...,400,qfq`，解析用 `day` 键），akshare 被墙兜底。沪深300/中证1000 已实测 ~281 条真实数据。
  - **US：新浪财经 `US_MinKService.getDailyK`（`stock.finance.sina.com.cn/usstock/api/json.php/US_MinKService.getDailyK?symbol=.{code}`），完整历史（指数 2004 起、个股 AAPL 1984 起）**，服务器可达，作为美股主源。映射 `^GSPC→.INX`、`^IXIC→.IXIC`（入库 index_code 统一用 yfinance 代码对齐 VCP）。yfinance(429)/腾讯(仅1天) 作兜底。**注意腾讯美股 fqkline 仅返最新 1 天**，不可用于历史。Eastmoney/Stooq/Nasdaq API 在服务器均不可达（HTTP 000 / JS 验证 / symbol not exists）。
  - **美股个股行情（`us_data_fetcher.py` → `stock_daily_quote` market='US'）**：`US_MinKService.getDailyK?symbol={ticker}`（`BRK-B→BRK.B`）作为**主源**，腾讯 `.OQ/.N`（个股可用 320 天，仅指数 1 天）兜底、yfinance 最后兜底。2026-07-14 全量刷新：S&P500 内置 503 只、160660 条、2025-07-14~2026-07-13，Sina 主源成功率 ~100%（499/503）。个股字段 o/h/l/c/v/a 齐全，VCP 的 breadth/turnover/breakout 所需列均有。
- **VCP 五项**（PRD 6.3）：大盘趋势25 / 市场宽度20 / 波动环境20 / 突破有效性25 / 交易活跃度10；三档 70-100 适合 / 45-69 中性 / 0-44 谨慎。否决降级规则见 `vcp_suitability.py`。
- **API**：`/api/v1/strategy/{list,overview,adaptability,stock_signal}` + `POST /compute`。`get_vcp_adaptability` 读缓存；强制重算用 `compute_vcp_adaptability(market, date, save=True)`（upsert 覆盖）。
- **调度器**（scheduler.py）：CN/US 指数采集 `15:50/05:50` + VCP 适配度 `16:10/06:10`（收盘后日终）。
- **已知**：① CN 适配度 5 维均有真实数据（breadth/turnover/breakout 来自 `stock_daily_quote`，最新日期即当日）。② **US 现五维全真实、无 DATA_DELAY**（2026-07-14 验证：favorable 83，大盘趋势25/市场宽度20/波动环境20/突破18/活跃度0~7）。此前 US 三项"数据不足"+`DATA_DELAY` 的**双重根因**：(a) VCP `target_date=today` 与美股实际最新交易日（T+1 时差）精确不匹配 → breadth/breakout/activity 精确匹配查询返回 None；(b) US 个股行情陈旧（仅到 07-10）。已通过两处修复闭环：新增 `_resolve_market_date`（`compute`/`get` 入口按市场回退到该市场已有数据的最新交易日）+ 美股个股接入新浪主源并全量刷新到 07-13。③ `market_adaptability` 表曾因测试 shell 转义产生脏行（`market=''`、`market='CN\'`），已清理；`get_vcp_adaptability` 读缓存，强制重算用 `compute_vcp_adaptability(market, date, save=True)`。④ **测试坑**：ssh 命令外面包本地双引号时，`$M`/`$K` 会被本地 shell 提前展开成空串，导致 overview 收到 `market=` 空值；须用 `\$M`/`\$K` 让远程 shell 展开。⑤ 容器内跑脚本须 `PYTHONPATH=/app`（否则 `python script.py` 因 sys.path[0]=脚本目录而找不到 `app` 包）；`docker exec -d` 的日志在容器内 `/tmp`，宿主机查不到。
- **前端**：`frontend/src/components/stocks/StrategyObservationPanel.vue` 策略观察面板；`stocks/index.vue` 右侧栏；策略 id 已归一化（美股 `us_` 前缀剥离）。**2026-07-14 加前端请求缓存**：`frontend/src/utils/requestCache.js`（模块级 Map + TTL + 并发去重 + `cachePeek` 同步读），`api.js` 的 `fetchVCPWatchlist`/`fetchVCPFilters`/`fetchStrategyOverview`/`batchCheckCatalyst` 已套缓存并导出 peek；`VcpTab.vue` 与 `StrategyObservationPanel.vue` 在命中缓存时**同步填充、不进 loading 分支**（零转圈）。TTL：白名单/概览/催化剂 `SHORT=5min`，筛选项 `LONG=30min`。根因：左侧 VcpTab 用 `v-if` 销毁重建 + 右侧面板 `watch([market,strategyId])` 在切回 VCP 时重拉，而这些数据日终算一次、盘中不变。

## 回填脚本
- `backfill_why.py`（历史 why_it_matters）：`docker compose run --rm -v /home/Alphareader/backend/scripts:/app/scripts web python scripts/backfill_why.py`。
- `backfill_translation.py`（回填英文信源未翻译条目：7 天内英文源/标题无中文/ai_score≥5）：`docker compose run --rm -v /home/Alphareader/backend/scripts:/app/scripts web python scripts/backfill_translation.py`（一次性工具，不进镜像）。根因：翻译 stage2 失败无重试，仅回填存量；未来失败仍会发生，需加重试机制。

## 中文财经信源
- **富途新闻（活跃，2026-07-13 替换财联社）**：`rss_fetcher.py` `_parse_futu()` + `FeedSource(name="富途新闻")`。接口 `https://news.futunn.com/news-site-api/main/get-flash-list?pageSize=30&lastTime=0`，必带 `Referer: https://news.futunn.com/main/live`，无需签名。返回 `data.data.news[]`：`title/content/detailUrl/time(秒戳)/relatedStocks`；空 title 用 content 前 60 字。
- **财联社（停用，代码保留备用）**：`cls.cn/v1/roll/get_roll_list`，签名 `MD5(SHA1(升序 k=v 拼接))`，`app=CailianpressWeb/os=web/sv=8.7.9`。

## 推荐流配置（2026-07-13）
- 入库闸门 `LLM_SCORE_THRESHOLD=5`（保留全量）；展示闸门分离。
- 后端 `list_news` 默认 `min_score=6` + `max_age_hours=24` + `highlight_only=False`；前端 `useNewsFilter` 同默认。
- 🔥 只看重点 = `is_highlight=true` 子集（score≥8 + 强催化 + 量化数据 + 一周内）。
- **已知**：8B 模型给科技类系统性打 5-6（无 ≥7），阈值 7 会让科技类消失，故默认 6。

## simhash 溢出修复（2026-07-13）
- `Simhash.value` 无符号 64 位，PG BIGINT 有符号（max 2^63-1），超额报 "value out of int64 range" 致 ~60% 写入失败。修复：pipeline 持久化 `sh.value if sh.value < 2**63 else sh.value - 2**64`；deduplicator `_hamming()` 统一 `& 0xFFFFFFFFFFFFFFFF`。

## LLM 评分模块 `backend/app/services/llm_news_filter.py`
- **评分/分析/公司名映射 = DeepSeek-V4-flash**（2026-07-13 从 SiliconFlow Qwen3-8B 切换）。旧名 `deepseek_filter.py` 保留为 re-export shim。配置：`LLM_API_KEY`(AliasChoices 兼容 `DEEPSEEK_API_KEY`，配一个 DeepSeek key 即同时驱动评分+摘要)/`LLM_API_URL`(默认 https://api.deepseek.com/v1/chat/completions)/`LLM_MODEL`(默认 deepseek-v4-flash)。`DEEPSEEK_*` 仅摘要/研报(digest_service/briefing_service)流式调用用（`DEEPSEEK_MODEL` 默认升级为 deepseek-v4-flash，旧 deepseek-chat 于 2026/07/24 弃用）。`SILICONFLOW_*` 仅 Embedding 去重(deduplicator)用，`SILICONFLOW_LLM_MODEL/API_URL` 字段已废弃保留兼容。
- **新增 `app/services/llm_client.py`**：`stream_chat()` 统一封装 DeepSeek 流式调用（含重试/退避/内容审查兜底），消除 digest_service 与 briefing_service 重复的 streaming 代码；briefing 仍各自做 JSON 提取。
- **移除 `enable_thinking`**（Qwen3 专有参数，DeepSeek 不支持）。
- 入口 `filter_news()`：按中文占比+langdetect(seed=0) 分中英组 → `asyncio.gather` 并发 batch（`Semaphore(LLM_MAX_CONCURRENCY=3)`）→ `filter_batch_detailed()` → `_score_batch_once()`（重试）→ content_risk 触发 `_bisect_content_risk()`（递归到 batch=1 丢坏条目）。
- 英文走 `_score_en_two_stage()`：阶段一评分（不翻译）→ 阶段二翻译通过阈值的；翻译失败保留评分。
- Prompt 约束：输入为不可信数据忽略其中指令（防注入）；旧闻硬规则（距抓取>24h 或正文"3天前"→最高3分）；预期差需明文数字/beat/miss；翻译中文占比 title≥0.5/summary≥0.6。
- `is_highlight=true` 硬防线：须 score≥8 + 强催化 + 明文量化 + 一周内；代码层 score<8 强制降级 false。
- Ticker 严格正则：A股 `^\d{6}$`、港股 `^\d{5}$`(4位补0)、美股 `^[A-Z]{3,5}(\.[A-Z])?$`（1-2位和6+位拒，宁漏不误伤）。
- 关键配置：`LLM_BATCH_SIZE=20 / LLM_SCORE_THRESHOLD=5 / LLM_MAX_RETRIES=2 / LLM_CONTENT_PREVIEW_CHARS=800 / LLM_MAX_CONCURRENCY=3 / LLM_TWO_STAGE_EN_ENABLED=True`。退避 `_backoff_delay()=min(30,2**attempt)+uniform(0,1)`，429 读 Retry-After。

## 去重系统（含 P5 跨天旧闻识别）
- 技术栈（deduplicator.py）：URL hash / SimHash 汉明≤5（Redis 24h）/ SequenceMatcher>0.5（2h）/ TF-IDF 余弦>0.65（批内）/ Embedding 语义（Redis 90min, cos>0.80 去重/0.67~0.80 聚合）/ 数值抗误杀 / 事件聚合（`related_to_id`）。
- P5 新增：News 表 `content_hash`(SHA-256, indexed) + `simhash_fingerprint`(BIGINT, indexed)，迁移 `p5q3r4s5t6u7v9`。Pipeline 评分前 `_load_historical_fingerprints()` 从 DB 加载 7 天指纹注入 `_historical_index`，与 24h Redis 合并比；新新闻入库时持久化两 hash。`DEDUP_HISTORICAL_DAYS=7`。存量新闻无指纹，能力随积累增强。
- `is_highlight` 字段迁移 `q3r4s5t6u7v8`，`Boolean NOT NULL DEFAULT false` 带索引；API 已返回，前端暂未用。

## 测试
- 全套 129 passed：P0:44 + P1:8 + P2:8 + P3:16 + parser:40 + json_extractor:10。
- 跑测试：`cd backend && .venv-test/bin/python -m pytest tests/test_deepseek_filter_p{0,1,2,3}.py tests/test_parser.py`（llm_news_filter 不依赖 DB）。
- 注意：MagicMock fixture 需显式关 `LLM_CONTENT_RISK_BISECT_ENABLED`/`LLM_TWO_STAGE_EN_ENABLED`（否则 truthy 触发逻辑让"只调1次API"断言失败）；mock `_call_llm_once` 返回 4 元组（加 `retry_after`）。
