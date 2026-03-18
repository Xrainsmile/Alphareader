# AlphaReader Screener — 完整逻辑文档

> 基于 Minervini Stage2 模型的 A 股每日白名单筛选系统

---

## 一、系统架构

```
runner.py              ── 命令行入口，解析参数，启动 pipeline
  └── pipeline.py      ── 管道编排，串联 7 步流水线
        ├── data_loader.py    ── 数据层：PostgreSQL 行情、Parquet EMA 快照、akshare 基本面
        ├── filters.py        ── 算法层：8 条技术面条件 (Stage2) + 4 条基本面条件
        └── models/screener.py ── 持久层：运行记录 + 白名单的 ORM 模型
```

**数据流向**：全市场 ~5500 只股票 → 条件 A（趋势确立）→ 条件 B（筹码+突破+放量）→ 条件 C（VCP 收敛+大阳线）→ 基本面防雷与加速检查 → **最终白名单**（按 VCP Score 排序）

---

## 二、Pipeline 7 步流水线

| Step | 名称 | 数据源 | 作用 |
|------|------|--------|------|
| 1 | OHLCV 加载 | PostgreSQL `stock_daily_quote` | 加载近 130 自然日（~90 交易日）全市场行情数据 |
| 2 | EMA 加载/更新 | 本地 Parquet 快照 | 加载最新 EMA 快照；如果快照日期早于最新交易日，执行增量更新 |
| 3 | 价格极值计算 | PostgreSQL（SQL 窗口函数） | 计算 120 日最低价、60 日最高价、50 日均量、最新收盘价/成交量 |
| 4 | Stage2 趋势过滤 | Step 1-3 的数据 | 8 项技术面条件串行漏斗，淘汰不满足 Minervini 趋势模型的股票 |
| 5 | 基本面数据拉取 | akshare（东方财富 API） | 拉取最近 3 个季度的全市场业绩报告（EPS/营收/净利润/现金流） |
| 6 | 基本面过滤 | Step 5 数据 | 4 项基本面条件：防雷 + 营收驱动 + EPS 加速 |
| 7 | 输出 | JSON 文件 + PostgreSQL | 组装白名单 → 保存 JSON → 写入 DB → 控制台打印漏斗 |

**容错设计**：每步独立 try/except，单步失败不崩溃。Step 5-6（基本面）失败时使用 Stage2 结果直接输出。

---

## 三、Stage2 技术面过滤器（8 项条件）

### 条件 A：趋势与底部确立

| 编号 | 条件名称 | 公式 | 默认参数 | 含义 |
|------|---------|------|---------|------|
| A1 | 均线多头排列 | `EMA20 > EMA50 > EMA120` | — | 短/中/长期均线多头排列，确认上升趋势 |
| A2 | 脱离底部 ≥30% | `Close ≥ min(Low, 120日) × bottom_rebound_pct` | `1.30` | 已从 120 日最低点反弹至少 30%，确认脱离底部区域 |
| A3 | 逼近前高 ≤15% | `Close ≥ max(High, 60日) × near_high_pct` | `0.85` | 距离 60 日最高价不超过 15% 差距，说明正在向前高进攻 |

### 条件 B：筹码支撑 + 箱体突破 + 放量确认

| 编号 | 条件名称 | 公式 | 默认参数 | 含义 |
|------|---------|------|---------|------|
| B1 | 站上筹码峰值 | `Close > Price_POC(120日)` | — | 股价站上 120 日内成交量最密集的价格区间（筹码峰值），说明多数持仓者浮盈 |
| B2 | 箱体突破 90% | `Close > Quantile(Close, 60日, 0.90)` | `q=0.90, window=60` | 股价突破 60 日收盘价的 90% 分位，突破整理区间 |
| B3 | 放量 ≥1.5x | `Volume > MA(Volume, 50日) × volume_ratio` | `1.5` | 最新交易日成交量超过 50 日均量的 1.5 倍，有资金介入 |

