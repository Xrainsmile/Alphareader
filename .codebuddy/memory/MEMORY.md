# AlphaReader 长期记忆

## 产品/设计决策（稳定）

- **News 视图**：现网只保留「推荐流」一种视图。原本的「热点」独立 tab 已移除（2026-07-08），
  改将热点内容融入推荐流卡片：
  - `why_it_matters`（推荐理由，💡 橙底）已在 `NewsCard.vue` 展示。
  - 🔥 信源数徽标（`childrenCount + 1` 信源）显示在 `NewsCard` 元信息行，当该新闻是某事件父条目且有多条关联报道时出现。
  - 多信源关联报道折叠区本就由 `NewsCardGroup`（基于 `related_to_id`）实现，无需额外后端改动。
- **不要**恢复「推荐流 / 热点」双 tab 切换（用户明确要求只保留一种视图）。
- `/news/hot-topics` 后端接口保留（未被前端调用），`fetchNewsHotTopics` 在前端 api.js 仍是未使用导出。

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
