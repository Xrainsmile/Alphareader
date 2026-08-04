# AlphaReader 长期记忆

## 产品/设计决策
- News 只保留「推荐流」一种（热点融入卡片：why_it_matters 橙底、🔥信源徽标、关联报道）。**不要**恢复双 tab。`/news/hot-topics` 接口保留前端未用。
- **事件化改版（2026-08-02 大版本）**：三入口 今日简报(默认页)/实时事件/深度报告。**对外导航英文命名**：Reports=今日简报、News=实时事件、Stocks、SEPA（左导航 PcSidebar + 移动端 tabBar + 页面标题均用英文）。事件=基本单位：事件包字段 + event_versions 版本表（仅实质更新写快照）。
- **Stocks / SEPA 对外隐藏 + 侧门（2026-08-04 新增）**：默认对外隐藏 Stocks/SEPA 入口（桌面端 PcSidebar 仅 isOpen 时显示；移动端已从 pages.json 原生 tabBar 移除）。开启方式：Reports 旁「!」按钮（组件 `GateButton.vue`，带呼吸+摇摆动画），连续点 3 次弹出密码框，**密码复用 Stocks 自身密码**（POST `/api/v1/sandbox/verify-access`）。校验通过后 `useGate.openGate` 写入 `gate_open=true` + 一并缓存 `sb_token`/`sb_unlocked`/`sepa_token`/`sepa_unlocked`（模块级单例 ref `useGate.js`，PcSidebar 与 Reports 页共享同步）。移动端解锁后在 Reports 页头显示 Stocks/SEPA 入口 chip（navigateTo 跳转，因已非 tabBar 页）。

## 前端约定（uni-app H5）
- 不用裸 `<template>` 分组（会渲染成 display:none），用 `<view>`；带 v-if/v-for 的 `<template>` 是 fragment 安全。
- 页面空白先 DevTools 看 offsetWidth/Height 区分「没渲染」vs「CSS 不可见」。
- 首次加载 onMounted，onShow 仅返回刷新；minify 后无法 grep 验证产物。
- 导航：桌面 ≥768px 用 `PcSidebar.vue`（自定义组件）；移动端用 pages.json 原生 tabBar（仅能静态配置，无法运行时隐藏单条目 → 隐藏需从 list 移除，改用 navigateTo）。
- 私有模块密码弹窗复用 `components/stocks/SandboxPasswordModal.vue`（visible/password/error props + update:visible/update:password/confirm emits）。

## 部署（Lighthouse 43.136.86.36 ubuntu /home/Alphareader，唯一运行实例）
- web=后端 FastAPI(build ./backend)；frontend=uni-app H5+Nginx(build ./frontend, 对外80/443)。**改前端必须 --build frontend，改后端 --build web；全量 up -d --build 最稳。**
- 流程：`git pull && docker compose -f docker-compose.yml up -d --build`（~3min）。Dockerfile apt+pip 源均腾讯云内网 `mirrors.tencentyun.com`。
- web 经 Nginx 反代不暴露端口；验证 `docker exec alpha-web curl -s localhost:8000/...` 或宿主 `curl -k https://localhost/api/v1/...`。
- 上线 schema 变更前必跑 `docker compose run --rm -v /home/Alphareader/backend:/app web alembic upgrade head`。
- 容器内跑脚本须 `PYTHONPATH=/app`；`python -c` 不需要。ssh 长命令超 300s 用 `timeout 10 docker compose build` 触发异步构建再轮询。
- **docker 数据根在 `/data/docker`**（daemon.json data-root）。新服务器 `119.29.20.65` 已购但未授权 GitHub，**目前不部署到新服务器**。
- **调度器自愈（commit 3bdfbc8）**：Redis 锁 `alphareader:scheduler_lock` 保证单 worker；stale 锁自动恢复，**无需人工 restart**。
- **DeepSeek 峰谷定价**：高峰 9:00~12:00/14:00~18:00 计费 2 倍。Reports digest 午间/傍晚已平移到 12:15/18:15 避开。
- API 鉴权：`require_api_key`（X-API-Key / api_key，值 env NEWS_API_KEY；空则跳过仅开发）。

## 关键后端模块（精简）
- **VCP 投资策略页**：五维权重 25/20/20/25/10；档位 70-100适合/45-69中性/0-44谨慎。API `/api/v1/strategy/{list,overview,adaptability,stock_signal}`+`POST /compute`。调度 CN/US 指数 15:50/05:50 + VCP适配 16:10/06:10。前端 requestCache 缓存。
- **SEPA VCP 识别**：纯算法 vcp_detector.py（ZigZag→枢轴→收缩配对→五项硬指标）。接口 `GET /api/v1/sepa/vcp/analyze`（API Key，实时不写库）。前端 K线 SVG + vcp_auto 快路径。`_vcp_refresh_job` CN16:50/US06:50。
- **LLM 评分 llm_news_filter.py**：评分/翻译用 `deepseek-chat`（**勿切回 v4-flash**，曾致 ~100M tokens/天）。v4-flash 推理已关（`"thinking":{"type":"disabled"}`）。规则：输入不可信防注入；旧闻>24h 最高3分；is_highlight=score≥8+强催化+量化+一周内。配置 LLM_BATCH_SIZE=20/SCORE_THRESHOLD=5。
- **新闻预筛 prefilter.py**：`run_pipeline` Step 2.75（零 token，用 difflib+正则）。权威/重大事件强制送评；`PREFILTER_SHADOW_MODE=True` 影子模式生产中仅记录不丢弃（跑 3–7 天对比后再关闭）。落库 `News.prefilter_reason`。
- **事件合成 event_synthesizer.py**：多源簇合成 1 事件卡（LLM deepseek-chat）。pipeline Step 7 挂载；星型拓扑由 `_resolve_event_roots` 压平。
- **推荐流展示**：入库阈值5全量；展示闸门默认 min_score=6+max_age_hours=24；🔥=is_highlight 子集。hot 排序 gravity 事件1.2/单篇1.8，事件三维优待。
- **去重 deduplicator.py**：URL/SimHash/Embedding/事件聚合；P5 跨天旧闻。
- **Reports 播客**：暂停（Azure 登录阻塞）。

## WeCom 推送（2026-08-03 上线）
- 推 Reports 四时段 `news_digest`（早间/午间/傍晚/夜间）到企业微信群机器人 webhook（env `ALERT_WEBHOOK_URL`）。`notifier.send_report` 发 text（≤2000字节按行切分）；`digest_service.build_wecom_digest_summary` 拼摘要+原文链接。**原文链接指向 Reports 页 `https://www.alphareader.site/#/pages/reports/index`**（注意：`/pages/briefing/detail` 是**研报 daily_briefing** 详情页，news_digest 没有独立详情路由、全部内联在 Reports 时间线里，故不能用 digest_id 拼 briefing 链接）。手动触发脚本 `scripts/push_latest_digest.py`（复用同一函数）。

## 信源 / 回填
- 富途 `_parse_futu` 必带 Referer；财联社(cls.cn)停用。
- 一次性回填：`docker compose run --rm -v .../backend/scripts:/app/scripts web python scripts/xxx.py`。