### 条件 C：形态收敛与资金活跃度

| 编号 | 条件名称 | 公式 | 默认参数 | 含义 |
|------|---------|------|---------|------|
| C1 | VCP 波动收缩 | `ATR(20) ≤ ATR(60) × vcp_atr_ratio` | `0.8` | 短期波动率小于长期波动率的 80%，即 Volatility Contraction Pattern（VCP），价格在收敛 |
| C2 | 大阳线活跃 | `20日内至少 1 根涨幅 ≥ yang_threshold% 的大阳线` | `7.0%` | 近期有强势大阳线，说明主力资金活跃 |

### 过滤顺序（串行漏斗）

```
全市场 ~5500 只
  │ A1 EMA20 > EMA50 > EMA120
  ├─→ ~2800 只
  │ A2 脱离底部 ≥30%
  ├─→ ~1600 只
  │ A3 逼近前高 ≤15%
  ├─→ ~1100 只
  │ B1 站上筹码峰值 (POC)
  ├─→ ~1060 只
  │ B2 箱体突破 90% 分位
  ├─→ ~710 只
  │ B3 放量 ≥1.5x
  ├─→ ~310 只
  │ C1 VCP 波动收缩 (ATR20 ≤ ATR60 × 0.8)
  ├─→ ~??? 只
  │ C2 大阳线 ≥7%
  └─→ ~??? 只  →  进入基本面过滤
```

> 注：B1/B2/B3 中 NaN 值不淘汰（即数据缺失时放行）。

---

## 四、基本面过滤器（4 项条件）

| 编号 | 条件名称 | 逻辑 | 默认参数 | 含义 |
|------|---------|------|---------|------|
| F1a | 防雷-连续亏损 | 最近 2 期净利润均为负 **且** 最新季度营收 < `min_revenue_for_loss` | `1亿` | 小营收+连续亏损 = 高风险 |
| F1b | 防雷-现金流造假 | 经营现金流为负 **且** EPS > 0 **且** 现金流/EPS < `cashflow_fraud_threshold` | `-0.5` | 利润高但没有现金流入 = 疑似财务造假 |
| F2 | 营收驱动 | 最新季度营收同比增长 < `min_revenue_yoy` → 淘汰 | `20%` | 要求营收有至少 20% 的同比增长 |
| F3 | EPS 环比加速 | `EPS_Q0 > EPS_Q-1 > EPS_Q-2`（连续 3 期递增） | 开/关 | 盈利能力逐季加速，Minervini 核心选股标准 |

**数据源**：akshare `stock_yjbb_em`（东方财富业绩报表），取最近 3 个季度。

**容错**：
- 基本面数据缺失的股票不一票否决，放行但标记
- 单只股票分析异常不崩溃，放行
- 整个 Step 5 拉取失败时跳过基本面过滤，使用 Stage2 结果

---

## 五、辅助计算函数

### ATR (Average True Range)

```
TR = max(High - Low, |High - Close_prev|, |Low - Close_prev|)
ATR(n) = SMA(TR, n)
```

- 用于 C1 条件：比较 ATR(20) 与 ATR(60)
- 向量化计算：pandas groupby + rolling

### POC (Point of Control)

```
取过去 120 日行情，按价格等分 20 个桶
每桶累加成交量
POC = 成交量最大桶的中位价
```

- 用于 B1 条件：股价是否站上筹码峰值
- 逐股 groupby apply 计算

### EMA 增量更新

```
k = 2 / (period + 1)
EMA_today = Close_today × k + EMA_yesterday × (1 - k)
```

- 6 条均线同时更新：EMA5/10/20/50/120/200
- 快照以 Parquet 格式存储在 `data/ema_snapshots/`

---

## 六、可调参数一览

### Stage2 技术面参数 (`Stage2FilterConfig`)

