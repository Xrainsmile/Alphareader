# EMA 快照数据说明

## 📊 数据概述

本目录包含 A 股市场所有标的的 EMA (指数移动平均线) 快照数据。

### EMA 指标周期
- EMA5: 5日指数移动平均
- EMA10: 10日指数移动平均
- EMA20: 20日指数移动平均
- EMA50: 50日指数移动平均
- EMA120: 120日指数移动平均
- EMA200: 200日指数移动平均

## 📁 文件格式

### Parquet 格式
- 文件名: `ema_snapshot_YYYYMMDD.parquet`
- 用途: 高效存储，适合程序读取
- 引擎: PyArrow

### CSV 格式
- 文件名: `ema_snapshot_YYYYMMDD.csv`
- 用途: 便于人工查看和Excel打开

### 数据结构
```
Code     : 股票代码 (6位数字)
Date     : 快照日期
Close    : 收盘价
EMA5     : 5日EMA
EMA10    : 10日EMA
EMA20    : 20日EMA
EMA50    : 50日EMA
EMA120   : 120日EMA
EMA200   : 200日EMA
```

## 🗓️ 已生成快照

### 任务1: 基于 history_lake 的历史快照
- **截止日期**: 2026-02-13
- **数据来源**: `/data/history_lake/`
- **标的数量**: 5,707 只
- **文件**: `ema_snapshot_20260213.parquet` (383 KB)

### 任务2: 开盘期间快照（2月24日 - 3月11日）

#### 已完成（基于 history_lake）
- **2026-02-24**: 5,116 只标的 (344 KB)
- **2026-02-25**: 5,113 只标的 (344 KB)
- **2026-02-26**: 5,112 只标的 (344 KB)
- **2026-02-27**: 5,112 只标的 (344 KB)

#### 进行中（基于腾讯财经 API）
- **日期范围**: 2026-02-28 ~ 2026-03-11
- **状态**: 后台任务运行中
- **预计完成**: 约 30-60 分钟
- **进度监控**: 运行 `python3 tools/check_ema_progress.py`

## 🛠️ 使用方法

### 读取 Parquet
```python
import pandas as pd

# 读取某日快照
df = pd.read_parquet('data/ema_snapshots/ema_snapshot_20260213.parquet')

# 查看数据
print(df.head())
print(f"共 {len(df)} 只标的")

# 筛选 EMA5 > EMA20 的标的
uptrend = df[df['EMA5'] > df['EMA20']]
```

### 读取 CSV
```python
import pandas as pd

df = pd.read_csv('data/ema_snapshots/ema_snapshot_20260213.csv')
```

### 查询特定标的
```python
# 查询贵州茅台 (600519)
moutai = df[df['Code'] == '600519']
print(moutai)
```

## 📈 数据用途

1. **趋势判断**: 比较不同周期EMA的排列关系
2. **支撑/阻力位**: EMA 常作为动态支撑/阻力位
3. **信号生成**: 
   - 短期EMA上穿长期EMA → 买入信号
   - 短期EMA下穿长期EMA → 卖出信号
4. **回测验证**: 基于历史EMA快照进行策略回测

## 🔄 更新机制

### 自动更新工具
```bash
# 更新特定日期范围
python3 tools/calculate_ema_snapshots_v2.py \
    --start-date 2026-03-12 \
    --end-date 2026-03-12 \
    --output-dir data/ema_snapshots

# 查看进度
python3 tools/check_ema_progress.py
```

### 数据来源优先级
1. **history_lake**: 优先使用本地历史数据（快速、离线）
2. **腾讯财经 API**: 补充缺失日期的数据（需联网）

## ⚠️ 注意事项

1. **EMA 计算需要足够历史数据**: 
   - EMA200 需要至少 200 个交易日的数据
   - 新上市股票可能部分 EMA 值为 NaN

2. **停牌/退市标的**:
   - 停牌期间无数据更新
   - ST、退市整理股已过滤

3. **复权处理**:
   - 所有价格均为前复权价格
   - 确保 EMA 计算的连续性

4. **北交所标的**:
   - 北交所（8开头代码）已排除
   - 腾讯财经 API 不支持北交所

## 🔧 工具脚本

| 脚本 | 功能 | 用法 |
|------|------|------|
| `calculate_ema_snapshots.py` | 单日快照计算 | 适合计算历史特定日期 |
| `calculate_ema_snapshots_v2.py` | 多日快照计算 | 支持日期范围，自动选择数据源 |
| `calculate_ema_api_batch.py` | 批量 API 拉取 | 支持断点续传、后台运行 |
| `check_ema_progress.py` | 进度监控 | 查看计算进度和文件统计 |

## 📞 问题排查

### 后台任务检查
```bash
# 查看是否在运行
ps aux | grep calculate_ema_api_batch

# 查看实时日志
tail -f data/ema_snapshots/api_fetch.log

# 停止后台任务
pkill -f calculate_ema_api_batch
```

### 重新开始
```bash
# 重置进度
python3 tools/calculate_ema_api_batch.py \
    --start-date 2026-02-28 \
    --end-date 2026-03-11 \
    --reset
```

---

**生成时间**: 2026-03-11  
**数据版本**: v1.0
