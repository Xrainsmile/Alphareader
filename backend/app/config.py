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
    # 归线阈值，S >= 该值才判定「属于这条线」
    THREAD_T_JOIN: float = 0.45
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