| 参数名 | CLI 参数 | 默认值 | 说明 |
|--------|---------|--------|------|
| `ema_trend_check` | — | `True` | 是否检查 EMA 多头排列 |
| `bottom_rebound_pct` | `--bottom-rebound` | `1.30` | 脱离底部倍数（1.30 = 反弹 30%） |
| `near_high_pct` | `--near-high` | `0.85` | 逼近前高比例（0.85 = 距前高 ≤15%） |
| `volume_ratio` | `--volume-ratio` | `1.5` | 放量倍数 |
| `quantile_close_q` | — | `0.90` | 箱体突破分位数 |
| `quantile_close_window` | — | `60` | 箱体窗口（交易日） |
| `vcp_atr_ratio` | `--vcp-atr-ratio` | `0.8` | VCP 波动收缩比（ATR20 ≤ ATR60 × 此值） |
| `big_yang_threshold` | `--yang-threshold` | `7.0` | 大阳线涨幅阈值（%） |
| `big_yang_window` | — | `20` | 大阳线检测窗口（交易日） |

### 基本面参数 (`FundamentalFilterConfig`)

| 参数名 | CLI 参数 | 默认值 | 说明 |
|--------|---------|--------|------|
| `min_revenue_for_loss` | — | `1e8`（1 亿） | 净利润连亏时最低营收门槛 |
| `cashflow_fraud_threshold` | — | `-0.5` | 经营现金流/EPS 比值下限 |
| `min_revenue_yoy` | `--min-revenue-yoy` | `20.0` | 最低营收同比增长（%） |
| `eps_acceleration` | `--no-eps-check` 反转 | `True` | 是否启用 EPS 环比加速检查 |

---

## 七、运行方式

### 命令行

```bash
# 在 backend/ 目录下
cd /path/to/AlphaReader/backend

# 基本运行
python3 -m app.services.screener.runner

# Dry-run（只打印不保存）
python3 -m app.services.screener.runner --dry-run

# 调参运行（放宽 VCP 和大阳线条件）
python3 -m app.services.screener.runner --vcp-atr-ratio 1.0 --yang-threshold 5.0

# 关闭基本面过滤
python3 -m app.services.screener.runner --no-fundamental

# Docker 容器内运行（服务器）
docker compose exec -T web python3 -m app.services.screener.runner
```

### 定时任务

```cron
# 每个交易日 15:35 运行
35 15 * * 1-5 cd /home/Alphareader && docker compose run --rm web python3 -m app.services.screener.runner >> /tmp/screener.log 2>&1
```

---

## 八、数据库模型

### `screener_runs` 表 — 运行记录

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | 自增主键 |
| run_date | DATE | 运行日期 |
| started_at | DATETIME(tz) | 开始时间 |
| finished_at | DATETIME(tz) | 结束时间 |
| duration_sec | FLOAT | 耗时（秒） |
| total_input | INT | 全市场输入股票数 |
| stage2_passed | INT | Stage2 通过数 |
| fundamental_passed | INT | 基本面通过数 |
| final_count | INT | 最终白名单数 |
| stats | JSONB | 完整漏斗统计（含各子步骤） |
| errors | JSONB | 错误信息列表 |
| status | VARCHAR(16) | success / partial / failed |

### `watchlist_daily` 表 — 每日白名单

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | 自增主键 |
| run_date | DATE | 白名单日期 |
| ts_code | VARCHAR(10) | 股票代码 |
| current_price | FLOAT | 当前价格 |
| ema20 | FLOAT | 20 日 EMA |
| ema50 | FLOAT | 50 日 EMA |
| ema120 | FLOAT | 120 日 EMA |
| vcp_score | FLOAT | VCP 得分 = 1 - ATR20/ATR60，越大越收敛 |
| eps_growth | FLOAT | EPS 同比增长率 |
| revenue_yoy | FLOAT | 营收同比增长率 |
| run_id | INT FK | 关联 screener_runs.id |

唯一约束：`(run_date, ts_code)`

---

## 九、最近一次运行结果分析（2025-03-11）

