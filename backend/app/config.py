"""集中式配置管理 — 基于 pydantic-settings 从环境变量/.env 文件加载配置。

配置项分组：
  - 应用基础：APP_ENV / DEBUG / TIMEZONE
  - 日志：LOG_LEVEL / LOG_FORMAT
  - 跨域：CORS_ORIGINS
  - 智谱 AI：短文本 Embedding 去重 API 密钥
  - 硅基流动 SiliconFlow：免费 Embedding API（BAAI/bge-m3）+ 免费 LLM（Qwen3-8B 评分/情绪分析）
  - DeepSeek AI：API 密钥/地址/模型/批次大小/分数阈值/重试次数（仅摘要 digest 使用）
  - 调度器：Pipeline 运行时间范围
  - 告警：Webhook URL（支持飞书/钉钉/企微/Slack）
  - PostgreSQL：连接参数 + 连接池配置
  - Redis：连接参数 + 最大连接数

计算属性：
  - DATABASE_URL：根据 PG 各字段动态拼接 asyncpg DSN
  - REDIS_URL：根据 Redis 各字段动态拼接 DSN
"""

from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置类。

    优先级：环境变量 > .env 文件 > 代码默认值。
    .env 文件搜索路径：先找上级目录的 ../.env，再找当前目录的 .env。
    extra="ignore" 表示忽略 .env 中未定义的多余字段。
    """
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 应用基础 ──
    APP_ENV: str = "development"       # 运行环境：development / production
    DEBUG: bool = False                 # 调试模式开关（默认关闭，生产安全）
    TIMEZONE: str = "Asia/Shanghai"     # 调度器和日志使用的时区（A 股）
    US_TIMEZONE: str = "US/Eastern"     # 美股时区（美东）

    # ── 日志 ──
    LOG_LEVEL: str = "INFO"          # 日志级别：DEBUG / INFO / WARNING / ERROR / CRITICAL
    LOG_FORMAT: str = "text"         # 日志格式："text" 人类可读 / "json" 结构化

    # ── 跨域（CORS）──
    CORS_ORIGINS: str = "https://alphareader.site,http://localhost:5173"  # 逗号分隔的允许源

    # ── Finnhub 市场新闻 ──
    FINNHUB_API_KEY: str = Field("", repr=False)                        # Finnhub API Token (https://finnhub.io)

    # ── SEC EDGAR（一手 filing 流）──
    # SEC 强制要求请求方 UA 带联系邮箱，格式：<Company/Project> <email>
    # 建议在 .env 覆盖为真实运维邮箱；否则使用默认占位（仍可通过 SEC 校验，但不礼貌）
    SEC_CONTACT_EMAIL: str = "alphareader@example.com"

    # ── Embedding 去重 — 提供商切换 ──
    # 可选值："zhipu"（智谱 AI）或 "siliconflow"（硅基流动，免费）
    EMBEDDING_PROVIDER: str = "siliconflow"

    # ── 智谱 AI（短文本 Embedding 去重）──
    ZHIPU_API_KEY: str = Field("", repr=False)                          # 智谱 API Key (https://open.bigmodel.cn)
    ZHIPU_EMBEDDING_MODEL: str = "embedding-3"                      # Embedding 模型：embedding-3（可自定义维度）或 embedding-2（固定1024维）

    # ── 硅基流动 SiliconFlow（免费 Embedding + 免费 LLM 评分）──
    SILICONFLOW_API_KEY: str = Field("", repr=False)                    # SiliconFlow API Key (https://cloud.siliconflow.cn)
    SILICONFLOW_EMBEDDING_MODEL: str = "BAAI/bge-m3"               # 免费模型：BAAI/bge-m3(1024维) / BAAI/bge-large-zh-v1.5(1024维)
    SILICONFLOW_LLM_MODEL: str = "Qwen/Qwen3-8B"                  # 免费 LLM 模型（用于评分/情绪分析）
    SILICONFLOW_API_URL: str = "https://api.siliconflow.cn/v1/chat/completions"  # SiliconFlow Chat API

    # ── DeepSeek AI（摘要专用，评分已迁移至 SiliconFlow）──
    DEEPSEEK_API_KEY: str = Field("", repr=False)                       # API 密钥
    DEEPSEEK_API_URL: str = "https://api.deepseek.com/v1/chat/completions"  # API 地址
    DEEPSEEK_MODEL: str = "deepseek-chat"                           # 模型名称（仅 digest 使用）

    # ── LLM 评分/翻译（SiliconFlow Qwen3-8B）──
    # P4-B: 配置项从 DEEPSEEK_* 重命名为 LLM_*，AliasChoices 保持 .env 向后兼容
    LLM_BATCH_SIZE: int = Field(20, validation_alias=AliasChoices("LLM_BATCH_SIZE", "DEEPSEEK_BATCH_SIZE"))                        # 每批评分条数
    LLM_SCORE_THRESHOLD: int = Field(5, validation_alias=AliasChoices("LLM_SCORE_THRESHOLD", "DEEPSEEK_SCORE_THRESHOLD"))          # 入库分数阈值（≥5 才存储）
    LLM_MAX_RETRIES: int = Field(2, validation_alias=AliasChoices("LLM_MAX_RETRIES", "DEEPSEEK_MAX_RETRIES"))                       # API 失败最大重试次数
    LLM_CONTENT_PREVIEW_CHARS: int = Field(800, validation_alias=AliasChoices("LLM_CONTENT_PREVIEW_CHARS", "DEEPSEEK_CONTENT_PREVIEW_CHARS"))  # 送给 LLM 的正文预览长度
    LLM_MIN_CHINESE_RATIO_TITLE: float = Field(0.5, validation_alias=AliasChoices("LLM_MIN_CHINESE_RATIO_TITLE", "DEEPSEEK_MIN_CHINESE_RATIO_TITLE"))  # 中文标题最低中文占比
    LLM_MIN_CHINESE_RATIO_SUMMARY: float = Field(0.6, validation_alias=AliasChoices("LLM_MIN_CHINESE_RATIO_SUMMARY", "DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY"))  # 中文摘要最低中文占比
    LLM_CONTENT_RISK_BISECT_ENABLED: bool = Field(True, validation_alias=AliasChoices("LLM_CONTENT_RISK_BISECT_ENABLED", "DEEPSEEK_CONTENT_RISK_BISECT_ENABLED"))  # 内容审查触发时二分隔离
    LLM_CONTENT_RISK_MAX_DEPTH: int = Field(6, validation_alias=AliasChoices("LLM_CONTENT_RISK_MAX_DEPTH", "DEEPSEEK_CONTENT_RISK_MAX_DEPTH"))  # 二分最大递归深度
    LLM_TWO_STAGE_EN_ENABLED: bool = Field(True, validation_alias=AliasChoices("LLM_TWO_STAGE_EN_ENABLED", "DEEPSEEK_TWO_STAGE_EN_ENABLED"))  # 英文两阶段评分
    LLM_TRANSLATE_BATCH_SIZE: int = Field(20, validation_alias=AliasChoices("LLM_TRANSLATE_BATCH_SIZE", "DEEPSEEK_TRANSLATE_BATCH_SIZE"))  # 翻译阶段批次大小
    LLM_MAX_CONCURRENCY: int = Field(3, validation_alias=AliasChoices("LLM_MAX_CONCURRENCY", "DEEPSEEK_MAX_CONCURRENCY"))  # 批次并发度

    # ── 调度器 — Pipeline 定时执行 ──
    PIPELINE_START_HOUR: int = 0   # 起始小时（全天运行覆盖英文信源不同时区）
    PIPELINE_END_HOUR: int = 23    # 结束小时（0-23）
    PIPELINE_INTERVAL_MINUTES: int = 15  # 执行间隔（分钟），每小时 0/15/30/45 触发

    # ── 告警 — Pipeline 失败时的 Webhook 通知 ──
    # 支持：飞书/钉钉/企业微信/Slack/通用（根据 URL 自动识别平台）
    # 留空则禁用告警
    ALERT_WEBHOOK_URL: str = ""

    # ── Reports 同步鉴权 ──
    REPORT_SYNC_TOKEN: str = Field("", repr=False)  # Node.js 上传脚本使用的 Bearer Token，生产环境必须设置

    # ── API Key 全局鉴权 ──
    NEWS_API_KEY: str = Field("", repr=False)  # 为空则不启用鉴权（仅限开发环境）

    # ── Dashboard 密码保护 ──
    DASHBOARD_PASSWORD: str = Field("", repr=False)  # 为空则不保护（不推荐生产环境）

    # ── Sandbox（模拟仓）访问密码 ──
    SANDBOX_PASSWORD: str = Field("", repr=False)  # 为空则不需要密码（不推荐生产环境）

    # ── PostgreSQL 数据库 ──
    POSTGRES_USER: str = "alphareader"     # 数据库用户名
    POSTGRES_PASSWORD: str = Field("", repr=False)       # 数据库密码（必须通过 .env 设置）
    POSTGRES_DB: str = "alphareader"       # 数据库名
    POSTGRES_HOST: str = "db"              # 主机（Docker 容器名）
    POSTGRES_PORT: int = 5432              # 端口
    DB_POOL_SIZE: int = 5                  # SQLAlchemy 连接池大小
    DB_MAX_OVERFLOW: int = 10              # 连接池最大溢出数

    # ── Redis 缓存 ──
    REDIS_HOST: str = "cache"              # 主机（Docker 容器名）
    REDIS_PORT: int = 6379                 # 端口
    REDIS_DB: int = 0                      # 数据库编号
    REDIS_PASSWORD: str = Field("", repr=False)  # Redis 密码（生产环境必须设置）
    REDIS_MAX_CONNECTIONS: int = 20        # 最大连接数

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """根据各 PG 字段动态拼接异步 PostgreSQL 连接字符串（asyncpg 驱动）。"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        """根据各 Redis 字段动态拼接 Redis 连接字符串（含密码）。"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的 CORS_ORIGINS 字符串解析为列表。"""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


# 全局单例，其他模块通过 `from app.config import settings` 引用
settings = Settings()
