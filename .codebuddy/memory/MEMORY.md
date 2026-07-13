# AlphaReader 长期记忆

## 产品/设计决策（稳定）

- **News 视图**：现网只保留「推荐流」一种视图。原本的「热点」独立 tab 已移除（2026-07-08），
  改将热点内容融入推荐流卡片：
  - `why_it_matters`（推荐理由，💡 橙底）已在 `NewsCard.vue` 展示。
  - 🔥 信源数徽标（`childrenCount + 1` 信源）显示在 `NewsCard` 元信息行，当该新闻是某事件父条目且有多条关联报道时出现。
  - 多信源关联报道折叠区本就由 `NewsCardGroup`（基于 `related_to_id`）实现，无需额外后端改动。
- **不要**恢复「推荐流 / 热点」双 tab 切换（用户明确要求只保留一种视图）。
- `/news/hot-topics` 后端接口保留（未被前端调用），`fetchNewsHotTopics` 在前端 api.js 仍是未使用导出。

## 前端约定（uni-app H5）

- **模板里不要用裸 `<template>` 做分组**。uni-app H5 编译器会把无指令的 `<template>` 渲染成真实 HTML `<template>` 元素（默认 `display:none`，内容不渲染），把内部整块藏死。带 `v-if`/`v-for` 的 `<template>` 是 fragment（不产生 DOM），安全的。如需分组容器用 `<view>`。
  - 实例：`pages/index/index.vue` 曾有一个无条件内层 `<template>` 包住新闻区，导致首页新闻卡片 DOM 全在但 `offsetWidth/Height=0` 完全不可见（commit bf39cd3 删除后修复）。
- **页面"空白"排查顺序**：先浏览器 DevTools 看目标元素 DOM 是否存在 + `offsetWidth/Height`，区分「没渲染」vs「渲染了但布局塌缩/CSS 不可见」，**不要先怀疑数据/生命周期**。AlphaReader 首页空白曾被误判为 onShow/onMounted 生命周期问题两轮，真因是 template display:none。
- 首次加载用 Vue 标准 `onMounted` 可靠（reports 页参照）；uni-app `onShow` 仅用于返回时按需刷新。
- 验证部署产物时，minify 会重命名钩子标识符，不能 grep `onShow(`/`onMounted(` 字符串；看 chunk import 行是否从 `uni-app.es.*.js` / vue runtime 多导入符号。

## 部署（Lighthouse 43.136.86.36）

- 部署命令（服务器本地执行）：`cd /home/Alphareader && git pull && docker compose -f docker-compose.yml up -d --build`
- **Dockerfile apt 源已改为腾讯云内网镜像** `mirrors.tencentyun.com`（python:3.12-slim，deb822 `/etc/apt/sources.list.d/debian.sources`），
  广州区域 build 从 ~26 分钟降到 ~3 分钟。`backend/Dockerfile` 两处（builder / runtime）都改了。
- `web` 服务故意不暴露端口，只经 Nginx 反代；宿主机验证新接口用 `docker exec alpha-web curl -s http://localhost:8000/...` 或 `curl http://localhost/api/v1/...`。
- Alembic 迁移通过 `docker compose run --rm -v /home/Alphareader/backend:/app web alembic upgrade head` 应用
  （bind-mount 必须挂到镜像 WORKDIR `/app`，不是 `/workspace`）。

## 回填（why_it_matters）

- 脚本 `backend/scripts/backfill_why.py`（commit 3709d79 修了 asyncpg 的 `make_interval` 坑）。
- 运行：`docker compose -f docker-compose.yml run --rm -v /home/Alphareader/backend/scripts:/app/scripts web python scripts/backfill_why.py`
  （镜像里的脚本可能是旧版，用 bind-mount 覆盖为最新）。
- 历史 6733 条（最近 30 天 ai_score>=6）于 2026-07-08 回填，约 45-90 分钟。

## 财联社（cls.cn）信源接口（易失，常改版）

- 抓取代码在 `backend/app/services/rss_fetcher.py`，`FeedSource(name="财联社", signed_cls=True)`。
- **当前可用接口**：`https://www.cls.cn/v1/roll/get_roll_list`（GET）。
- **签名算法**（已第三次改版，逆向自 cls.cn 前端 JS）：`sign = MD5( SHA1( 按 key 升序拼接的 "k=v&k=v" 串 ) )`，
  请求自动注入 `app=CailianpressWeb` / `os=web` / `sv=8.7.9`，签名覆盖全部 query 参数（不含 sign 自身）。
- 若未来再 404/10012：直接逆向 cls.cn 前端 bundle（`/_next/static/chunks/pages/telegraph-*.js` 引用的请求层模块）核对 `_cls_sign` 与 `sv` 版本号，无需全网试错。
- 历史端点：`nodeapi/updateTelegraphList` → `nodeapi/telegraphList` → `v1/roll/get_roll_list`（均已废弃前者）。

