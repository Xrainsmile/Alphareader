# AlphaReader 长期记忆

## 产品/设计决策
- News 只保留「推荐流」一种（热点融入卡片：why_it_matters 橙底、🔥信源徽标、关联报道）。**不要**恢复双 tab。`/news/hot-topics` 接口保留前端未用。

## 前端约定（uni-app H5）
- 不用裸 `<template>` 分组（会渲染成 display:none），用 `<view>`；带 v-if/v-for 的 `<template>` 是 fragment 安全。
- 页面空白先 DevTools 看 offsetWidth/Height 区分「没渲染」vs「CSS 不可见」。
- 首次加载 onMounted，onShow 仅返回刷新；minify 后无法 grep 验证产物。

## 部署（Lighthouse 43.136.86.36 ubuntu /home/Alphareader）
- web=后端 FastAPI(build ./backend)；frontend=uni-app H5+Nginx(build ./frontend, 对外80/443)。**改前端必须 --build frontend，改后端 --build web；全量 up -d --build 最稳。**
- 流程：`git pull && docker compose -f docker-compose.yml up -d --build`（~3min）。Dockerfile apt+pip 源均腾讯云内网 `mirrors.tencentyun.com`（apt 两处、pip 一处；原 tuna 不可达已换）。
- web 经 Nginx 反代不暴露端口；验证 `docker exec alpha-web curl -s localhost:8000/...` 或宿主 `curl -k https://localhost/api/v1/...`（HTTP 301→HTTPS）。
- 上线 schema 变更前必跑 `docker compose run --rm -v /home/Alphareader/backend:/app web alembic upgrade head`。
- 容器内跑脚本须 `PYTHONPATH=/app`（如 `docker compose run -e PYTHONPATH=/app web python scripts/xxx.py`）。
- ssh 长命令超 300s：用极短 `timeout 10 docker compose build` 触发 daemon 异步构建再轮询镜像时间/日志；setsid 在 macOS 无效。
- 磁盘防膨胀：build 留 ~900MB dangling，deploy.sh 已加 image/builder prune -f；服务器 weekly crontab 周日4:00 清理（实测回收15GB）。
- **docker 数据根已在 `/data/docker`**（2026-07-16 从 `/var/lib/docker` 跨盘迁到挂载盘 `/dev/vdb`=`/data`，`daemon.json` 配 `data-root:/data/docker`）。系统盘 `/dev/vda2`(40G) 现约 46% 用。迁移需停 docker daemon 致全站短暂下线，须选维护窗口。清理回收站 `.trash_*` 可直接 `rm`。
- **新服务器 `119.29.20.65`**（腾讯云，4C/8G/180G 系统盘，Ubuntu 24.04，Docker 29.6.1，docker compose v5.3.1）已于 2026-07-16 购买并授权本机 `id_ed25519` 公钥可登录。**但用户明确：目前 AlphaReader 不部署到新服务器，仍在老服务器 `43.136.86.36` 运行。** 新服务器仅登录可达，**未授权 GitHub**（git clone 报 publickey denied），如需部署须先给 GitHub 加新机公钥或复用旧 deploy key。
- 老服务器 `43.136.86.36` 当前为 AlphaReader **唯一**运行实例，勿误以为已迁移。
- **调度器自愈已部署（2026-07-16，commit 3bdfbc8）**：`scheduler.py` 用 Redis 锁 `alphareader:scheduler_lock`(TTL 3600，值=worker owner id) 保证单 worker 跑管线；未持锁 worker 起看门狗每 60s 重试拿锁，持锁 worker 起续期循环。今后 stale 锁致调度器停摆会在「锁剩余TTL+60s」内自动恢复，**无需人工 `docker restart alpha-web`**。
- **DeepSeek 峰谷定价（2026-07 中旬起）**：高峰时段（北京时间 9:00~12:00、14:00~18:00）所有计费项 2 倍价。已把 Reports digest 午间/傍晚从 12:00/18:00 平移到 **12:15/18:15**（commit 9cfc543）避开峰段。其余 LLM 任务（catalyst 08:45/15:50、briefing 09:00/16:00、VCP 16:10 等）仍在高峰段，若要进一步省 2 倍价可后续平移。
- API 鉴权：`require_api_key`(header X-API-Key 或 query api_key，值=env NEWS_API_KEY；空则跳过仅开发)。

## VCP 投资策略页（阶段一二，已部署）
- 五维：大盘趋势25/市场宽度20/波动环境20/突破有效性25/交易活跃度10；档位 70-100适合/45-69中性/0-44谨慎。否决降级见 vcp_suitability.py。
- API：`/api/v1/strategy/{list,overview,adaptability,stock_signal}`+`POST /compute`；缓存 `get_vcp_adaptability`，强算 `compute_vcp_adaptability(market,date,save=True)`（upsert）。策略 id 归一化（美股剥 us_ 前缀）。
- 调度：CN/US 指数采集 15:50/05:50 + VCP适配度 16:10/06:10。
- 数据源：CN指数腾讯 fqkline(akshare兜底)；US指数新浪 getDailyK(^GSPC→.INX)；US个股新浪 getDailyK(BRK-B→BRK.B)。腾讯美股 fqkline 仅1天不可用于历史。CN/US 五维均真实无 DATA_DELAY。
- 前端缓存 requestCache.js(模块级Map+TTL+并发去重+cachePeek)：fetchVCPWatchlist/Filters/StrategyOverview/batchCheckCatalyst 套缓存，命中同步填充零转圈（TTL 白名单/概览/催化剂5min、筛选项30min）。

