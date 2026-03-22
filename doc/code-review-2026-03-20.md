拉取请求已成功合并并关闭
一切就绪 feat/daily-briefing 分支可以被安全删除。

---

# 2026-03-21 重构踩坑总结 & 避坑指南

## 为什么要重构

1. **安全裸奔**：API Key 明文比较（时序攻击）、CORS 全通配符、Redis 无密码
2. **API 不规范**：各端点返回格式不统一（有的裸 Pydantic model、有的裸 dict、有的 APIResponse 包装），前端解析逻辑混乱
3. **前端屎山**：`index/index.vue` 单文件 2207 行 Options API，15+ 个文件散布 300+ 处硬编码颜色，重复工具函数各写各的
4. **基础设施粗糙**：Dockerfile 单阶段构建镜像臃肿、Docker 无内存限制（4GB 服务器随时 OOM）、Nginx 无速率限制、无 CI/CD
5. **数据层隐患**：缺失关键索引、列类型不当（Date 用 String、volume 溢出）、连接池无回收

---

## 一、后端 API 层

### 坑 1：`response_model` 与实际返回类型不匹配 → 500

**现象**：价投 Tab 加载失败，前端报错，后端日志 `ResponseValidationError`。

**根因**：统一 API 响应格式时，把返回值从裸 Pydantic model 改成了 `APIResponse(data={...})` 包装，但**忘记移除** `@router.get` 上的 `response_model=ValueWatchlistResponse`。FastAPI 会用 `response_model` 验证返回值，期望顶层有 `count` 和 `items`，实际拿到的是 `{code, message, data}`，直接炸。

**涉及端点**：`vcp_watchlist`、`trend_watchlist`、`trend_watchlist/filters`、`value_watchlist`，共 4 个遗漏。

**避坑**：
- 统一响应包装这种"全局性改造"，做完后必须**逐个端点 `curl` 验证**，不能只改了代码就收工
- 建一个 checklist 列出所有端点，逐一勾选确认
- 如果用 `APIResponse` 统一包装，就**全局禁用 `response_model`**，二者只能选一种模式

---

## 二、前端 CSS / 样式

### 坑 2：mp-html 的 `tag-style` 中用 rpx → 浏览器不识别 → 字体巨大

**现象**：每日研报详情页和新闻概览 digest 的字体特别大，几乎不可读。

**根因**：`formatters.js` 中的 `detailTagStyle` 和 `listTagStyle` 使用了 rpx 单位（如 `font-size: 28rpx`）。关键误解在于——**mp-html 的 `tag-style` 是直接注入为 DOM 内联样式的**，uni-app 构建时**不会转换** JS 对象字符串里的 rpx。浏览器不认识 rpx，回退到默认的巨大字体。

**避坑**：
- 分清 uni-app 中 rpx 生效的两个场景：`.vue` 文件的 `<style>` 块 ✅ vs JS 字符串中的内联样式 ❌
- **mp-html 的 `tag-style` 必须用 px**，因为它绕过了 uni-app 的编译转换
- 凡是通过 JS 动态生成的样式字符串，一律用 px，不要用 rpx

### 坑 3：CSS 变量大规模替换（300+ 处）的风险

**背景**：用 65+ 个 CSS Custom Properties 替换 15+ 个文件中 300+ 处硬编码颜色。

**风险点**：
- `find + xargs + sed` 批量替换可能误伤（如 SVG 内联属性、JS 动态颜色数组）
- `mask-image` 中的 `#000` 是技术用途，不应替换

**避坑**：
- 大规模替换前先跑 `grep` 统计受影响行，分类处理
- 保留合理例外（SVG 内联、JS 动态色值、mask 遮罩），不强制 100% 迁移
- 替换后**每个页面都要视觉对比**，确认无色差

---

## 三、前端架构重构

### 坑 4：Options API → `<script setup>` 重写 2207 行巨型文件

**挑战**：`index/index.vue` 一个文件 2207 行，Options API，要重写为 `<script setup>` + 拆分子组件。

