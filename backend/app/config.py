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
    # 生产默认只允许自有域名；本地开发源请在 .env 中显式追加，不要改默认值。
    CORS_ORIGINS: str = "https://alphareader.site"  # 逗号分隔的允许源

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

    # ── DeepSeek 官方 API（摘要/研报专用，流式调用）──
    # 2026-09 从腾讯云 tencentmaas 切回 DeepSeek 官方直连（OpenAI 兼容，请求方式不变）。
    # 注意：pydantic-settings 下 validation_alias 会覆盖字段名本身，故必须显式把
    # DEEPSEEK_API_KEY 放在首位，否则 .env 里写 DEEPSEEK_API_KEY 不会被读取（旧代码的坑）。
    TENCENTMAAS_API_KEY: str = Field("", repr=False)                          # 【已废弃】仅作旧值兼容，不再作为主 key
    DEEPSEEK_API_KEY: str = Field("", repr=False, validation_alias=AliasChoices("DEEPSEEK_API_KEY", "TENCENTMAAS_API_KEY"))  # DeepSeek 官方 key（优先）；无则回退旧 tencentmaas key
    DEEPSEEK_API_URL: str = "https://api.deepseek.com/chat/completions"      # DeepSeek 官方地址（OpenAI 兼容）
    DEEPSEEK_MODEL: str = "deepseek-flash"                                    # 摘要/研报模型（digest / briefing 使用）= V4.1-Flash

    # ── LLM 评分/翻译/分析/公司名映射（deepseek-flash）──
    # 评分等高频结构化任务与摘要统一用 deepseek-flash（V4.1-Flash，官方当前主推，成本最低）。
    # 官方已下线 V4 Flash / V4 Flash Vision Exp：旧名 deepseek-v4-flash 会临时路由到 V4.1-Flash。
    # LLM_API_KEY 读取优先级：LLM_API_KEY > DEEPSEEK_API_KEY > TENCENTMAAS_API_KEY（旧值兜底）。
    LLM_API_KEY: str = Field("", repr=False, validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY", "TENCENTMAAS_API_KEY"))  # 评分/分析用 key（默认复用 DeepSeek 官方 key）
    LLM_API_URL: str = "https://api.deepseek.com/chat/completions"            # 评分/分析 API 地址（OpenAI 兼容）
    LLM_MODEL: str = "deepseek-flash"                                         # 评分/分析模型（结构化 JSON 输出）

    # ── LLM 评分参数（AliasChoices 兼容旧 DEEPSEEK_* 环境变量名）──
    LLM_BATCH_SIZE: int = Field(30, validation_alias=AliasChoices("LLM_BATCH_SIZE", "DEEPSEEK_BATCH_SIZE"))                        # 每批评分条数（P1 实验：30 在零质量退化下较 20 省 ~9% prompt/item 且少 1/3 API 往返；40 仅再降 5% 却抬升 p95 延迟至 ~21s，故不取）
    LLM_SCORE_THRESHOLD: int = Field(5, validation_alias=AliasChoices("LLM_SCORE_THRESHOLD", "DEEPSEEK_SCORE_THRESHOLD"))          # 入库分数阈值（≥5 才存储）
    LLM_MAX_RETRIES: int = Field(2, validation_alias=AliasChoices("LLM_MAX_RETRIES", "DEEPSEEK_MAX_RETRIES"))                       # API 失败最大重试次数
    LLM_CONTENT_PREVIEW_CHARS: int = Field(400, validation_alias=AliasChoices("LLM_CONTENT_PREVIEW_CHARS", "DEEPSEEK_CONTENT_PREVIEW_CHARS"))  # 已废弃：预览长度改由下方 LLM_PREVIEW_*_CHARS 三档动态分配，见 llm_news_filter.get_llm_preview_chars
    LLM_PREVIEW_SHORT_CHARS: int = Field(120, validation_alias=AliasChoices("LLM_PREVIEW_SHORT_CHARS", "DEEPSEEK_PREVIEW_SHORT_CHARS"))  # 动态预览：完整快讯标题档（标题已自包含完整事件，正文只需少量上下文）
    LLM_PREVIEW_NORMAL_CHARS: int = Field(250, validation_alias=AliasChoices("LLM_PREVIEW_NORMAL_CHARS", "DEEPSEEK_PREVIEW_NORMAL_CHARS"))  # 动态预览：普通短新闻/常规财经科技新闻档
    LLM_PREVIEW_COMPLEX_CHARS: int = Field(400, validation_alias=AliasChoices("LLM_PREVIEW_COMPLEX_CHARS", "DEEPSEEK_PREVIEW_COMPLEX_CHARS"))  # 动态预览：财报/业绩/guidance/监管/政策/并购/官方公告档（含关键数字，强制全长）
    LLM_MIN_CHINESE_RATIO_TITLE: float = Field(0.5, validation_alias=AliasChoices("LLM_MIN_CHINESE_RATIO_TITLE", "DEEPSEEK_MIN_CHINESE_RATIO_TITLE"))  # 中文标题最低中文占比
    LLM_MIN_CHINESE_RATIO_SUMMARY: float = Field(0.6, validation_alias=AliasChoices("LLM_MIN_CHINESE_RATIO_SUMMARY", "DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY"))  # 中文摘要最低中文占比
    LLM_CONTENT_RISK_BISECT_ENABLED: bool = Field(True, validation_alias=AliasChoices("LLM_CONTENT_RISK_BISECT_ENABLED", "DEEPSEEK_CONTENT_RISK_BISECT_ENABLED"))  # 内容审查触发时二分隔离
    LLM_CONTENT_RISK_MAX_DEPTH: int = Field(6, validation_alias=AliasChoices("LLM_CONTENT_RISK_MAX_DEPTH", "DEEPSEEK_CONTENT_RISK_MAX_DEPTH"))  # 二分最大递归深度
    LLM_TWO_STAGE_EN_ENABLED: bool = Field(True, validation_alias=AliasChoices("LLM_TWO_STAGE_EN_ENABLED", "DEEPSEEK_TWO_STAGE_EN_ENABLED"))  # 英文两阶段评分
    # ── 英文单阶段实验（P1）──
    # False=保持现状（两阶段：先评分后翻译，≥6 条目二次调用翻译）；
    # True=实验性单次调用同时完成评分 + 对 score>=6 条目条件翻译（A/B 达标后再切换，切勿默认开启）。
    LLM_EN_SINGLE_STAGE_EXPERIMENT: bool = Field(False, validation_alias=AliasChoices("LLM_EN_SINGLE_STAGE_EXPERIMENT", "DEEPSEEK_EN_SINGLE_STAGE_EXPERIMENT"))  # 英文单阶段实验开关
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
    # fast path：满足以下任一条件即可绕过 min_sources 门槛单独合成（一手重大公告常仅单源）：
    #   - 根来源为权威/一手信源（美联储/SEC/交易所/央行/公司 IR 等）
    #   - ai_score >= 该阈值（默认 8）
    #   - is_highlight = true
    EVENT_SYNTH_FAST_AI_THRESHOLD: int = 8
    # 每日维护：developing 且无实质更新超过该小时数 → 自动转 stable（resolved 不依赖时间自动判定）
    EVENT_STABLE_AFTER_HOURS: int = 48
    # 事件合成单次调用的 max_tokens。
    # 原为硬编码 768；P1 需在输出 JSON 增加 mechanism_hints / contested_assets 两个数组字段，
    # 并在输入侧增加「所在世界线」谱系区块，768 会导致输出被截断 → JSON 不完整 → 触发重试 →
    # 该簇本轮不合成（静默降级，难排查）。提到 1024 留出余量。
    # 后续若继续加字段，优先调这里而不是改代码。
    EVENT_SYNTH_MAX_TOKENS: int = 1024

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
    # P1 需在同一份 prompt 内再塞入「所在世界线」谱系区块（当前章节 + rollup 摘要），
    # 历史同类事件的摘要从 60 降到 50，给谱系区块腾出输入余量。实测该长度对
    # 「判断这类事件通常如何演进」的归纳无实质损失。
    EVENT_MEMORY_SUMMARY_CHARS: int = 50       # 注入的历史事件摘要截断长度

    # ── 新闻清理（每日 03:30）──
    # 普通报道保留窗口：原始 news 记录的硬删除上限（7~14 天，取 14 留余量）。
    # 注意：事件聚合根（related_to_id IS NULL 且 event_title IS NOT NULL）不在此窗口删除，
    # 而是按事件生命周期保留（见 NEWS_CLEANUP_EVENT_LOOKBACK_DAYS），否则会破坏
    # 90 天 Event Memory、拆散长周期事件、并级联删除 Reports 历史链接。
    NEWS_CLEANUP_ARTICLE_DAYS: int = 14
    # 事件根保留窗口：与 EVENT_MEMORY_LOOKBACK_DAYS 对齐，使「配置写 90 天」真正生效。
    # developing 事件按 event_last_updated_at 计龄；stable/resolved 按
    # max(published_at, event_first_seen_at, event_last_updated_at) 计龄。
    NEWS_CLEANUP_EVENT_LOOKBACK_DAYS: int = 90

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

    # ── 评分年龄闸（Step 2.5）──
    # 漏洞：旧逻辑对所有 published_at >24h 的新闻一刀切不送 LLM，导致 LLM 评分 Prompt 中
    # "1—7天轻度降权""旧事件首次披露关键数据按新增内容评分""官方/监管公告正常评分"等规则
    # 全部失效。改为分源规则：快讯媒体（实时快讯流，旧闻重复度高）>24h 才拦截；其余信源
    # 走 7 天或更长窗口，由 LLM 时效规则轻度降权。
    # 下列为"快讯媒体"信源名（命中即 >24h 拦截）。可用 .env 的 JSON 数组覆盖。
    AGE_GATE_FAST_NEWS_SOURCES: list[str] = Field(
        default_factory=lambda: ["富途新闻", "华尔街见闻", "Investing.com"]
    )

    # ── 事件记忆召回约束（与"结果记忆"配套）──
    # 仅召回 status 属于下列集合的历史事件（跳过 new/developing 进行中事件），
    # 避免把未结束事件当"历史规律"。默认只取已结束(resolved)与已平息(stable)的。
    EVENT_MEMORY_RECALL_STATUSES: list[str] = Field(
        default_factory=lambda: ["stable", "resolved"]
    )
    # 写"通常/往往"类规律结论前，要求至少 N 个方向一致（同 outcome_type）的历史事件；
    # 不足时 LLM 只能逐条引用、不得归纳"通常"。杜绝单样本臆断。
    EVENT_MEMORY_MIN_PATTERN_COUNT: int = 2

    # ── 世界线 P0：实体抽取（kill switch）──
    # 实体抽取搭评分调用的便车，在同一份 JSON 输出里多要一个 entities 字段。
    # 总开关：关闭后评分 prompt 不再要求 entities，解析器也不再读取，
    # 立即回到 P0 之前的纯评分行为。出现评分质量回退时先关这个，再排查。
    ENTITY_EXTRACTION_ENABLED: bool = True
    # 仅对 score >= 该档位的条目要求输出 entities。
    # 依据 LLM_SCORE_THRESHOLD：低于阈值的条目根本不入库，给它们抽实体纯属浪费。
    ENTITY_EXTRACTION_MIN_SCORE: int = 5
    # 单条事件最多保留的实体数（解析器硬截断，防 LLM 返回超长数组）
    ENTITY_EXTRACTION_MAX_ITEMS: int = 5

    # ── 世界线 P0：实体层信源名过滤 ──
    # 漏洞：LLM 会把发文媒体（Yahoo Finance / Seeking Alpha / MarketWatch 等）误当作
    # 事件参与实体抽出来，落库后污染归线的 E 值（实体 Jaccard）——两条不相关的线只要
    # 都引了同一家媒体就会被判相似，而 E 在 S=0.55E+0.30M+0.15R 里权重最高。
    # 过滤规则：归一化后命中下列任一信源名即剔除（写入 is_generic 而非丢弃，
    # 保留 mention_count 以便回溯误杀）。可用 .env 的 JSON 数组覆盖。
    ENTITY_SOURCE_BLOCKLIST: list[str] = Field(
        default_factory=lambda: [
            # 财经媒体 / 通讯社（纯信源，非事件参与者）
            "Yahoo Finance", "YahooFinance", "Yahoo", "Seeking Alpha", "SeekingAlpha",
            "MarketWatch", "Benzinga", "Barron's", "Barrons", "Investing.com",
            "CNBC", "Reuters", "Bloomberg", "Financial Times", "FT", "WSJ",
            "Wall Street Journal", "TheStreet", "Zacks", "Motley Fool",
            "TechCrunch", "The Verge", "The Verge AI", "Wired", "Ars Technica",
            "Engadget", "VentureBeat", "MarkTechPost", "Simon Willison",
            "富途新闻", "财联社", "新浪财经", "东方财富", "同花顺", "雪球",
            "证券时报", "上海证券报", "中国证券报", "第一财经", "21世纪经济报道",
            # 交易所 / 监管（作为"来源"时是发布渠道，不是事件主体）
            "SEC EDGAR", "SEC", "EDGAR", "NASDAQ", "NYSE", "HKEX",
            # SEC 披露表单编号（8-K 当前公告 / 10-K 年报 / 10-Q 季报 / S-1 招股书 / 20-F 外国发行人年报）
            # 与交易所同类：是"披露渠道/文件类型"，不是事件参与主体。
            # 回填后 8-K 系列累计 39 次提及冲上实体库第 2 位，污染归线的实体 Jaccard。
            # 注意：黑名单为精确归一化匹配（非子串），故不会误伤 TruistSecurities / Securetech 等真实体。
            "8-K", "8-K/A", "8-K文件", "8-K表格",
            "10-K", "10-K/A", "10-Q", "10-Q/A", "S-1", "S-1/A",
            "20-F", "6-K", "13F", "13F-HR", "SC 13D", "SC 13G",
            "Form 4", "DEF 14A", "424B5", "FWP",
        ]
    )
    # 豁免名单：既是信源名、本身也是真实事件主体的机构。
    # 例：OpenAI Blog 是信源，但 OpenAI 是事件主体；Anthropic / NVIDIA 同理。
    # 命中豁免时保留为实体（前提是 LLM 确实从正文抽出了它）。
    ENTITY_SOURCE_ALLOWLIST: list[str] = Field(
        default_factory=lambda: [
            "OpenAI", "Anthropic", "NVIDIA", "Nvidia", "Google", "Microsoft",
            "Apple", "Amazon", "Meta", "Tesla", "DeepMind", "xAI",
        ]
    )
    # 从数据库动态加载近 N 天出现过的 news.source 追加进黑名单（0 = 关闭）。
    # 覆盖未被静态表收录的新增信源；开库查询成本极低（DISTINCT 单列）。
    ENTITY_SOURCE_BLOCKLIST_FROM_DB_DAYS: int = 30

    # ── 世界线 P1-c：归线打分（S = 0.55E + 0.30M + 0.15R）──
    # 总开关：关闭后不做任何归线计算，事件正常合成但不挂线。
    THREAD_ROUTING_ENABLED: bool = True
    # 影子模式（影线期必须开）：只计算 S 并写入 thread_operations 留痕，
    # 不写 thread_events、不改 threads。7 天影子期内严禁关闭。
    THREAD_ROUTING_SHADOW: bool = True
    # S 公式权重，三者应和为 1.0
    THREAD_SCORE_W_ENTITY: float = 0.55
    THREAD_SCORE_W_MECHANISM: float = 0.30
    THREAD_SCORE_W_RECENCY: float = 0.15
    # 归线阈值，S >= 该值才判定「属于这条线」。
    # 0.45 -> 0.40：批量回填实测 S 上限 0.4375（E=0.25*0.55 + M=1*0.30 + R=0），
    # 恒定跨不过 0.45，一条都无法归线。阈值源自影子期标定，但影子期实际
    # 只跑了 1 小时（留痕 3 条）未达设计要求的 7~14 天，缺乏观测支撑。
    # ★ P0-2（2026-10-14 数据定参）：0.40 -> 0.15。
    #   依据 eval_thread_routing.py 以 441 条人工基线为 ground truth 的
    #   离线回放：真实配对 S 中位数仅 0.302、p75 仅 0.391，
    #   旧的 0.40 只放得过 105/441（23.8%）真阳性 —— 阈值本身就是最大漏归源。
    #   扫描结果：T_JOIN=0.10 时 F1=0.622(P=0.840 R=0.494)；
    #             0.15 时 P 升到 0.907、R 降到 0.365。
    #   取 0.15：世界线宁可漏归也不误归——误归会污染叙事，漏归只是一条
    #   孤立事件，后续可被 LLM 校验或人工补线救回，代价不对称。
    #   想再提召回就调到 0.10（改配置重启即可，无需发版）。
    THREAD_T_JOIN: float = 0.15
    # 核心实体（event_entities.weight >= 该值）在 Jaccard 中的加权倍率
    THREAD_CORE_ENTITY_WEIGHT: int = 3
    # 活跃度奖励 R 的半衰期（小时）：线最近一次更新距今越近，R 越大。
    # R = 0.5 ** (hours_since / HALF_LIFE)，天然落在 (0,1]，无需再设 CAP。
    THREAD_RECENCY_HALF_LIFE_HOURS: float = 72.0
    # 单条事件最多写入的线数（防止一个事件挂满所有线）
    THREAD_MAX_LINES_PER_EVENT: int = 3
    # 候选线扫描上限（性能保护，按 last_event_at 倒序取最近 N 条 active 线）
    THREAD_CANDIDATE_LIMIT: int = 200
    # ── 自动建线门槛（world-thread-design.md §5.3：核心实体 >= 2 才建 embryo 线）──
    THREAD_MIN_CORE_ENTITIES: int = 2        # 开线所需最少非泛化实体数
    THREAD_MIN_MENTION_COUNT: int = 1        # 实体 mention_count 达标线（1=不额外限制）

    # 自动建线时写入 core_entities 的实体数上限。
    # 原硬编码 5，导致线的实体画像过窄：加权 Jaccard (Σmin/Σmax) 在
    # 线侧实体少时会因 union 偏小而放大分母，实测 E 最高仅 0.25、
    # 66.7% 候选配对 E=0，S 卡在 0.4375 过不了 T_JOIN=0.45。
    # 放宽到 10 让线的实体画像更完整，提升真实同主题命中的重叠度。
    THREAD_MAX_CORE_ENTITIES: int = 10

    # ── 世界线 P1-c-2：线画像滚动重算 ──
    # 线标题 / core_entities / last_event_at 随章节滚动重算（P1-c 只在建线时写一次，
    # 导致「线名=首章标题」且长线实体画像冻结，是 8-K 扎堆成一条线的直接成因）。
    THREAD_PROFILE_REFRESH_ENABLED: bool = True
    # 至少几章才做 rollup 命名：1 章时首章标题就是最佳命名，没有 rollup 输入
    THREAD_MIN_CHAPTERS_FOR_ROLLUP: int = 2

    # ── 世界线 P1-c-3：归线止血（防「沾一个实体就归线」）──
    # 事件 mechanism_hints 为空时的 M 取值。
    # 原为 1.0（语义「不参与门控」），实测机制抽取覆盖率低、绝大多数事件为空，
    # 等于每条线白送 0.30 分；叠加新线 R≈1.0 的 0.15，S 恒 >= 0.45 而无视 E，
    # 任何沾到一个实体的事件都能过 T_JOIN=0.40 —— 这是 8-K 扎堆的成因之一。
    # 改 0.5 中性：空机制不加分也不减分，归线重新由 E 主导。
    THREAD_M_MISSING_SCORE: float = 0.5
    # E 下限：实体重合比例低于此值直接否决（不论 S 高）。
    # ★ P0-2（2026-10-14 数据定参，已修正）：0.30 -> 0.08。
    #   第一版拍脑袋提到 0.30 / MIN_SHARED=3，离线回放证明是**误杀**：
    #   441 条真阳性的 E 中位数仅 0.036（归一化后 0.111）、shared 中位数仅 1，
    #   门控拦下 399/441 → Recall 掉到 0.000。真实同主题事件往往只共享
    #   1~2 个实体，硬性要求 3 个不符合数据分布。
    #   扫描结论：门控在 0.05~0.20 区间、shared>=1 时 F1 基本不变（瓶颈在
    #   T_JOIN 不在门控）。取 0.08 留一点噪声过滤，shared 回到 1。
    THREAD_T_JOIN_ENTITY: float = 0.08
    # 最少共同实体数：只共享 1 个实体不足以证明同一条线。
    # ★ 注意不能用「共同**核心**实体（weight>=3）」判定：
    #   link_event_entities 唯一调用点（event_synthesizer）用默认 default_weight=1，
    #   全库 event_entities.weight 恒为 1，weight>=3 永远不成立 → 会误杀全部归线。
    # ★ P0-2（2026-10-14 数据定参，已修正）：3 -> 1。
    #   真实配对 shared 中位数仅 1、p75 为 2、最大 4。要求 3 会误杀
    #   绝大多数真阳性（扫描：MIN_SHARED=2 时 Recall 从 0.494 掉到 0.280）。
    THREAD_MIN_SHARED_ENTITIES: int = 1
    # 门控总开关：false 则整套门控退化为仅 E<=0 否决（等同收紧前行为）。
    # ★ 必须保留：服务器 THREAD_ROUTING_SHADOW=false（真实写入，非影子模式），
    #   门控一旦误判会直接污染生产数据；且机制命中的线 M=1.0 使 S 恒 >= 0.45，
    #   T_JOIN 对它们完全失效，门控是唯一防线。没有开关就只能改代码重新发版回退。
    THREAD_ENTITY_GATE_ENABLED: bool = True

    # ★ P0-1（2026-10-14）：机制未知时是否做权重重分配（核心止血项）。
    # true  = S = (wE*E + wR*R) / (wE + wR)，M 维度整体退出（推荐，默认）
    # false = 旧行为：M 取 M_MISSING_SCORE 后照常按 wM 计入 → 白送 0.15~0.30 分
    # 生产库 mechanism_hints 覆盖率仅 1.9%（16/838），此开关必须保持 true。
    THREAD_M_REDISTRIBUTE_WEIGHT: bool = True

    # ── 世界线 P1（2026-10-14 结构改进）──
    # P1-6：事件类型硬门控。类型互斥的事件禁止归入同一条线。
    # 现网把"公司业绩"和"地缘冲突"混线，根因是只比实体不比类型。
    THREAD_KIND_GATE_ENABLED: bool = True
    # P1-7：时间断线。章节间隔超过该天数后 S 线性衰减，2 倍时归零。
    # 世界线是连续追踪的叙事，长期空窗后应视为新线而非老线续章。
    THREAD_TIME_GAP_ENABLED: bool = True
    THREAD_TIME_GAP_DAYS: float = 30.0
    # P1-8：碎片线合并扫描。core_entities Jaccard 超过该阈值即建议合并。
    THREAD_MERGE_SIMILARITY: float = 0.60

    # ── 世界线 P2（2026-10-14 质量层）──
    # P2-9：LLM 二次语义校验。规则判 join 且 S 落在
    # [T_JOIN, T_JOIN + BAND) 的灰色地带时送 DeepSeek 复核。
    # 只查灰色地带：明显命中不查（省 token），已被规则挡掉的不查。
    # 失败一律放行（宁可放过不可错杀——误杀导致线碎片化的代价更高）。
    THREAD_LLM_VERIFY_ENABLED: bool = False   # 先关，观察规则层效果后再开
    THREAD_LLM_VERIFY_BAND: float = 0.15
    # P2-10：embryo 归档。超过该天数无新章节的 embryo 线置 dormant。
    # 现网 300/312 条是 embryo 孤岛（96%），需要定期清扫。
    THREAD_EMBRYO_ARCHIVE_DAYS: int = 30
    # P2-11：市场快照隔离。命中这些模式的事件不进世界线，
    # 归入独立的「市场脉搏」视图。现网约 150 条日频综述被当成世界线章节。
    THREAD_MARKET_SNAPSHOT_ENABLED: bool = True

    # ── 强信号：指数级 / 交易时段级，一律判快照（无例外）──────────────
    # 「A股三大指数」「港股开盘」「美股盘前」描述的是当天盘面本身，
    # 不存在可追踪的争夺标的与推进机制。
    THREAD_MARKET_SNAPSHOT_STRONG: list[str] = [
        r"三大指数", r"创业板指", r"科创50", r"恒指", r"科指", r"恒生科技",
        r"开盘", r"收盘", r"早盘", r"午盘", r"尾盘", r"盘初", r"盘中",
        r"夜盘", r"盘前", r"盘后", r"异动", r"涨跌停", r"两市", r"沪深",
    ]

    # ── 弱信号：板块 / 概念股 + 方向性走势 ──────────────────────────
    # 这类**多数**是快照，但若标题里同时出现"实体做了某件具体的事"
    # （发射成功、获批、收购、突破里程碑…），则盘面只是结果，
    # 事件本身值得进线 → 由 THREAD_MARKET_SNAPSHOT_RESCUE 捞回。
    # 例：「朱雀三号火箭陆地回收成功，商业航天概念股大涨」应保留。
    THREAD_MARKET_SNAPSHOT_WEAK: list[str] = [
        r"板块(集体|走强|走弱|领涨|领跌|拉升|下挫|高开|低开|大涨|大跌|普涨|普跌|分化|承压|反弹)",
        r"概念股(集体|全线|普涨|普跌|走强|走弱|大涨|大跌|领涨|领跌|高开|拉升|跟涨|下挫)",
        r"(股|指数|板块)?(集体|全线|普遍)(走强|走弱|走高|走低|拉升|下挫|大涨|大跌|翻红|收涨|收跌|上涨|下跌)",
        r"(黄金股|有色股|银行股|科技股|芯片股|医药股|地产股|航运股|锂业股|稀土股|军工股|能源股)(集体|全线|普涨|普跌|走强|走弱|领涨|领跌)",
        r"(加密货币|比特币|以太坊)(集体|全线)?(拉升|大涨|大跌|走强|走弱)",
    ]

    # ── 豁免信号：出现即不判快照（有具体事件，盘面只是结果）──────────
    # 这些词代表"某个主体做成了一件事"，是可追踪的叙事节点。
    THREAD_MARKET_SNAPSHOT_RESCUE: list[str] = [
        r"成功", r"首破", r"突破", r"创新高", r"创下", r"获批", r"签署",
        r"收购", r"并购", r"中标", r"发布", r"推出", r"交付", r"发射",
        r"回收", r"试飞", r"获批", r"制裁", r"关税", r"加息", r"降息",
        r"罢工", r"袭击", r"封锁", r"停产", r"减产", r"扩产", r"投产",
        r"财报", r"业绩", r"指引", r"回购", r"增持", r"减持", r" IPO",
        r"上市", r"退市", r"重组", r"破产", r"诉讼", r"罚款", r"调查",
    ]

    # 兼容旧配置名：保留作为强信号的别名
    THREAD_MARKET_SNAPSHOT_PATTERNS: list[str] = [
        r"开盘", r"收盘", r"三大指数", r"创业板指", r"科创50", r"恒指",
        r"恒生科技", r"板块集体", r"板块走强", r"板块走弱", r"集体走高",
        r"集体下挫", r"盘初", r"盘中", r"夜盘", r"盘前", r"盘后", r"异动",
    ]
    # 胚胎线至少几章才转 active（P2-10 配套：1-2 章不足以证明是条线）
    THREAD_MIN_CHAPTERS_ACTIVE: int = 3

    # ★ P0-5（2026-10-14）：加权 Jaccard 是否做归一化。
    # true  = 两侧各除以自身 Σw 后再算（推荐，默认）
    # false = 直接用原始累加权重算 → 成熟线 Σw 大，E 被压到 0.07 以下，
    #         门控无论怎么设都会误杀真阳性
    THREAD_E_NORMALIZE: bool = True

    # ★ P0-3（2026-10-14）：披露形式 / 通用名词实体黑名单。
    # 命中这些名字的实体不得作为归线锚点、也不得计入 Jaccard 分子。
    # 依据：现网 12 条 8-K 线（40+ 章）把几十家无关公司串成一条线，只因
    # 共享「8-K」这个**披露形式**；「原油/市场/AI/通胀」等通用名词同理——
    # 33 章巨型线的 core_entities 是 {伊朗, 原油, 石油}，后两个无区分度。
    # 世界线要的是「争夺标的」，不是「表述形式」。
    THREAD_ENTITY_DENYLIST: list[str] = [
        # 披露形式 / 监管文件
        "8-K", "8-K/A", "10-K", "10-Q", "6-K", "20-F", "S-1", "424B5",
        "财报", "季报", "年报", "半年报", "中报", "业绩公告", "重大协议",
        "重大事项", "经营业绩", "其他事项", "退市通知", "监管披露",
        "SEC", "美国证券交易委员会", "披露文件", "定期报告",
        # 通用名词（跨所有同类新闻，无区分度）
        "原油", "石油", "天然气", "油价", "市场", "股市", "板块", "指数",
        "通胀", "经济", "金融", "投资", "资本", "增长", "预期", "数据",
        "AI", "人工智能", "芯片", "半导体", "科技", "美元", "人民币",
        "港元", "华尔街", "美股", "港股", "A股",
    ]

    # ── 事件级排序信号（纯规则，无需额外模型调用）──
    # 合成时算出 impact/novelty/urgency/confidence/relevance 五个 0-10 信号，
    # 派生 0-3 加分并入「重要」排序的 HN 重力公式，使 Reports 标为"必须知道"的
    # 事件在 News 里也能靠前。关闭则退回原 根 ai_score + 信源加分 + 时间衰减。
    EVENT_SIGNAL_BOOST_ENABLED: bool = True

    # ── 事件级重大事件即时提醒（条件触发，不生成午报）──
    # 早报/晚报保留即可，但高波动日中午的重大事件等到 18:30 偏晚；
    # 满足全部条件时合成阶段即时推一条 1-2 条的短简讯（纯程序规则，不额外调 LLM）：
    #   event_version 增加 且 ai_score >= MIN_AI_SCORE
    #   且（官方来源 或 独立信源数 >= MIN_SOURCES）且 latest_change 非空
    EVENT_ALERT_ENABLED: bool = True
    EVENT_ALERT_MIN_AI_SCORE: int = 8
    EVENT_ALERT_MIN_SOURCES: int = 2
    EVENT_ALERT_MAX_ITEMS: int = 2

    # ── 调度器 — Pipeline 定时执行 ──
    PIPELINE_START_HOUR: int = 0   # 起始小时（全天运行覆盖英文信源不同时区）
    PIPELINE_END_HOUR: int = 23    # 结束小时（0-23）
    # 执行间隔（分钟）。必须为 60 的约数（15→0,15,30,45 / 20→0,20,40 / 30→0,30），
    # 否则 scheduler 用 range(0,60,interval) 生成分钟表达式会出现不均匀间隔
    # （曾用 25 导致 0,25,50，整点处出现 10 分钟空档，且每天运行次数统计失真）。
    PIPELINE_INTERVAL_MINUTES: int = 20  # 每 20 分钟触发一次，控制 LLM 调用成本

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