## LLM 评分模块 deepseek_filter.py（2026-07-13 大改）

**核心文件**：`backend/app/services/deepseek_filter.py`（不是 deepseek 而是 SiliconFlow，函数/日志名沿用 deepseek 是历史遗留）。

**关键数据结构**：
- `BatchResult(scored, status, processed_ids, missing_ids, duplicate_ids, content_risk_dropped, raw_response)`：`status` 为 `Literal["ok"|"api_error"|"parse_error"|"content_risk"|"empty_after_filter"|"no_api_key"]`。
- `FilterResult(scored, skipped_batches, total_batches, content_risk_batches, content_risk_dropped_items, api_error_batches, parse_error_batches)`：`had_errors` 是 `pipeline.py` 决定是否 Redis-标记低分 URL 的依据。
- `ScoredNewsItem`：新增 `is_highlight: bool = False`（P2 两层筛选）。

**入口链路**：
- `filter_news()` → 按中文占比 + langdetect（seed=0）分中英组 → `_run_batches()` → `filter_batch_detailed()` → `_score_batch_once()`（API 层重试）→ 若 status=content_risk 且开关开 → `_bisect_content_risk()`（递归到 batch=1 定位坏条目）。
- `filter_batch()` 与 `_parse_response()` 保留为向后兼容薄包装，勿删（test_parser.py 依赖）。

**Prompt 关键约束**（CN/EN 两套）：
- 旧闻硬规则：`published_at` 距 `fetched_at` >24h 或正文明确"3 天前"以上 → 最高 3 分。
- 预期差判定：需明文 beat/miss/超预期或具体对比数字，仅凭语气不算。
- 翻译约束：`chinese_title` 中文占比 ≥50%、`chinese_summary` ≥60%；品牌名/型号/EPS-CPI-PMI 等允许英文保留（不是"绝对不可英文"）。
- **is_highlight=true 需同时**：score≥8 + 明确强催化 + 明文量化数据 + 一周内事件。代码解析层有硬防线：score<8 时强制降级为 false。

**关键配置**（`app/config.py`）：
- `DEEPSEEK_BATCH_SIZE=20 / SCORE_THRESHOLD=5 / MAX_RETRIES=2`
- `DEEPSEEK_CONTENT_PREVIEW_CHARS=800`（旧值 200；仅送 200 字导致模型无法判定旧闻/预期差）
- `DEEPSEEK_MIN_CHINESE_RATIO_TITLE=0.5 / SUMMARY=0.6`
- `DEEPSEEK_CONTENT_RISK_BISECT_ENABLED=True / MAX_DEPTH=6`（关闭时回退到"整批丢弃"老行为）

**Ticker 校验规则**（严格）：
- A股：`^\d{6}$`
- 港股：`^\d{5}$`；4 位自动补前导 0
- 美股：`^[A-Z]{3,5}(\.[A-Z])?$` **仅 3-5 位纯字母**，可选 `.X` 后缀（BRK.B/BRK.A）。1-2 位（F/T）和 6+ 位（"INVALID"）一律拒。宁可漏也不误伤。

**Content Risk 二分行为**：
- 触发 400 Content Exists Risk → 二分递归定位到 batch=1 的坏条目 → 丢弃单条，其他条目正常评分。
- 单批的 dropped 数进 `BatchResult.content_risk_dropped`；`FilterResult.content_risk_dropped_items` 累加。
- 二分不算 batch skipped（只要有 scored 就算 ok），但 dropped_items 会单独记 warning。

**测试组织**：
- `tests/test_deepseek_filter_p0.py`：44 个（BatchResult 状态、中文占比、ticker、字段校验、prompt 长度/时间、完整性校验）
- `tests/test_deepseek_filter_p1.py`：8 个（二分核心、开关、累加）
- `tests/test_deepseek_filter_p2.py`：8 个（is_highlight 提取、硬防线、中英文分支）
- `tests/test_parser.py`：40 个既有，保持向后兼容
- 本地跑测试用 `.venv-test`（`/opt/homebrew/bin/python3.11 -m venv backend/.venv-test`），backend 里没 sqlalchemy 也能跑（deepseek_filter 不依赖 DB）。

**test_parser.py `_patch_api_key` 兼容**：用 MagicMock 时新增的 `DEEPSEEK_CONTENT_RISK_BISECT_ENABLED` 需要显式设 False，否则 MagicMock() 是 truthy 会触发二分逻辑，让"只调 1 次 API"断言失败。

**News 表 is_highlight 字段**（2026-07-13 迁移）：
- Alembic `q3r4s5t6u7v8_add_is_highlight`（down_revision=`p2q3r4s5t6u7`），`Boolean NOT NULL DEFAULT false`，带索引。
- API 层：`GET /api/v1/news` 和 hot-topics SQL 都返回 `is_highlight`；前端暂未使用，后续可用于卡片突出显示。
- **上线必须先 alembic upgrade head**，否则 pipeline 写入报错 unknown column。
