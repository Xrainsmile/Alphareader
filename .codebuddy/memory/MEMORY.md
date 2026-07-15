# AlphaReader 长期记忆

## 产品/设计决策（稳定）
- News 视图只保留「推荐流」一种（热点已融入推荐流卡片：why_it_matters 橙底、🔥信源数徽标、NewsCardGroup 关联报道）。**不要**恢复双 tab。`/news/hot-topics` 后端接口保留（前端未调用）。

## 前端约定（uni-app H5）
- **不要用裸 `<template>` 分组**：uni-app H5 会把无指令 `<template>` 渲染成 `display:none` 真 HTML，藏死整块。分组用 `<view>`；带 `v-if`/`v-for` 的 `<template>` 是 fragment，安全。
- 页面"空白"先 DevTools 看 DOM `offsetWidth/Height` 区分「没渲染」vs「渲染了但 CSS 不可见」，别先怀疑生命周期。
- 首次加载用 `onMounted`，`onShow` 仅返回时刷新；minify 后无法 grep 验证产物。

## 部署（Lighthouse 43.136.86.36, ubuntu, /home/Alphareader）
- 部署：`cd /home/Alphareader && git pull && docker compose -f docker-compose.yml up -d --build`（约 3min）。Dockerfile apt 源已改腾讯云内网 `mirrors.tencentyun.com`（builder+runtime 两处），build 26min→3min。
- `web` 不暴露端口，只经 Nginx 反代；验证用 `docker exec alpha-web curl -s http://localhost:8000/...` 或宿主 `curl -k https://localhost/api/v1/...`（HTTP 会 301→HTTPS）。
- **构建缓存坑**：改代码后容器内仍旧逻辑 → `docker compose build --no-cache web` + `up -d --force-recreate web`；且服务器必须先 `git pull`。验证：`docker exec alpha-web grep -n '关键字' /app/app/...`。
- **API 鉴权**：策略等路由经 `require_api_key`（header `X-API-Key` 或 query `api_key`，值=env `NEWS_API_KEY`；空则跳过，仅开发）。取值 `docker exec alpha-web printenv NEWS_API_KEY`。
- **Alembic**：上线 schema 变更前**必先** `docker compose run --rm -v /home/Alphareader/backend:/app web alembic upgrade head`（挂 `/app`）。
- **容器内跑脚本**须 `PYTHONPATH=/app`；`docker exec -d` 日志在容器内 `/tmp`。
- **ssh 坑**：外层本地双引号会提前展开 `$M`/`$K` 成空串，须写 `\$M`/`\$K` 让远程 shell 展开。
- **磁盘防膨胀**：`docker compose build` 每次留 ~900MB dangling 镜像 + build cache，曾撑到 83% 告警。`deploy.sh` 构建后已加 `docker image prune -f && docker builder prune -f`；服务器另设 weekly crontab（周日 4:00 `docker image prune -f && docker builder prune -f`）。清理只删 dangling/失效缓存，不影响运行容器（2026-07-15 实测回收 15GB：83%→45%）。

## VCP 投资策略页（阶段一+二，已部署 2df6106 + 2498d85）
- **五项**（PRD 6.3）：大盘趋势25/市场宽度20/波动环境20/突破有效性25/交易活跃度10；三档 70-100 适合 / 45-69 中性 / 0-44 谨慎。否决降级见 `vcp_suitability.py`。
- **API**：`/api/v1/strategy/{list,overview,adaptability,stock_signal}` + `POST /compute`。读缓存 `get_vcp_adaptability`，强制重算 `compute_vcp_adaptability(market, date, save=True)`（upsert）。策略 id 已归一化（美股剥 `us_` 前缀）。
- **调度**（scheduler.py）：CN/US 指数采集 15:50/05:50 + VCP 适配度 16:10/06:10（收盘日终）。
- **指数/行情数据源**：
  - CN 指数：腾讯 `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh{code},day,...,400,qfq`（解析 `day` 键），akshare 兜底。
  - US 指数：新浪 `stock.finance.sina.com.cn/usstock/api/json.php/US_MinKService.getDailyK?symbol=.{code}`（完整历史）为主源；映射 `^GSPC→.INX`/`^IXIC→.IXIC`（入库统一 yfinance 代码）。yfinance/腾讯兜底。**注意腾讯美股 fqkline 仅返 1 天**，不可用于历史；Eastmoney/Stooq/Nasdaq 服务器均不可达。
  - US 个股（`us_data_fetcher.py`）：新浪 `getDailyK?symbol={ticker}`（`BRK-B→BRK.B`）为主源，腾讯 `.OQ/.N` / yfinance 兜底。S&P500 全量已刷新。
