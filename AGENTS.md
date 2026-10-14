# AlphaReader 研发规范（AI 助手强制入口）

> 本文件供所有 AI 编码助手（Claude Code、Cursor、CodeBuddy、Copilot 等）在进入本项目时自动读取。
> **修改任何前端 UI 前，必须先读取下方规范文档。**

## 一、必读文档（按优先级）

| 优先级 | 文档 | 用途 |
|---|---|---|
| P0 | [前端设计规范](./docs/frontend-design-spec.md) | **所有 UI 改动的唯一权威依据**，含令牌、色彩、排版、圆角、间距、层级、响应式、组件、强制禁令 |
| P1 | [架构与上下文索引](./claude.context.md) | 技术栈、业务闭环、部署架构、文件寻址地图 |
| P1 | [世界线设计](./docs/world-thread-design.md) §4.2 | **章节排序的唯一权威口径**（`chapter_no DESC` 三级回退）与两起分叉事故教训（排序键分叉 / 聚合作用域分叉）；改任何章节 `ORDER BY` 或任何展示「第 N 章」的聚合前必读 |
| P2 | [设计令牌映射表](./docs/design-token-map.md) | 硬编码色值 → 令牌的替换对照 |
| P3 | [前端组件规范](./front.md) | 胶囊搜索栏 `.vcp-*` 类名体系（强制复用） |

## 二、前端硬性约束摘要

违反以下任一条即视为设计走偏，**AI 不得提交此类代码**：

1. **禁止裸色值**：业务 `.vue` / `.css` 中不得出现十六进制色值。唯一允许写死色值处是 `frontend/src/App.vue` 的 `:root` 令牌定义区。
2. **禁止跨档混用单位**：移动端用 `--*-r-*`（rpx），PC 档（≥768px）用 `--*-p-*`（px），不得互换。
3. **禁止覆盖旧圆角令牌**：`--radius-sm/md/lg/pill`（rem）已被引用，新圆角用 `--radius-r-*` / `--radius-p-*`。
4. **禁止新造搜索样式**：搜索/筛选交互必须复用 `.vcp-*` 类名体系。
5. **禁止内联 emoji 当图标**：一律用 `IconSvg` 的 `name` 枚举。
6. **禁止写死 z-index**：用 `--z-base/sticky/overlay/modal`。
7. **禁止只做单端**：UI 变更须同时验证 `<768px`、`≥768px`、`≥1200px` 三档。
8. **禁止新增断点**：全站仅 768px 与 1200px 两个断点。
9. **禁止新造空态**：空数据一律用 `EmptyState` 组件。
10. **禁止数字用非等宽字体**：价格、涨跌幅、KPI、评分必须用 `--font-numeric`。
11. **禁止章节排序各写一套**：任何返回章节列表的接口，`ORDER BY` 必须与
    `workbench.py::_chapter_rows` 逐字一致（`chapter_no DESC` 三级回退）。
    两个页面各排各的会导致「按章号摘错章」——治理动作是按章号寻址的。
12. **禁止章号在子集作用域内聚合**：任何展示「第 N 章」的地方，章号必须跨
    **整条线**的全量章节取（`MAX(chapter_no)` 独立子查询），
    不得受上层 `WHERE`（如 `digest_id`）压缩作用域。
    「本期 +M」是子集属性、「第 N 章」是全集属性，混在同一条 `WHERE` 下必错一个。
    已发生过（2026-10-14）：简报世界线进展区块显示 34 章而详情页是 36 章。

完整令牌表、色值、字号刻度、组件清单见 [前端设计规范](./docs/frontend-design-spec.md)。

## 三、其他项目约束

- **技术栈**：后端 Python FastAPI（纯异步）+ PostgreSQL 16 + Redis 7；前端 uni-app + Vue 3 组合式 API。
- **Sandbox Admin**（`/sandbox-admin`）为纯后端渲染单文件 `backend/app/sandbox_admin.py`，**不走 Vue**，新增管理功能优先在此扩展。
- **新闻分类**：仅「财经」「科技」两类，前端顶部平铺 Tab 切换。
- **RS Rating**：前端页面已隐藏（代码注释保留），后端定时任务继续运行。
- **部署**：腾讯云 Lighthouse，4 容器 docker-compose，命令见 `claude.context.md`。
- **页面背景基准**：`--color-bg: #f6f7fb`，导航栏白底黑字。

## 四、规范变更

当设计令牌、断点、组件体系发生变化时，**必须同步更新** `docs/frontend-design-spec.md`，并回头核对本文件摘要是否仍准确。