## SEPA VCP 形态识别（纯数据算法）
- 算法 vcp_detector.py：ZigZag→枢轴(最高swing high)→收缩段配对→五项硬指标(收缩次数/振幅递减/末段振幅/量能递减)。"高点递减"仅信息字段非硬门槛。detect_vcp(bars,params?,pivot_override?) 返回结构化结果，阈值宽松待回测。
- 接口 `GET /api/v1/sepa/vcp/analyze`(API Key)：实时算不写库，回传 bars(OHLCV) 供前端K线缩略图；人在环由 vcp_confirmed 兜底。曾漏 sa_text 导入已补。
- HK 日K hk_data_fetcher.py(腾讯hkfqkline+新浪兜底)；_hk_quotes_job 每交易日16:30。回测 scripts/backtest_vcp.py。
- 前端 P3：VcpTab 展开行渲染 VCP 判定卡片+K线SVG(蜡烛/量能/摆动高低点/枢轴橙虚线/收缩段紫带)。P4+快路径：SepaWatchlistItem.vcp_auto JSON列(迁移t2u3v4w5x6y7)；refresh_vcp_watchlist 遍历股池→detect_vcp(含K线)→写 vcp_auto，与 vcp_confirmed 独立；触发①POST /sepa/admin/refresh-vcp ②调度_vcp_refresh_job CN16:50/US06:50 ③scripts/refresh_vcp.py。VcpTab 展开优先读 item.vcp_auto 零延迟，缺失再 fetchVcpAnalyze。**实测回填 CN 192只/37 VCP/0失败。** 部署踩坑见 2026-07-16.md。

## LLM 评分 llm_news_filter.py
- 评分/分析/公司名映射=DeepSeek-V4-flash。配置 LLM_API_KEY(兼容DEEPSEEK_API_KEY)/LLM_API_URL/LLM_MODEL。DEEPSEEK_*仅摘要/研报；SILICONFLOW_*仅Embedding。已移除 Qwen3 enable_thinking。
- 入口 filter_news：中英分组→gather(Semaphore3)→_score_batch_once(重试)→content_risk触发_bisect(递归到batch=1丢坏)。英文_two_stage先评分后翻译。
- 规则：输入视为不可信(防注入)；旧闻>24h最高3分；is_highlight=score≥8+强催化+明文量化+一周内(score<8强制降级)。Ticker正则 A股^\d{6}$/港股^\d{5}$/美股^[A-Z]{3,5}(\.[A-Z])?$。
- 配置：LLM_BATCH_SIZE=20/SCORE_THRESHOLD=5/MAX_RETRIES=2/CONTENT_PREVIEW_CHARS=800/MAX_CONCURRENCY=3/TWO_STAGE_EN_ENABLED=True。退避 min(30,2**attempt)+uniform(0,1)，429读Retry-After。

## 推荐流展示
- 入库阈值5（保留全量）；展示闸门 list_news 默认 min_score=6+max_age_hours=24；🔥=is_highlight子集。8B模型科技类系统性5-6故默认6。

## 去重 deduplicator.py（含P5跨天旧闻）
- URL hash/SimHash汉明≤5(Redis24h)/SequenceMatcher>0.5(2h)/TF-IDF>0.65/Embedding语义(Redis90min,cos>0.80去重,0.67-0.80聚合)/事件聚合 related_to_id。
- P5：News 表 content_hash(SHA256)+simhash_fingerprint(BIGINT) indexed(迁移p5q3r4s5t6u7v9)；_load_historical_fingerprints 加载7天注入_historical_index，DEDUP_HISTORICAL_DAYS=7。
- simhash溢出修复：持久化 v if v<2**63 else v-2**64；_hamming &0xFFFFFFFFFFFFFFFF。
- is_highlight 迁移 q3r4s5t6u7v8(Boolean indexed)，前端暂未用。

## Reports 播客（暂停，Azure登录阻塞）
- 四时段播客化：DeepSeek改写双人对话+TTS。TTS=Azure Speech F0(中文计2字符)。host=XiaoxiaoMultilingualNeural/guest=YunxiNeural，SSML多voice一次合成。无Key+Region暂停。详见2026-07-15.md。

## 信源
- 富途 _parse_futu()：`news.futunn.com/news-site-api/main/get-flash-list?pageSize=30&lastTime=0` 必带 Referer。财联社(cls.cn)停用留档。

## 回填脚本/测试
- 一次性：`docker compose run --rm -v .../backend/scripts:/app/scripts web python scripts/xxx.py`（backfill_why.py / backfill_translation.py 等）。
- 测试 129 passed。跑：cd backend && .venv-test/bin/python -m pytest tests/test_deepseek_filter_p{0,1,2,3}.py tests/test_parser.py。MagicMock fixture 需关 bisect/two_stage 开关；mock _call_llm_once 返回4元组。
