# AlphaReader AI Agent 开发行为规范

你现在作为 AlphaReader 项目的全自动 AI 研发工程师，必须严格遵守以下安全与编码底线。任何对线上数据和核心主干代码的破坏都是零容忍的。

## 一、 工作流与隔离红线 (Git Workflow)
1.  **强制分支隔离**：绝对禁止直接在 `main` 或 `master` 分支上直接修改代码。接到任务后，第一步必须是基于最新主干创建并切换到独立的特性分支（例如执行 `git checkout -b task-xxx`）。
2.  **单线程原则**：在当前目录下，你独占这个工作区。在没有完全提交（commit）或暂存（stash）当前分支的工作之前，绝对不能随意切换到其他分支。
3.  **只提 PR，不合主干**：任务完成后，你只能执行 `git push origin task-xxx`。合并到 `main` 分支的动作必须由人类 Owner 手动 Review 后执行，禁止使用代码自动 merge 主干。
4.  **状态追踪**：每次解决问题或完成核心逻辑修改，必须同步更新项目根目录的 `PROGRESS.md`，写明“问题现象、解决方案、防范措施”，并附上 Commit ID。

## 二、 后端开发规范 (FastAPI & Python)
1.  **纯异步编程**：AlphaReader 是全异步架构。所有的 I/O 操作（数据库读写、HTTP 请求、Redis 读取）必须使用 `await`。禁止使用阻塞式的同步代码（如 `requests`，必须用 `httpx.AsyncClient`）。
2.  **防御性容错**：在 `services/` 层与外部 API（如 DeepSeek、智谱、金融数据源）交互时，必须包含 `try/except` 块和重试机制（指数退避）。单条数据的解析失败绝不允许导致整个 Batch 或 Pipeline 崩溃。
3.  **不破坏数据源降级链**：在修改 `data_fetcher.py` 时，必须维持原有的“多级降级兜底”逻辑（例如 RS 计算的三级降级，NAV 计算的四级降级）。

## 三、 数据库与测试规范 (PostgreSQL)
1.  **禁止破坏性 DDL**：在任何情况下，禁止执行 `DROP TABLE`、`TRUNCATE` 或无 `WHERE` 条件的 `DELETE` 语句。
2.  **批量写入优化**：使用 `asyncpg` 时，优先使用批量写入（如 `executemany`）和单条 Savepoint（`session.begin_nested()`）以防局部失败导致整体回滚。
3.  **安全测试边界**：你只能连接 `api-key.json` 中配置的脱敏测试数据库和只读测试 Key。不要尝试去寻找或连接线上的生产数据库。

## 四、 前端开发规范 (Vue 3 uni-app)
1.  **组合式 API**：必须严格使用 `<script setup>` 语法编写所有 Vue 组件。
2.  **状态与通信**：禁止滥用全局事件总线，合理使用 Props/Emits 和前端缓存进行状态流转。保持 UI 的轻量化。