```
全市场: 5,492 只
  A1 均线多头:     2,791
  A2 脱离底部:     1,624
  A3 逼近前高:     1,103
  B1 筹码峰值:     1,063
  B2 箱体突破:       715
  B3 放量确认:       316
  C1 VCP 收缩:         0   ← 全部被淘汰
  C2 大阳线:           0
  最终白名单:          0
```

**瓶颈分析**：C1（VCP 波动收缩 `ATR20 ≤ ATR60 × 0.8`）把所有 316 只全部淘汰了。

**可能原因**：
1. 当前市场短期波动性较大（大盘震荡），短期 ATR 普遍高于长期 ATR
2. `vcp_atr_ratio = 0.8` 要求太严格（要求短期波动率比长期低 20%）
3. C1 和 C2 是"且"关系，C1 已经清零后 C2 无意义

**调参建议**：
- 放宽 `--vcp-atr-ratio` 从 0.8 → 1.0~1.2（允许短期波动与长期持平或略高）
- 放宽 `--yang-threshold` 从 7.0 → 4.0~5.0（降低大阳线要求）
- 或者先单独跑 `--no-fundamental` 看纯技术面能选出多少

---

## 十、文件路径清单

| 文件 | 路径 |
|------|------|
| 入口脚本 | `backend/app/services/screener/runner.py` |
| 管道编排 | `backend/app/services/screener/pipeline.py` |
| 过滤器 | `backend/app/services/screener/filters.py` |
| 数据加载 | `backend/app/services/screener/data_loader.py` |
| DB 模型 | `backend/app/models/screener.py` |
| EMA 快照 | `data/ema_snapshots/*.parquet` |
| 白名单输出 | `data/watchlists/watchlist_YYYYMMDD.json` |

---

# 右侧趋势 Screener — 完整逻辑文档

> 基于双均线趋势突破模型的 A 股每日白名单筛选系统（与 VCP Screener 并行）

---

## 十一、右侧趋势系统架构

```
trend_runner.py         ── 命令行入口，解析参数，启动 pipeline
  └── trend_pipeline.py ── 管道编排，串联 5 步流水线
        ├── data_loader.py       ── [复用] 数据层：PostgreSQL 行情数据
        ├── trend_filters.py     ── 算法层：5 条技术面条件 + 趋势综合得分
        ├── enricher.py          ── [复用] 补充行业/题材/资金
        └── models/screener.py   ── 持久层：TrendScreenerRun + TrendWatchlistDaily ORM
```

**数据流向**：全市场 ~5500 只股票 → 剔除 ST → 日均成交额过滤 → T1 MA 多头排列 → T2 ADX 趋势强度 → T3 20 日高点突破 → T4 放量确认 → T5 RSI 动量区间 → **最终白名单**（按 trend_score 排序）

---

## 十二、Trend Pipeline 5 步流水线

| Step | 名称 | 数据源 | 作用 |
|------|------|--------|------|
| 1 | OHLCV 加载 | PostgreSQL `stock_daily_quote` | 加载近 120 自然日（~80 交易日）全市场行情数据 |
| 1.5 | ST 剔除 | PostgreSQL | 排除最新交易日名称含 ST 的股票 |
| 2 | 技术面过滤 | Step 1 的数据 | 日均成交额 + 5 项技术面条件串行漏斗 |
| 3 | 数据补充 | akshare（东方财富 API） | 补充行业、题材概念、主营业务、资金流向 |
| 4 | 输出 | JSON 文件 + PostgreSQL | 组装白名单 → 保存 JSON → 写入 DB → 控制台打印漏斗 |

**容错设计**：每步独立 try/except，单步失败不崩溃。数据补充（Step 3）失败时白名单仍正常输出。

---

## 十三、右侧趋势技术面过滤器（5 项条件）

### 基础筛选

| 条件 | 公式 | 默认参数 | 含义 |
|------|------|---------|------|
| 排除 ST | 名称包含 'ST' → 剔除 | — | 排除高退市风险股票 |
| 日均成交额 | MA(Amount, 20日) ≥ min_avg_amount | `2000万元` | 确保足够的流动性 |

