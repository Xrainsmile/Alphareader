# AlphaReader 开发进度记录

## 2026-03-09: Daily Screener — Minervini Stage2 白名单筛选模块

### 问题/需求
需要一个每日收盘后自动运行的量化筛选脚本，基于 Mark Minervini 趋势交易体系（Stage 2 & VCP），
从全市场 5000+ 只 A 股中筛选出约 50-80 只符合严格技术面 + 基本面条件的准入白名单。

### 解决方案
创建模块化的 `backend/app/services/screener/` 包，包含 4 个核心文件：

| 文件 | 类 | 职责 |
|------|-----|------|
| `data_loader.py` | `DataLoader` | 从 PostgreSQL 加载 OHLCV、从 Parquet 加载/更新 EMA、从 akshare 批量拉取基本面 |
| `filters.py` | `MinerviniScreener` | Stage2 趋势过滤器（8 项量化条件：均线排列/底部反弹/前高逼近/筹码POC/箱体突破/放量/VCP收缩/大阳线） |
| `filters.py` | `FundamentalFilter` | 基本面过滤器（财务防雷/营收驱动/EPS环比加速） |
| `pipeline.py` | `ScreenerPipeline` | 串行管道编排（7 步流水线） |
| `runner.py` | CLI 入口 | 命令行参数支持，`python3 -m app.services.screener.runner` |

### 技术要点
1. **数据复用**：直接从现有 `stock_daily_quote` 表（175 万+行情记录）读取 OHLCV，
   无需额外数据源。EMA 使用增量公式更新，避免全量重算。
2. **性能**：SQL 窗口函数在数据库端完成极值计算；Pandas 向量化处理 5000+ 只股票；
   POC 等需要逐股计算的使用 groupby apply。
3. **容错**：每个过滤步骤独立 try/except；单只股票数据缺失不崩溃；
   基本面拉取失败时跳过基本面过滤。
4. **扩展性**：所有过滤阈值通过 dataclass 配置，支持 CLI 参数覆盖。

### 运行方式
```bash
# 服务器 Docker 环境
docker compose run --rm web python3 -m app.services.screener.runner

# 本地开发（需连 DB）
cd backend && python3 -m app.services.screener.runner --dry-run

# 定时任务（每个交易日 15:35）
35 15 * * 1-5 cd /home/Alphareader && docker compose run --rm web python3 -m app.services.screener.runner >> /tmp/screener.log 2>&1
```

### 输出
- 控制台打印漏斗统计 + Top 20 白名单
- `data/watchlists/watchlist_YYYYMMDD.json`（含 ticker, price, EPS, VCP Score）

### 防范措施
- 所有数据库操作只读（SELECT），不写入任何表
- EMA 快照写入本地文件，不影响线上数据
- akshare 请求带超时和重试
