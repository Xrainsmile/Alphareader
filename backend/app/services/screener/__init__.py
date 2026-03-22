"""AlphaReader Daily Screener — 基于 Minervini 趋势交易体系的每日白名单筛选。

模块组成：
  VCP 策略（Minervini Stage2）：
  - data_loader.py:       数据加载器，从 DB/EMA 快照/akshare 加载量价与基本面数据
  - filters.py:           Stage2 趋势过滤器 + 基本面过滤器（量化漏斗）
  - pipeline.py:          串行过滤管道编排
  - runner.py:            每日批处理入口（CLI 可执行，支持 --market CN/US）

  右侧趋势策略（双均线趋势突破）：
  - trend_filters.py:     右侧趋势过滤器（SMA/ADX/RSI + 5 条漏斗）
  - trend_pipeline.py:    趋势筛选管道编排
  - trend_runner.py:      趋势策略批处理入口（CLI 可执行，支持 --market CN/US）

  共享模块：
  - enricher.py:          数据补充器（行业/题材/主营/资金流向，仅 A 股）
  - utils.py:             公共工具函数（ST 剔除/股票名称加载等）
"""