### 条件 T1：MA 多头排列

| 公式 | 含义 |
|------|------|
| `Close > SMA20 > SMA50` | 短/中期均线多头排列 |
| `SMA20_today > SMA20_(today-5)` | SMA20 方向向上（5 日斜率） |
| `SMA50_today > SMA50_(today-5)` | SMA50 方向向上（5 日斜率） |

### 条件 T2：ADX 趋势强度

| 公式 | 默认参数 | 含义 |
|------|---------|------|
| `ADX(14) > adx_threshold` | `25` | 确认市场处于趋势状态（非震荡） |

ADX 计算方法（Wilder's）：
```
+DM = max(High_today - High_yesterday, 0) [当 +DM > -DM]
-DM = max(Low_yesterday - Low_today, 0)   [当 -DM > +DM]
TR  = max(H-L, |H-C_prev|, |L-C_prev|)
ATR14 = Wilder smooth(TR, 14)
+DI  = 100 × smooth(+DM) / ATR14
-DI  = 100 × smooth(-DM) / ATR14
DX   = 100 × |+DI - -DI| / (+DI + -DI)
ADX  = Wilder smooth(DX, 14)
```

### 条件 T3：20 日高点突破

| 公式 | 默认参数 | 含义 |
|------|---------|------|
| `Close ≥ max(High, 20日)` | `window=20` | 价格创 20 日新高，确认突破 |

### 条件 T4：放量确认

| 公式 | 默认参数 | 含义 |
|------|---------|------|
| `Volume ≥ MA(Volume, 20日) × volume_ratio` | `1.5` | 突破伴随放量，有资金介入 |

### 条件 T5：RSI 动量区间

| 公式 | 默认参数 | 含义 |
|------|---------|------|
| `rsi_lower < RSI(14) < rsi_upper` | `50 < RSI < 80` | 有动量但不过热 |

RSI 计算方法（Wilder's）：
```
gains = max(close_delta, 0)
losses = max(-close_delta, 0)
avg_gain = Wilder smooth(gains, 14)
avg_loss = Wilder smooth(losses, 14)
RS  = avg_gain / avg_loss
RSI = 100 - 100 / (1 + RS)
```

### 过滤顺序（串行漏斗）

```
全市场 ~5500 只
  │ 剔除 ST
  ├─→ ~5300 只
  │ 日均成交额 > 2000 万
  ├─→ ~2500 只
  │ T1 Close > SMA20 > SMA50 向上
  ├─→ ~??? 只
  │ T2 ADX(14) > 25
  ├─→ ~??? 只
  │ T3 Close ≥ 20 日最高价
  ├─→ ~??? 只
  │ T4 Volume ≥ 20 日均量 × 1.5
  ├─→ ~??? 只
  │ T5 50 < RSI(14) < 80
  └─→ ~??? 只  →  最终白名单
```

---

## 十四、趋势综合得分 (trend_score)

```
trend_score = 0.4 × ADX_norm + 0.3 × RSI_norm + 0.3 × VolRatio_norm

ADX_norm     = min(ADX / 50, 1.0)           — ADX 越高趋势越强
RSI_norm     = clamp((RSI - 50) / 30, 0, 1) — RSI 越高动量越强
VolRatio_norm = min(vol_ratio / 3.0, 1.0)    — 放量倍数越高越好
```

得分范围 [0, 1]，越高代表趋势越强、动量越足、资金介入越多。

---

## 十五、可调参数一览 (`TrendFilterConfig`)