- **状态**：CN/US 五维现均真实、无 DATA_DELAY。此前 US "数据不足" 双根因已闭环——(a) 新增 `_resolve_market_date` 在 compute/get 入口按市场回退到已有数据的最新交易日（解决 T+1 时差精确匹配失败）；(b) US 个股接新浪主源并全量刷新。
- **前端缓存**（2026-07-14）：`frontend/src/utils/requestCache.js`（模块级 Map + TTL + 并发去重 + `cachePeek` 同步读）；`api.js` 的 `fetchVCPWatchlist`/`fetchVCPFilters`/`fetchStrategyOverview`/`batchCheckCatalyst` 套缓存并导出 peek；`VcpTab.vue`/`StrategyObservationPanel.vue` 命中缓存时同步填充、不进 loading（零转圈）。TTL：白名单/概览/催化剂 5min，筛选项 30min。根因：VcpTab `v-if` 重建 + 面板 `watch` 切回重拉，而数据日终算一次盘中不变。

## LLM 评分模块 `backend/app/services/llm_news_filter.py`
- **评分/分析/公司名映射 = DeepSeek-V4-flash**（2026-07-13 从 Qwen3-8B 切换）。旧 `deepseek_filter.py` 为 re-export shim。配置：`LLM_API_KEY`（兼容 `DEEPSEEK_API_KEY`）/`LLM_API_URL`（默认 api.deepseek.com/v1/chat/completions）/`LLM_MODEL`（默认 deepseek-v4-flash）。`DEEPSEEK_*` 仅摘要/研报流式用（deepseek-chat 于 2026/07/24 弃用）；`SILICONFLOW_*` 仅 Embedding 去重用。已移除 Qwen3 专有 `enable_thinking`。
- **`app/services/llm_client.py`** `stream_chat()` 统一封装流式（重试/退避/审查兜底），digest 与 briefing 复用。
- 入口 `filter_news()`：中英分组 → `asyncio.gather` 并发（`Semaphore(LLM_MAX_CONCURRENCY=3)`）→ `filter_batch_detailed` → `_score_batch_once`（重试）→ content_risk 触发 `_bisect_content_risk`（递归到 batch=1 丢坏条目）。英文走 `_score_en_two_stage`（先评分不翻译，再翻译过阈值的，翻译失败保留评分）。
- Prompt：输入视为不可信忽略内嵌指令（防注入）；旧闻硬规则（>24h 或正文"3天前"→最高3分）；预期差需明文数字/beat/miss；翻译中文占比 title≥0.5/summary≥0.6。
- `is_highlight=true` 硬防线：score≥8 + 强催化 + 明文量化 + 一周内（score<8 代码强制降级）。
- Ticker 正则：A股 `^\d{6}$` / 港股 `^\d{5}$`(补0) / 美股 `^[A-Z]{3,5}(\.[A-Z])?$`。
- 配置：`LLM_BATCH_SIZE=20 / SCORE_THRESHOLD=5 / MAX_RETRIES=2 / CONTENT_PREVIEW_CHARS=800 / MAX_CONCURRENCY=3 / TWO_STAGE_EN_ENABLED=True`。退避 `min(30,2**attempt)+uniform(0,1)`，429 读 Retry-After。

## 推荐流展示（2026-07-13）
- 入库 `LLM_SCORE_THRESHOLD=5`（保留全量）；展示闸门分离：`list_news` 默认 `min_score=6`+`max_age_hours=24`+`highlight_only=False`，前端 `useNewsFilter` 同默认。🔥 只看重点 = `is_highlight=true` 子集。
- 已知：8B 模型给科技类系统性打 5-6（无 ≥7），故展示默认 6。

