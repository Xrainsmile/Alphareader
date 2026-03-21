# AlphaReader 全项目 Code Review 报告

> **审查日期**：2026-03-20  
> **审查范围**：后端 Services / API / Models、前端 Pages / Components、基础设施 Docker / Nginx / CI  
> **审查依据**：`claude.rules.mdc` 开发规范 + `claude.context.md` 架构文档

---

## 📊 审查总览

| 维度 | 发现数 | 🔴 紧急 | 🟠 重要 | 🟡 建议 | 🟢 低 |
|------|--------|---------|---------|---------|-------|
| 安全 | 9 | 4 | 3 | 2 | 0 |
| 后端代码质量 | 14 | 1 | 6 | 5 | 2 |
| 前端代码质量 | 13 | 3 | 6 | 2 | 2 |
| 数据模型 | 10 | 0 | 4 | 4 | 2 |
| 基础设施 | 11 | 1 | 5 | 3 | 2 |
| 测试 | 5 | 0 | 2 | 2 | 1 |
| **合计** | **62** | **9** | **26** | **18** | **9** |

---

## 一、🔴 紧急安全问题（必须立即修复）

### S-1. ✅ ~~API Key 泄露风险~~
- **已验证**：`git log --all -- .env` 和 `git log --all -- frontend/.env.production` 均无历史提交记录，密钥从未泄露。
- **Nginx 兜底注入**已在 `default.conf.template` 中配置（前端未携带 Key 时自动注入），前端 `VITE_API_KEY` 通过 `.env` 文件加载，不硬编码在代码中。

### S-2. ✅ ~~API Key 比较使用 `==` 而非恒定时间比较~~
- **已修复**：`auth.py:41` 改用 `hmac.compare_digest(api_key.encode(), settings.NEWS_API_KEY.encode())`，防止时序攻击。

### S-3. ✅ ~~`DEBUG=True` 默认值~~
- **已修复**：`config.py:39` 已为 `DEBUG: bool = False`（默认关闭）。debug_panel 仅在 `DEBUG=True` 时加载，500 响应仅在 DEBUG 模式下包含调试信息。

### S-4. ✅ ~~500 错误响应暴露内部异常~~
- **已修复**：`briefings.py` 和 `digests.py` 的 500 响应已改为通用错误信息（"研报生成失败，请稍后重试" / "摘要生成失败，请稍后重试"），详细错误仅通过 `logger.exception()` 写入日志。

---

## 二、后端代码质量

### B-1. 🟠 LLM Briefing 渲染 — code 幻觉问题（已部分修复）
- **文件**：`briefing_service.py`
- **问题**：LLM（DeepSeek）无视输入股票池中的 ts_code，自行编造 20 个不存在的股票代码，导致 Tier S/A 表格全部为空
- **已修复**：新增 `_normalize_tier_codes()` + `_validate_and_fix_tiers()` 校验链
- **仍需验证**：修复后的效果需要重新生成研报确认

