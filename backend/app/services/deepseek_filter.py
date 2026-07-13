"""向后兼容 shim —— 已迁移到 llm_news_filter.py。

P4-B: 文件从 deepseek_filter.py 重命名为 llm_news_filter.py，
此文件仅保留 re-export 以避免遗漏的 import 报错。
后续应全部迁移到 `from app.services.llm_news_filter import ...`。
"""
from app.services.llm_news_filter import *  # noqa: F401, F403