## 去重系统（deduplicator.py，含 P5 跨天旧闻）
- 技术栈：URL hash / SimHash 汉明≤5（Redis 24h）/ SequenceMatcher>0.5（2h）/ TF-IDF 余弦>0.65（批内）/ Embedding 语义（Redis 90min，cos>0.80 去重、0.67~0.80 聚合）/ 数值抗误杀 / 事件聚合 `related_to_id`。
- P5：News 表 `content_hash`(SHA-256) + `simhash_fingerprint`(BIGINT) 均 indexed，迁移 `p5q3r4s5t6u7v9`。Pipeline 评分前 `_load_historical_fingerprints()` 加载 7 天指纹注入 `_historical_index` 与 24h Redis 合并比；`DEDUP_HISTORICAL_DAYS=7`。存量无指纹，能力随积累增强。
- **simhash 溢出修复**：Simhash 无符号 64 位、PG BIGINT 有符号，超额报 "value out of int64 range"。修复：持久化 `v if v<2**63 else v-2**64`；`_hamming()` 统一 `& 0xFFFFFFFFFFFFFFFF`。
- `is_highlight` 迁移 `q3r4s5t6u7v8`（Boolean NOT NULL DEFAULT false，indexed）；API 已返回，前端暂未用。

## Reports 播客功能（已规划，待实施，因 Azure 登录阻塞暂停）
- 目标：Reports 新闻概览四时段（早/午/傍/夜）做成播客化版——DeepSeek 改写 host/guest 双人对话脚本 + TTS 合成。
- 锁定决策：①播客化版 ②入口=当前页时段卡片内嵌 ▶ + 底部播放条（不新建页） ③时段任务写库后 `asyncio.create_task` 异步生成 ④**TTS=Azure Speech F0 免费层（CJK 计 2 字符，约 19 万计费单位/月，< 50 万额度）**。
- 引擎可配置 `TTS_ENGINE=azure`（默认），`siliconflow`(MOSS-TTSD-v0.5, ¥14/月) 作 fallback 位；脚本层输出结构化 `[{speaker,text}]` 与引擎解耦。host=zh-CN-XiaoxiaoMultilingualNeural / guest=zh-CN-YunxiNeural，SSML 多 `<voice>` 一次合成。
- 阻塞：Azure 登录问题未解，无 Key+Region，实施暂停。详见 `2026-07-15.md`。

## 中文财经信源
- **富途新闻（活跃）**：`rss_fetcher.py` `_parse_futu()`。接口 `https://news.futunn.com/news-site-api/main/get-flash-list?pageSize=30&lastTime=0`，必带 `Referer: https://news.futunn.com/main/live`，无签名。返回 `data.data.news[]`（title/content/detailUrl/time秒戳/relatedStocks），空 title 用 content 前 60 字。
- **财联社（停用留档）**：`cls.cn/v1/roll/get_roll_list`，签名 `MD5(SHA1(升序 k=v 拼接))`，`app=CailianpressWeb/os=web/sv=8.7.9`。

## 回填脚本（一次性，不进镜像）
- `docker compose run --rm -v /home/Alphareader/backend/scripts:/app/scripts web python scripts/{脚本}`。
- `backfill_why.py`（历史 why_it_matters）；`backfill_translation.py`（7 天内英文源/无中文/ai_score≥5，回填翻译；根因 stage2 失败无重试，待加重试）。

## 测试
- 全套 129 passed（P0:44+P1:8+P2:8+P3:16+parser:40+json_extractor:10）。跑：`cd backend && .venv-test/bin/python -m pytest tests/test_deepseek_filter_p{0,1,2,3}.py tests/test_parser.py`。
- 坑：MagicMock fixture 需显式关 `LLM_CONTENT_RISK_BISECT_ENABLED`/`LLM_TWO_STAGE_EN_ENABLED`（否则触发逻辑破坏"只调1次API"断言）；mock `_call_llm_once` 返回 4 元组（含 `retry_after`）。
