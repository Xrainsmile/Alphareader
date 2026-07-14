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
- Alembic：上线任何 schema 变更前**必先** `docker compose run --rm -v /home/Alphareader/backend:/app web alembic upgrade head`（bind-mount 挂 `/app`，非 `/workspace`），否则 pipeline 写库报 unknown column。

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
