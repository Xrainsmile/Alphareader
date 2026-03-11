"""AlphaReader Daily Screener — 基于 Minervini 趋势交易体系的每日白名单筛选。

模块组成：
  - data_loader.py:  数据加载器，从 DB/EMA 快照/akshare 加载量价与基本面数据
  - filters.py:      Stage2 趋势过滤器 + 基本面过滤器（量化漏斗）
  - pipeline.py:     串行过滤管道编排
  - runner.py:       每日批处理入口（CLI 可执行）
"""