**踩过的问题**：
- uni-app 页面生命周期（`onShow`/`onHide`/`onPullDownRefresh`/`onReachBottom`）在 `<script setup>` 中需要通过 `getCurrentInstance().proxy.$options` 挂载
- 子组件样式穿透需要 `:deep()` 选择器
- composable 之间的数据流需要精心设计（筛选参数怎么传给 Feed、搜索和 Feed 如何互不干扰）

**避坑**：
- 大文件重构**不要一步到位**，先拆组件（纯移动代码），再改 API 风格
- 每拆出一个组件就**立即编译验证**，不要攒到最后一起验
- uni-app 的生命周期钩子坑多，先查文档确认 `<script setup>` 下的写法

---

## 四、Docker 构建 & 部署

### 坑 5：Docker BuildKit 并发构建 → 服务器卡死

**现象**：多次 `docker compose build` 命令被"跳过"后，实际在后台运行了约 6 个并发构建进程，4GB 小内存服务器直接卡死。

**根因**：命令超时被终端 skip 后，服务器端的进程并没有被杀掉，BuildKit 仍在后台编译。反复重试 = 反复叠加进程。

**避坑**：
- 远程构建前先 `ps aux | grep docker` 确认没有残留进程
- 构建卡住时先 `kill` 掉所有构建进程，再 `docker builder prune -f` 清缓存
- **4GB 内存服务器永远不要并发构建**，一次只 build 一个服务
- 使用 `nohup ... &` 后台构建，通过日志文件跟踪进度，避免 SSH 超时导致重复触发

### 坑 6：多阶段构建的 Dockerfile 踩坑

**背景**：为了减小镜像体积（~200MB），引入 builder + runtime 两阶段构建。

**风险点**：
- runtime 阶段必须安装正确的运行时库（`libpq5`、`libxml2`、`libxslt1.1`），少一个就 import 失败
- `CMD` 必须两个阶段完全一致，否则容器行为不一致

**避坑**：
- 多阶段构建后**必须完整测试**容器能否正常启动和响应
- 把运行时依赖列成清单，逐个确认

### 坑 7：磁盘空间 / 构建缓存堆积

**现象**：多次 `--no-cache` 构建后，Docker 构建缓存占满磁盘。

**解决**：`docker builder prune -f` 一次释放了 4.8GB。

**避坑**：
- 小服务器定期清理：`docker system prune -f`、`docker builder prune -f`
- 构建前先 `df -h` 检查可用空间

---

## 五、安全与配置

### 坑 8：API Key 比较用 `!=` → 时序攻击

**根因**：`auth.py` 中用 `!=` 比较 API Key，攻击者可通过响应时间差逐字符猜测密钥。

**修复**：改用 `hmac.compare_digest()` 常量时间比较。

**避坑**：凡是涉及密钥/密码比较的地方，**一律用 `hmac.compare_digest()`**。

### 坑 9：CORS 配置 `allow_methods=["*"]` / `allow_headers=["*"]`

**避坑**：生产环境 CORS **永远不要用通配符**，明确列出允许的 methods 和 headers。

---

## 六、总结：通用避坑原则

| 原则 | 说明 |
|------|------|
| **全局改造必须全量验证** | 统一响应格式、CSS 变量替换这类"改所有文件"的操作，必须逐个端点/页面验证 |
| **区分编译时 vs 运行时** | rpx 在 `.vue` style 块编译转换 ✅，在 JS 字符串中不转换 ❌ |
| **小服务器要精打细算** | 4GB 内存不允许并发构建，要监控进程和磁盘，后台构建 + 日志跟踪 |
| **远程命令要防幽灵进程** | SSH 超时 ≠ 进程终止，重试前先检查残留 |
| **安全是基本功不是可选项** | `hmac.compare_digest`、CORS 收紧、Redis 密码，都是标配 |
| **大文件重构分步走** | 拆一步验一步，不要攒到最后 |