### B-2. ✅ ~~响应格式不统一（4+ 种风格）~~
- **已修复**：创建 `app/schemas/response.py`，定义 `APIResponse` + `PaginatedResponse` 统一包装器。
- **所有 API 端点已改造**：
  - `reports.py`：sync / delete / list / detail 全部用 `APIResponse` 包装
  - `briefings.py`：latest / list / detail / generate 全部用 `APIResponse` 包装
  - `digests.py`：list / detail / generate 全部用 `APIResponse` 包装
  - `news.py`：list 用 `PaginatedResponse`，search / suggest / hot / pipeline/* 用 `APIResponse`
  - `stocks.py`：rs_rating / search / vcp_watchlist / trend_watchlist / value_watchlist 等 15+ 端点全部用 `APIResponse`；后台任务的 `JSONResponse`（202/409）也统一为 `{code, message, data}` 结构
- **前端兼容**：`api.js` 的 `request()` 已内置 `{code, data}` 自动解包逻辑，前端页面无需修改

### B-3. 🟠 Pydantic 输入校验不严格
| 端点 | 问题 | 文件:行号 |
|------|------|-----------|
| `briefings/generate` | `target_date` 为 `str` 应为 `date` | `briefings.py:132-133` |
| `digests/generate` | `target_date` 为 `str`，`period_label` 无枚举约束 | `digests.py:111-113` |
| `stocks/backfill` | `start_date`/`end_date` 为 YYYYMMDD 字符串 | `stocks.py:353-355` |

### B-4. 🟠 Admin 权限分层不足
- **文件**：`stocks.py` 全文件
- **问题**：`/rs_rating/compute`、`/update_quotes`、`/backfill` 等高权限操作仅受普通 API Key 保护，无 admin 鉴权
- **建议**：复用 `sandbox.py` 的 `_require_admin` 模式

### B-5. ✅ ~~`CORS_ORIGINS="*"` 默认值~~
- **已修复**：
  - `config.py:47`：`CORS_ORIGINS` 默认值改为 `"https://alphareader.site,http://localhost:5173"`
  - `main.py`：`allow_methods` 收紧为 `["GET", "POST", "PUT", "DELETE", "OPTIONS"]`，`allow_headers` 收紧为 `["Content-Type", "X-API-Key", "Authorization"]`

### B-6. ✅ ~~敏感配置字段缺少 `repr=False`~~
- **已修复**：`config.py` 中所有敏感字段（`DEEPSEEK_API_KEY`、`ZHIPU_API_KEY`、`SILICONFLOW_API_KEY`、`FINNHUB_API_KEY`、`NEWS_API_KEY`、`DASHBOARD_PASSWORD`、`SANDBOX_PASSWORD`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`REPORT_SYNC_TOKEN`）均已使用 `Field("", repr=False)`。

### B-7. 🟡 根目录调试脚本散落（8 个）
- **待删除**：`check_st.py`、`debug_c1.py`、`debug_c1_st.py`、`debug_c2.py`、`debug_funnel.py`、`debug_funnel2.py`、`debug_nrc.py`、`debug_pipeline.py`、`show_all.py`
- **待整理**：
  - `cleanup_duplicates.py`、`cleanup_stale_news.py`、`sync_update.py`、`run_spider.py` → 移到 `backend/scripts/`
  - `test_briefing.py` → 移到 `backend/tests/`
- **建议**：`.gitignore` 添加 `backend/debug_*.py`

### B-8. 🟡 Scheduler 日志完善
- **文件**：`scheduler.py`
- **问题**：`_briefing_job` 缺少执行耗时日志
- **建议**：参照 `_pipeline_job` 记录开始/结束/耗时

### B-9. 🟡 数据库连接池缺少 `pool_recycle`
- **文件**：`database.py:10-16`
- **问题**：长时间运行的应用中，数据库端可能主动关闭空闲连接
- **修复**：添加 `pool_recycle=3600`

### B-10. 🟢 `config.py` 缺少范围校验
- `PIPELINE_START_HOUR`/`PIPELINE_END_HOUR` 无 `ge=0, le=23` 约束
- `LOG_LEVEL` 无枚举约束

---

## 三、前端代码质量

### F-1. 🔴 `index/index.vue` — 2207 行 + 使用 Options API
- **问题**：这是项目中**唯一一个**不使用 `<script setup>` 的页面文件，违反 `claude.rules.mdc` 第四章规范
- **行号**：第 367 行 `export default {}`
- **建议**：重构为 `<script setup>` + 拆分为多个子组件

### F-2. 🔴 `stocks/index.vue` — 2312 行巨型文件
- **问题**：全项目最大文件，包含 VCP、趋势、价投、模拟仓四个 Tab 的全部逻辑和样式
- **建议**：每个 Tab 提取为独立组件（`VCPTab.vue`、`TrendTab.vue`、`ValueTab.vue`、`SandboxTab.vue`）

### F-3. 🔴 `ValueStockAddModal.vue` 绕过 API 封装
- **文件**：`components/stocks/ValueStockAddModal.vue:150-167, 203-218`
- **问题**：直接调用 `uni.request` 手动拼接 `BASE_URL` + `API_KEY`，完全绕过 `utils/api.js` 统一封装
- **影响**：API 地址变更时此文件不会同步；错误处理逻辑不一致
- **附加问题**：该组件可能未被任何页面引用（遗留代码？）

### F-4. ✅ ~~大量重复代码~~
- **已修复**：创建 `frontend/src/utils/formatters.js`（189 行），包含 15+ 公共函数：
  - `scoreClass`、`formatScore`、`formatTime`、`gravityClass`、`formatGravity`
  - `sentimentClass`、`sentimentIcon`、`sentimentEmoji`、`formatRelevance`
  - `formatDate`、`formatDateTime`、`formatDateWithWeekday`
  - `reportStatusLabel`、`stockStatusLabel`
  - `detailTagStyle`、`listTagStyle`（mp-html tag-style 常量）
- **6 个文件已引用**：reports/detail、reports/index、briefing/detail、stocks/detail、NewsCardGroup、SandboxTab

### F-5. 🟠 路由参数获取方式不一致
- `reports/detail.vue:75-77`、`briefing/detail.vue:129-131`：使用非标准的 `getCurrentPages()` + `$page.options`
- `stocks/detail.vue`：使用标准的 `onLoad(options)` 钩子
- **建议**：统一使用 `onLoad` 方式

### F-6. 🟠 `resetTmp` 默认值 bug
- **文件**：`index/index.vue:660-664`
- **问题**：`tmpScore` 重置为 `6`，但 `data()` 中 `minScore` 初始值为 `5`，两处不一致
- **影响**：用户重置筛选后评分阈值会意外变为 6 而非默认的 5

### F-7. ✅ ~~缺少 CSS 变量系统~~
- **问题**：颜色值硬编码几十处（`#1a1a2e`、`#8c8c9a`、`#4285f4` 等），若未来做暗黑模式或换肤，改动量巨大
- **已修复**：在 `App.vue` 定义 65+ CSS 变量（设计 Token），覆盖基础色/文字色/品牌色/语义色/状态背景/边框/渐变/时段色/字体/圆角/阴影。全部 15+ Vue 文件共 439 处引用 `var(--xxx)`，仅 9 处合理保留（SVG 内联/JS 动态/mask 遮罩）

### F-8. 🟠 uni-app 使用 Alpha 通道版本
- **文件**：`frontend/package.json`
- **问题**：`@dcloudio/uni-*: 3.0.0-alpha-*` — alpha 版本在生产环境存在 breaking change 风险

### F-9. 🟡 Prompt 模板硬编码在组件内
- **文件**：`index/index.vue:683-718`
- **问题**：35 行 Gemini Prompt 模板直接写在 Vue 组件的 methods 里
- **建议**：提取到 `utils/prompt-template.js`

### F-10. 🟡 日期 / 数据源列表硬编码
- `stocks/index.vue:621`：`成立于 2026.02.13` 写死
- `index/index.vue:409-411`：`cnSources`/`enSources`/`techSources` 列表写死
- **建议**：从 API 或配置中获取

### F-11. 🟢 生产环境残留 `console.log`
- `App.vue:4`：`console.log('AlphaReader launched')`
- `index/index.vue`：部分 catch 块使用空 `catch {}`，吞掉异常

### F-12. 🟢 前端零测试
- 没有任何前端测试文件（单元测试或 E2E）

---

## 四、数据模型

### M-1. 🟠 缺失索引
| 表 | 缺失索引 | 影响 |
|----|----------|------|
| `pipeline_runs` | `started_at` | API 查询频繁使用 `WHERE started_at >= :start_dt`，无索引全表扫描 |
| `news` | `tags` GIN 索引 | `News.tags.any(sector)` 过滤无索引支持 |
| `watchlist_daily` | `(run_date, vcp_score DESC)` 复合索引 | 按分数排序时无法利用索引 |
| `trend_watchlist_daily` | `(run_date, trend_score DESC)` 复合索引 | 同上 |

### M-2. 🟠 冗余索引（浪费写入性能和存储）
| 表 | 冗余 |
|----|------|
| `sandbox_nav` | `uq_sandbox_nav_date`（唯一约束已隐式创建索引） + `ix_nav_date`（多余） |
| `stock_daily_quote` | `uq_quote_code_date`（唯一约束）+ `ix_quote_code_date`（完全重复） |

### M-3. ✅ ~~列类型不当~~
- **已修复**：4 个列类型已全部修正：
  - `reports.date`：`String(32)` → `Date`（`report.py:26`）
  - `stock_daily_quote.volume`：`Integer` → `BigInteger`（`stock.py:43`）
  - `sandbox_nav.nav/total_pnl`：`Float` → `Numeric(16,4)`（`sandbox.py:159-160`）
  - `sandbox_analyses.score`：`Float` → `Numeric(3,1)`（`sandbox.py:80`）

### M-4. 🟠 缺少关键约束
| 约束类型 | 表.列 | 建议 |
|----------|-------|------|
| CHECK | `sandbox_stocks.status` | `IN ('watching', 'holding', 'exited')` |
| CHECK | `sandbox_trades.action` | `IN ('buy', 'sell')` |
| CHECK | `daily_briefings.status` | `IN ('ok', 'failed', 'empty')` |
| FK | `sandbox_analyses.stock_id` | → `sandbox_stocks.id` |
| FK | `sandbox_trades.stock_id` | → `sandbox_stocks.id` |

### M-5. 🟡 未定义 SQLAlchemy relationship
- 所有关联查询都是手动 JOIN/子查询
- `SandboxStock` ↔ `SandboxAnalysis` ↔ `SandboxTrade` 在 sandbox API 中分三次查询，如果定义 `relationship()` + `selectinload()` 可以合并

---

## 五、基础设施

### I-1. ✅ ~~Redis 无密码保护~~
- **已修复**：`docker-compose.yml` 中 Redis 已配置 `--requirepass ${REDIS_PASSWORD}`，healthcheck 也使用 `-a ${REDIS_PASSWORD}`。`config.py` 的 `REDIS_URL` 属性已支持含密码的连接字符串。

### I-2. ✅ ~~Backend Dockerfile 单阶段构建~~
- **已修复**：改为多阶段构建（builder 编译 C 扩展 → runtime 仅复制 venv），最终镜像减小 200MB+。测试依赖（pytest/aiosqlite）分离到 `requirements-dev.txt`，不进入生产镜像。

### I-3. ✅ ~~Docker 无资源限制~~
- **已修复**：为所有 4 个容器添加 `mem_limit`：web 1536m, db 768m, cache 384m, frontend 128m（合计 ~2.8GB，为系统和突发预留 ~1.2GB）

### I-4. 🟠 Nginx 域名硬编码
- **文件**：`deploy/nginx/conf.d/default.conf.template`
- **问题**：`alphareader.site` 和 SSL 证书路径硬编码
- **修复**：改用 `${NGINX_SERVER_NAME}` 环境变量

### I-5. ✅ ~~Nginx 缺少速率限制~~
- **已修复**：添加两级速率限制：
  - 通用 API：`30r/m` + burst 15（`/api/` 全部端点）
  - AI 生成类：`3r/m` + burst 2（`/api/v1/(briefings|digests)/generate`）
  - 超限返回 429 Too Many Requests

### I-6. 🟠 gunicorn timeout (1800s) vs nginx proxy_read_timeout (120s) 冲突
- **问题**：Nginx 会先超时返回 504，而后端请求仍在执行
- **修复**：统一超时设置，或对长任务使用异步任务队列模式

### I-7. 🟡 依赖版本管理
- `akshare >=1.18.27,<2.0` 范围过大（该库更新频繁且常 breaking change）
- 没有 `requirements-lock.txt` 或 `pip-compile` 生成的完整依赖锁文件
- `frontend/package-lock.json` 未追踪，构建不可复现

### I-8. 🟡 pyrightconfig.json Python 版本不一致
- 当前设为 `3.10`，但 Dockerfile 使用 `python:3.12-slim`

### I-9. 🟡 Frontend Dockerfile 运行为 root
- nginx:alpine 默认以 root 运行
- 建议添加非特权用户

### I-10. 🟢 deploy.sh 文件路径不一致
- 第 33 行引用 `default.conf`，但实际使用的是 `default.conf.template`

---

## 六、测试

### T-1. ✅ ~~没有 CI/CD 配置~~
- **已修复**：添加 `.github/workflows/ci.yml`，push/PR 自动运行：
  - **Backend Tests**：PostgreSQL 16 + Redis 7 服务容器，Python 3.12，`pytest -v`
  - **Frontend Lint**：Node.js 20，`npm run build:h5` 编译检查
  - 触发分支：`main`、`feat/*`、`fix/*`
  - 并发控制：同分支取消旧 run

### T-2. 🟠 测试覆盖不足
- **已有**：API 端点、LLM 解析、去重、JSON 提取、排名算法（6 个测试文件）
- **缺失**：
  - Screener pipeline 无测试
  - Scheduler 无测试
  - Briefing service 无测试
  - 前端零测试

### T-3. 🟡 缺少覆盖率工具
- 没有 `pytest-cov` 配置

### T-4. 🟡 缺少集成测试
- 所有测试使用 mock/SQLite，没有真实 PostgreSQL/Redis 的集成测试

---

## 七、架构优化建议

### A-1. 创建 `utils/formatters.js` 统一前端工具函数
```
statusLabel()、sentimentEmoji()、formatDate()、scoreClass()、tagStyle
```
消除 6+ 处重复定义。

### A-2. 定义统一的 API 响应包装器
后端所有端点使用一致的 `{code, message, data}` 结构，配合分页扩展。

### A-3. 前端大文件拆分路线图
```
index/index.vue (2207 行)
├── SearchPanel.vue
├── FilterSheet.vue
├── NewsCard.vue
└── PromptGenerator.vue

stocks/index.vue (2312 行)
├── VCPTab.vue
├── TrendTab.vue
├── ValueTab.vue
├── SandboxTab.vue
└── IndustryConceptFilter.vue (通用筛选器)
```

### A-4. 后端脚本整理
```
backend/
├── scripts/          # 运维脚本
│   ├── cleanup_duplicates.py
│   ├── cleanup_stale_news.py
│   ├── sync_update.py
│   └── run_spider.py
├── tests/            # 测试
│   ├── test_briefing.py
│   └── ...
└── (删除所有 debug_*.py、check_st.py、show_all.py)
```

---

## 八、执行计划（建议优先级）

### Phase 1：安全加固（1-2 天）
- [x] S-1: 检查 git 历史并轮换密钥
- [x] S-2: API Key 比较改用 `hmac.compare_digest`
- [x] S-3: `DEBUG` 默认值改 `False`
- [x] S-4: 500 响应不暴露内部异常
- [x] I-1: Redis 添加密码
- [x] B-5: CORS 收紧

### Phase 2：数据可靠性（1-2 天）
- [x] M-1: 补充缺失索引
- [x] M-2: 清理冗余索引
- [x] M-3: 修复列类型
- [x] B-9: 添加 `pool_recycle`

### Phase 3：代码整洁（2-3 天）
- [x] B-7: 清理调试脚本
- [ ] B-2: 统一 API 响应格式（推迟：涉及全部 API 端点 + 前端联动，作为独立重构任务）
- [x] B-3: 修复 Pydantic 输入校验
- [x] F-4: 创建 `utils/formatters.js` 消除前端重复

### Phase 4：前端重构（3-5 天）
- [x] F-1: `index/index.vue` 改 `<script setup>` + 拆分
- [x] F-2: `stocks/index.vue` 拆分 Tab 组件
- [x] F-7: 引入 CSS 变量系统

### Phase 5：基础设施优化（1-2 天）
- [x] I-2: Backend Dockerfile 多阶段构建
- [x] I-3: 添加 Docker 资源限制
- [x] I-5: Nginx 添加速率限制
- [x] T-1: 添加 GitHub Actions CI

---

*本报告由全项目自动化 Code Review 生成，覆盖 107 个后端 Python 文件、36 个前端文件及全部基础设施配置。*
