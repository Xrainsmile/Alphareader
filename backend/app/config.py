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

from pydantic import AliasChoices, Field, computed_field, model_validator
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

    # ── 硅基流动 SiliconFlow（仅用于 Embedding 去重）──
    # 评分/分析已迁移至 DeepSeek（见下方 LLM_* 配置），此处仅保留 Embedding 配置。
    SILICONFLOW_API_KEY: str = Field("", repr=False)                    # SiliconFlow API Key (https://cloud.siliconflow.cn)
    SILICONFLOW_EMBEDDING_MODEL: str = "BAAI/bge-m3"               # Embedding 模型：BAAI/bge-m3(1024维) / BAAI/bge-large-zh-v1.5(1024维)

    # ── DeepSeek AI（摘要/研报专用，流式调用）──
    # deepseek-chat / deepseek-reasoner 将于 2026/07/24 弃用，默认升级为 v4-flash
    DEEPSEEK_API_KEY: str = Field("", repr=False)                       # API 密钥（同时供评分复用，见 LLM_API_KEY）
    DEEPSEEK_API_URL: str = "https://api.deepseek.com/v1/chat/completions"  # API 地址（OpenAI 兼容）
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"                        # 摘要/研报模型（digest / briefing 使用）

    # ── LLM 评分/翻译/分析/公司名映射（DeepSeek-V4-flash）──
    # 评分等高频结构化任务用 v4-flash（便宜），摘要等长文本用 DEEPSEEK_MODEL。
    # LLM_API_KEY 通过 AliasChoices 复用 DEEPSEEK_API_KEY：只配一个 DeepSeek key 即可同时驱动评分与摘要。
    LLM_API_KEY: str = Field("", repr=False, validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY"))  # 评分/分析用 key（默认复用 DeepSeek key）
    LLM_API_URL: str = "https://api.deepseek.com/v1/chat/completions"  # 评分/分析 API 地址（OpenAI 兼容）
    LLM_MODEL: str = "deepseek-v4-flash"                            # 评分/分析模型（结构化 JSON 输出）

    # ── LLM 评分参数（AliasChoices 兼容旧 DEEPSEEK_* 环境变量名）──
    LLM_BATCH_SIZE: int = Field(20, validation_alias=AliasChoices("LLM_BATCH_SIZE", "DEEPSEEK_BATCH_SIZE"))                        # 每批评分条数
    LLM_SCORE_THRESHOLD: int = Field(5, validation_alias=AliasChoices("LLM_SCORE_THRESHOLD", "DEEPSEEK_SCORE_THRESHOLD"))          # 入库分数阈值（≥5 才存储）
    LLM_MAX_RETRIES: int = Field(2, validation_alias=AliasChoices("LLM_MAX_RETRIES", "DEEPSEEK_MAX_RETRIES"))                       # API 失败最大重试次数
    LLM_CONTENT_PREVIEW_CHARS: int = Field(400, validation_alias=AliasChoices("LLM_CONTENT_PREVIEW_CHARS", "DEEPSEEK_CONTENT_PREVIEW_CHARS"))  # 送给 LLM 的正文预览长度（800→400：投资相关性判断主要看标题+开头，省 ~40% 输入 token）
    LLM_MIN_CHINESE_RATIO_TITLE: float = Field(0.5, validation_alias=AliasChoices("LLM_MIN_CHINESE_RATIO_TITLE", "DEEPSEEK_MIN_CHINESE_RATIO_TITLE"))  # 中文标题最低中文占比
    LLM_MIN_CHINESE_RATIO_SUMMARY: float = Field(0.6, validation_alias=AliasChoices("LLM_MIN_CHINESE_RATIO_SUMMARY", "DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY"))  # 中文摘要最低中文占比
    LLM_CONTENT_RISK_BISECT_ENABLED: bool = Field(True, validation_alias=AliasChoices("LLM_CONTENT_RISK_BISECT_ENABLED", "DEEPSEEK_CONTENT_RISK_BISECT_ENABLED"))  # 内容审查触发时二分隔离
    LLM_CONTENT_RISK_MAX_DEPTH: int = Field(6, validation_alias=AliasChoices("LLM_CONTENT_RISK_MAX_DEPTH", "DEEPSEEK_CONTENT_RISK_MAX_DEPTH"))  # 二分最大递归深度
    LLM_TWO_STAGE_EN_ENABLED: bool = Field(True, validation_alias=AliasChoices("LLM_TWO_STAGE_EN_ENABLED", "DEEPSEEK_TWO_STAGE_EN_ENABLED"))  # 英文两阶段评分
    LLM_TRANSLATE_BATCH_SIZE: int = Field(20, validation_alias=AliasChoices("LLM_TRANSLATE_BATCH_SIZE", "DEEPSEEK_TRANSLATE_BATCH_SIZE"))  # 翻译阶段批次大小
    LLM_MAX_CONCURRENCY: int = Field(3, validation_alias=AliasChoices("LLM_MAX_CONCURRENCY", "DEEPSEEK_MAX_CONCURRENCY"))  # 批次并发度

    # ── 去重 — 历史窗口扩展 ──
    DEDUP_HISTORICAL_DAYS: int = 7  # P5: 评分前从 DB 加载 N 天的 SimHash 指纹注入去重索引，识别跨天旧闻

    # ── 事件合成（方案A：事件中心化）──
    # 每轮 pipeline 结束后，把「多信源报道同一事件」的聚合簇交给 LLM 合成一张事件卡片，
    # 写到聚合根的 event_title/event_summary，前端直接以事件为粒度展示。
    EVENT_SYNTH_ENABLED: bool = True      # 总开关
    EVENT_SYNTH_WINDOW_HOURS: int = 12    # 扫描最近 N 小时内有新关联报道的聚合簇
    EVENT_SYNTH_MAX_EVENTS: int = 10      # 每轮最多合成事件数（成本控制，按信源数优先）
    EVENT_SYNTH_MIN_SOURCES: int = 2      # 至少 N 个信源（根+子）才值得合成
    # 每日维护：developing 且无实质更新超过该小时数 → 自动转 stable（resolved 不依赖时间自动判定）
    EVENT_STABLE_AFTER_HOURS: int = 48

    # ── 事件记忆（方案B：跨周期相似事件召回）──
    # 合成事件包时，用向量召回「历史上的同类事件」注入 prompt，让 LLM 能判断
    # 该类事件过去如何演进（是否常被证伪 / 通常多久落地），提升 why_important 与 watch_next 质量。
    # 向量复用去重器的 Embedding API（provider 由 EMBEDDING_PROVIDER 决定），以 REAL[] 存在
    # news.event_embedding；召回在 Python 内存做余弦，不引入 pgvector（4G 服务器内存友好）。
    EVENT_MEMORY_ENABLED: bool = True
    EVENT_MEMORY_LOOKBACK_DAYS: int = 90       # 只召回近 N 天的历史事件
    EVENT_MEMORY_TOP_K: int = 3                # 每次注入的历史事件条数（控制 token）
    # 相似度区间对齐 deduplicator 的同模型标定：>0.80 为同一条新闻，>0.67 为同一事件
    # 的不同报道（已由去重器聚合）。因此「历史同类事件」取 [0.50, 0.67)——
    # 语义相关但不是同一事件。上界若放宽，会把同一事件当成「历史规律」误导 LLM。
    EVENT_MEMORY_MIN_SIM: float = 0.50
    EVENT_MEMORY_MAX_SIM: float = 0.67
    EVENT_MEMORY_MAX_CANDIDATES: int = 5000    # 单次加载候选向量上限（内存保护）
    EVENT_MEMORY_SUMMARY_CHARS: int = 60       # 注入的历史事件摘要截断长度

    # ── 新闻预筛（LLM 评分前过滤/压缩，节省评分 token）──
    # 优先拦截低价值内容、按信源历史质量门控、同事件跟稿继承根评分。
    # 上线前务必保持 PREFILTER_SHADOW_MODE=True 跑 3-7 天影子测试，确认误杀率达标再关闭。
    PREFILTER_ENABLED: bool = True
    # 影子模式：仅记录预筛决策、不丢弃、不压缩，全部仍送 LLM 以对比真实评分
    PREFILTER_SHADOW_MODE: bool = True
    # 正常模式下，随机保留该比例的被拦截内容继续送 LLM，作为长期审计样本（防规则漂移）
    PREFILTER_AUDIT_SAMPLE_RATE: float = 0.05
    # 同事件标题相似度阈值（difflib，零 token）；低于则视为不同事件、需单独评分
    PREFILTER_EVENT_SIM_THRESHOLD: float = 0.85
    # 信源历史质量统计窗口（天）
    PREFILTER_SOURCE_QUALITY_DAYS: int = 30
    # C 级信源至少需要的硬信息信号数
    PREFILTER_TIER_C_MIN_HARD_SIGNAL: int = 2
    # D 级信源判定：展示通过率低于该值且样本数 >= 下限
    PREFILTER_TIER_D_DISPLAY_RATE: float = 0.03
    PREFILTER_TIER_D_MIN_SAMPLES: int = 200
    # prefilter_score <= 该值则丢弃（兜底，官方/重大事件已提前放行不受影响）
    PREFILTER_DROP_PREFILTER_SCORE: int = 1
    # 低价值模式正则（命中即丢弃）。可在 .env 用 JSON 数组覆盖。
    PREFILTER_LOW_VALUE_PATTERNS: list[str] = Field(default_factory=list)
    # 权威/一手信源名称（命中强制 A 级、不受历史分限流）
    PREFILTER_OFFICIAL_SOURCES: list[str] = Field(default_factory=list)
    # 权威/一手信源域名片段
    PREFILTER_OFFICIAL_DOMAINS: list[str] = Field(default_factory=list)

    # ── 调度器 — Pipeline 定时执行 ──
    PIPELINE_START_HOUR: int = 0   # 起始小时（全天运行覆盖英文信源不同时区）
    PIPELINE_END_HOUR: int = 23    # 结束小时（0-23）
    PIPELINE_INTERVAL_MINUTES: int = 15  # 执行间隔（分钟），每小时 0/15/30/45 触发

    # ── 告警 — Pipeline 失败时的 Webhook 通知 ──
    # 支持：飞书/钉钉/企业微信/Slack/通用（根据 URL 自动识别平台）
    # 留空则禁用告警
    ALERT_WEBHOOK_URL: str = ""

    # ── 站点基础地址（用于推送消息中拼接原文链接）──
    SITE_BASE_URL: str = "https://www.alphareader.site"

    # ── Reports 同步鉴权 ──
    REPORT_SYNC_TOKEN: str = Field("", repr=False)  # Node.js 上传脚本使用的 Bearer Token，生产环境必须设置

    # ── API Key 全局鉴权 ──
    NEWS_API_KEY: str = Field("", repr=False)  # 为空则不启用鉴权（仅限开发环境）

    # ── Admin Key 高成本触发端点独立鉴权 ──
    # 用于 digest/briefing 手动生成、pipeline 手动触发、行情回填等烧钱/重资源端点。
    # 与 NEWS_API_KEY 叠加（两个 Header 都要：X-API-Key + X-Admin-Key）。生产环境必须设置。
    ADMIN_API_KEY: str = Field("", repr=False)  # 为空则回退到全局 API Key 语义（仅限开发环境）

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

    @model_validator(mode="after")
    def _require_production_secrets(self):
        """生产环境 fail-fast：关键密钥缺失直接拒绝启动，避免"静默放行"裸奔。

        此前各鉴权点（NEWS_API_KEY / DASHBOARD_PASSWORD / SANDBOX_PASSWORD 等）
        为空即跳过校验且无告警，生产忘配即全站无鉴权。此处在启动期拦截。
        """
        if self.APP_ENV == "production":
            required = (
                "NEWS_API_KEY",
                "ADMIN_API_KEY",
                "POSTGRES_PASSWORD",
                "REDIS_PASSWORD",
                "DASHBOARD_PASSWORD",
            )
            missing = [name for name in required if not getattr(self, name)]
            if missing:
                raise ValueError(
                    f"生产环境缺少必需密钥配置: {', '.join(missing)}。"
                    "请在 .env 中设置后重启（空密钥在生产环境等于无鉴权）。"
                )
            # SANDBOX_PASSWORD 不做强制（面向用户的私密口令，历史上未设置=任意密码可进）。
            # 未设置时 token 校验直通、保持现状；设置后私密 GET 端点才真正受保护。
            if not self.SANDBOX_PASSWORD:
                import logging

                logging.getLogger("alphareader.config").warning(
                    "SANDBOX_PASSWORD 未设置：模拟仓/SEPA 私密端点当前为开放状态，"
                    "建议配置以启用 token 保护。"
                )
        return self


# 全局单例，其他模块通过 `from app.config import settings` 引用
settings = Settings()