| 参数名 | CLI 参数 | 默认值 | 说明 |
|--------|---------|--------|------|
| `min_avg_amount` | `--min-avg-amount` | `2e7` | 日均成交额下限（2000 万元） |
| `amount_window` | — | `20` | 成交额计算窗口 |
| `ma_short` | `--ma-short` | `20` | 短期均线周期 (SMA20) |
| `ma_long` | `--ma-long` | `50` | 长期均线周期 (SMA50) |
| `ma_slope_window` | — | `5` | 均线方向判断窗口 |
| `adx_period` | — | `14` | ADX 周期 |
| `adx_threshold` | `--adx-threshold` | `25.0` | ADX 趋势强度下限 |
| `breakout_window` | `--breakout-window` | `20` | 突破回溯窗口 |
| `volume_ratio` | `--volume-ratio` | `1.5` | 放量倍数 |
| `volume_ma_window` | — | `20` | 均量计算窗口 |
| `rsi_period` | — | `14` | RSI 周期 |
| `rsi_lower` | `--rsi-lower` | `50.0` | RSI 下限 |
| `rsi_upper` | `--rsi-upper` | `80.0` | RSI 上限 |

---

## 十六、运行方式

### 命令行

```bash
cd /path/to/AlphaReader/backend

# 基本运行
python3 -m app.services.screener.trend_runner

# Dry-run（只打印不保存）
python3 -m app.services.screener.trend_runner --dry-run

# 调参运行（放宽 ADX 和 RSI）
python3 -m app.services.screener.trend_runner --adx-threshold 20 --rsi-lower 45

# Docker 容器内运行
docker compose exec -T web python3 -m app.services.screener.trend_runner
```

### 定时任务

```
# 每个交易日 15:45 运行（在 VCP Screener 15:40 之后）
# 由 scheduler.py 中的 _trend_screener_job 自动调度
```

---

## 十七、数据库模型

### `trend_screener_runs` 表 — 运行记录

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | 自增主键 |
| run_date | DATE | 运行日期 |
| started_at | DATETIME(tz) | 开始时间 |
| finished_at | DATETIME(tz) | 结束时间 |
| duration_sec | FLOAT | 耗时（秒） |
| total_input | INT | 全市场输入股票数 |
| trend_passed | INT | 趋势过滤通过数 |
| final_count | INT | 最终白名单数 |
| stats | JSONB | 完整漏斗统计 |
| errors | JSONB | 错误信息列表 |
| status | VARCHAR(16) | success / partial / failed |

### `trend_watchlist_daily` 表 — 每日白名单

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | 自增主键 |
| run_date | DATE | 白名单日期 |
| ts_code | VARCHAR(10) | 股票代码 |
| name | VARCHAR(32) | 股票名称 |
| current_price | FLOAT | 当前价格 |
| ma20 | FLOAT | SMA20 |
| ma50 | FLOAT | SMA50 |
| adx | FLOAT | ADX(14) 值 |
| rsi | FLOAT | RSI(14) 值 |
| volume_ratio | FLOAT | 放量倍数 (当日量/20日均量) |
| trend_score | FLOAT | 趋势综合得分 [0,1] |
| industry | VARCHAR(64) | 行业 |
| concepts | VARCHAR(512) | 概念板块 |
| main_business | TEXT | 主营业务 |
| fund_flow_net | FLOAT | 主力净流入（万元） |
| run_id | INT FK | 关联 trend_screener_runs.id |

唯一约束：`(run_date, ts_code)`

---

## 十八、趋势策略文件路径清单

| 文件 | 路径 |
|------|------|
| 入口脚本 | `backend/app/services/screener/trend_runner.py` |
| 管道编排 | `backend/app/services/screener/trend_pipeline.py` |
| 过滤器 | `backend/app/services/screener/trend_filters.py` |
| 数据加载 | `backend/app/services/screener/data_loader.py`（复用） |
| 数据补充 | `backend/app/services/screener/enricher.py`（复用） |
| DB 模型 | `backend/app/models/screener.py` |
| 白名单输出 | `data/trend_watchlists/trend_watchlist_YYYYMMDD.json` |
| API 端点 | `GET /api/v1/stocks/trend_watchlist` |
| 筛选枚举 | `GET /api/v1/stocks/trend_watchlist/filters` |
