"""新闻预筛（LLM 评分前的零 / 低 token 过滤与压缩）。

设计目标：在把新闻送进 DeepSeek 评分之前，用确定性的规则与廉价的文本特征，
尽可能多地拦截低价值内容、压缩"媒体跟稿"的重复评分，从而显著减少评分输入 token。

实现顺序（对应 2026-08-03 设计文档「推荐的 AlphaReader 方案」）：

    现有去重
      → 权威来源强制放行
      → 内容质量硬规则（完整性 / 低价值模式 / 硬信息信号）
      → 信源历史质量门控（按近 N 天通过率分级 A/B/C/D）
      → 同事件新事实检测（related_to_url 子报道无新事实则继承根评分）
      → LLM 评分

关键设计点：

  * 全程零 LLM / 零 Embedding 调用（标题相似度用 difflib，符合零 token 目标）。
  * 高价值兜底：官方 / 监管 / 重大事件强制送评，不受历史分限流，控制误杀。
  * 影子测试：PREFILTER_SHADOW_MODE 下只记录决策、不丢弃、不压缩，用于对比真实评分。
  * 审计抽样：正常模式下随机保留少量被拦截内容送 LLM，防止规则漂移。

所有阈值集中在 config.py（PREFILTER_*），便于灰度与回滚。
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from sqlalchemy import case, func, select

from app.config import settings
from app.database import async_session
from app.models.news import News

logger = logging.getLogger("alphareader.prefilter")


# ───────────────────────────────────────────────────────────────────────────
# 规则资源（可被 config 覆盖，提供内置兜底）
# ───────────────────────────────────────────────────────────────────────────

DEFAULT_LOW_VALUE_PATTERNS = [
    r"报名开启",
    r"直播预告",
    r"播客第\d+期",
    r"本周精选",
    r"招聘|加入我们|诚聘|招募",
    r"sponsored|partner content|广告",
    r"webinar|podcast|newsletter",
    r"限时优惠|免费领取|立即下载|扫码关注|点击购买|优惠促销",
    r"课程推广|训练营|公开课",
]

# 权威 / 一手信源：政府、监管、交易所、央行、公司 IR / 公告。这些不应被历史分限流。
DEFAULT_OFFICIAL_NAMES = [
    "美联储", "央行", "人民银行", "证监会", "交易所", "国家统计局", "财政部",
    "发改委", "工信部", "商务部", "央行", "Federal Reserve", "Fed", "SEC",
    "Treasury", "ECB", "PBOC", "CSRC", "HKEX", "SSE", "SZSE",
]
DEFAULT_OFFICIAL_DOMAINS = [
    ".gov", ".gov.cn", "sec.gov", "hkex.com.hk", "hkexnews.hk", "sse.com.cn",
    "szse.cn", "cninfo.com.cn", "pbc.gov.cn", "mof.gov.cn", "stats.gov.cn",
    "ndrc.gov.cn", "miit.gov.cn", "mofcom.gov.cn", "federalreserve.gov",
    "treasury.gov", "ecb.europa.eu",
]

# 动作动词：明确的"发生了什么"
ACTION_VERBS = [
    "发布", "收购", "并购", "兼并", "裁员", "批准", "禁止", "上调", "下调", "降息",
    "加息", "涨停", "跌停", "上市", "退市", "起诉", "破产", "盈利", "亏损", "营收",
    "签约", "合作", "投资", "减持", "增持", "分红", "回购", "合并", "重组", "违约",
    "中标", "获批", "立案", "罚款", "警告", "停产", "扩产", "减产",
    "acquire", "merge", "layoff", "approve", "ban", "raise", "cut", "launch",
    "sue", "bankrupt", "earn", "guidance", "buyback", "recall", "default",
    "ipo", "listing", "settlement",
]
ACTION_RE = re.compile("|".join(re.escape(w) for w in ACTION_VERBS), re.I)

# 政策 / 公告 / 文件信号
POLICY_SIGNALS = [
    "政策", "监管", "法规", "公告", "财报", "指引", "利率决议", "关税", "制裁",
    "反垄断", "ipo", "重组", "股权激励", "配股", "定增", "法案", "条例", "通知",
    "指导意见", "规划", "白皮书", "决议",
    "policy", "regulation", "filing", "earnings", "guidance", "rate decision",
    "tariff", "sanction", "antitrust", "ruling", "mandate",
]
POLICY_RE = re.compile("|".join(re.escape(w) for w in POLICY_SIGNALS), re.I)

# 重大事件兜底信号：即使低质信源也强制送评
MAJOR_EVENT_SIGNALS = [
    "重大并购", "破产", "退市", "诉讼", "业绩预告", "业绩指引", "利率决议", "降息",
    "加息", "关税", "制裁", "产业政策", "反垄断", "违约", "重组", "重大合同",
    "major acquisition", "bankruptcy", "lawsuit", "earnings guidance",
    "rate decision", "tariff", "sanction", "antitrust",
]
MAJOR_EVENT_RE = re.compile("|".join(re.escape(w) for w in MAJOR_EVENT_SIGNALS), re.I)

# 核心相关主题（粗略相关性加分）
CORE_TOPICS = [
    "宏观", "货币", "利率", "股市", "债券", "美联储", "央行", "财报", "半导体",
    "人工智能", "ai", "能源", "油价", "关税", "地缘", "科技", "并购", "经济",
    "gdp", "通胀", "就业", "芯片", "新能源", "电动车", "上市公司", "ipo",
]
CORE_TOPIC_RE = re.compile("|".join(re.escape(w) for w in CORE_TOPICS), re.I)

# 营销 / 推广倾向
PROMO_MARKERS = [
    "报名", "优惠", "促销", "限时", "抢购", "免费领取", "立即下载", "扫码", "关注我们",
    "点击购买", "加盟", "招募", "webinar", "podcast", "newsletter", "sponsored",
    "subscribe", "discount", "buy now", "免费试用", "限时特惠",
]
PROMO_RE = re.compile("|".join(re.escape(w) for w in PROMO_MARKERS), re.I)

# 模糊观点标记（需与"无数字"组合才扣分，避免误伤）
VAGUE_MARKERS = ["业内人士认为", "分析称", "或", "可能", "有望", "预计", "猜测", "传言"]
VAGUE_RE = re.compile("|".join(re.escape(w) for w in VAGUE_MARKERS), re.I)

NUMBER_RE = re.compile(
    r"\d[\d,\.]*\s*(%|％|亿|万|万亿|元|美元|欧元|英镑|\$|bn|mn|trn|k|m|b|percent|pts|点)?",
    re.I,
)
ENTITY_RE = re.compile(
    r"[A-Z]{3,}|[\u4e00-\u9fff]{2,}(公司|集团|银行|央行|政府|部|局|委员会|研究院|交易所)",
    re.I,
)


# ───────────────────────────────────────────────────────────────────────────
# 基础文本特征
# ───────────────────────────────────────────────────────────────────────────

def _text(item) -> str:
    return f"{getattr(item, 'title', '') or ''} {getattr(item, 'content', '') or ''}"


def contains_number(text: str) -> bool:
    return bool(NUMBER_RE.search(text))


def contains_named_entity(text: str) -> bool:
    return bool(ENTITY_RE.search(text))


def contains_action_verb(text: str) -> bool:
    return bool(ACTION_RE.search(text))


def contains_policy_or_filing_signal(text: str) -> bool:
    return bool(POLICY_RE.search(text))


def is_core_topic(text: str) -> bool:
    return bool(CORE_TOPIC_RE.search(text))


def is_promotional(text: str) -> bool:
    return bool(PROMO_RE.search(text))


def is_vague_opinion(text: str) -> bool:
    # 仅当同时缺乏明确数字时才视为模糊观点，降低误伤
    if contains_number(text):
        return False
    return bool(VAGUE_RE.search(text))


def title_similarity(a: str, b: str) -> float:
    """零 token 的标题相似度（difflib），用于同事件判定。"""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def extract_numbers(text: str) -> frozenset:
    return frozenset(m.group(0).strip() for m in NUMBER_RE.finditer(text or ""))


def extract_entities(text: str) -> frozenset:
    return frozenset(m.group(0).strip() for m in ENTITY_RE.finditer(text or ""))


def extract_actions(text: str) -> frozenset:
    return frozenset(m.group(0).lower() for m in ACTION_RE.finditer(text or ""))


def extract_dates(text: str) -> frozenset:
    # 粗略时间短语：今日/某月/季度/Q1-Q4/年月日
    pat = re.compile(r"今日|昨日|本周|本月|季度|Q[1-4]|20\d{2}年|\d{1,2}月\d{1,2}日|明年|明年", re.I)
    return frozenset(m.group(0) for m in pat.finditer(text or ""))


# ───────────────────────────────────────────────────────────────────────────
# 信源质量统计与分级
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class SourceQuality:
    source: str
    sample_count: int = 0
    avg_score: float = 0.0
    score_pass_rate: float = 0.0       # 达到入库(>=5)比例
    display_pass_rate: float = 0.0     # 达到展示(>=6)比例
    highlight_rate: float = 0.0        # 达到重点推荐比例
    duplicate_rate: float = 0.0        # 被聚合为子报道比例


async def compute_source_quality(
    session, since_days: int | None = None
) -> dict[str, SourceQuality]:
    """从 news 表汇总每信源近 N 天历史质量指标。

    这是信源分级（A/B/C/D）的唯一数据来源；权威信源在此之后被强制提升为 A。
    """
    since_days = since_days or settings.PREFILTER_SOURCE_QUALITY_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    stmt = select(
        News.source,
        func.count(News.id),
        func.avg(News.ai_score),
        func.sum(case((News.ai_score >= 5, 1), else_=0)),
        func.sum(case((News.ai_score >= 6, 1), else_=0)),
        func.sum(case((News.is_highlight == True, 1), else_=0)),
        func.sum(case((News.related_to_id.isnot(None), 1), else_=0)),
    ).where(News.published_at >= cutoff).group_by(News.source)
    try:
        rows = (await session.execute(stmt)).all()
    except Exception as e:  # 表尚未迁移或字段缺失时安全降级
        logger.warning("compute_source_quality 查询失败，降级为空: %s", e)
        return {}

    result: dict[str, SourceQuality] = {}
    for src, cnt, avg, pass5, disp6, hl, dup in rows:
        cnt = int(cnt or 0)
        if cnt == 0:
            continue
        src = src or ""
        result[src] = SourceQuality(
            source=src,
            sample_count=cnt,
            avg_score=float(avg or 0),
            score_pass_rate=(int(pass5 or 0)) / cnt,
            display_pass_rate=(int(disp6 or 0)) / cnt,
            highlight_rate=(int(hl or 0)) / cnt,
            duplicate_rate=(int(dup or 0)) / cnt,
        )
    return result


def is_official_source(source: str, url: str = "") -> bool:
    """权威 / 一手信源判定：政府、监管、交易所、央行、公司公告等。

    此类信源可能平时大量常规发布，但偶尔出现极重要信息，绝对不能因历史平均分低而限流。
    """
    s = (source or "").lower()
    u = (url or "").lower()
    names = settings.PREFILTER_OFFICIAL_SOURCES or DEFAULT_OFFICIAL_NAMES
    domains = settings.PREFILTER_OFFICIAL_DOMAINS or DEFAULT_OFFICIAL_DOMAINS
    if any(n.lower() in s for n in names):
        return True
    if any(d in u for d in domains):
        return True
    return False


def classify_source(quality: SourceQuality | None, source: str = "", url: str = "") -> str:
    """信源分级 A/B/C/D（权威来源强制 A）。

    A 全量送评；B 通过基础规则后送评；C 仅发送有硬信息信号的新闻；
    D 长期噪声，仅抽样送评。
    """
    if is_official_source(source, url):
        return "A"
    if quality is None:
        return "B"
    if (
        quality.display_pass_rate < settings.PREFILTER_TIER_D_DISPLAY_RATE
        and quality.sample_count >= settings.PREFILTER_TIER_D_MIN_SAMPLES
    ):
        return "D"
    if quality.display_pass_rate < 0.10:
        return "C"
    if quality.display_pass_rate >= 0.30:
        return "A"
    return "B"


# ───────────────────────────────────────────────────────────────────────────
# 评分函数
# ───────────────────────────────────────────────────────────────────────────

def has_minimum_information(item, patterns: list[str] | None = None) -> bool:
    """内容完整性检查（零 token）。命中任一即视为低价值、可直接丢弃。"""
    patterns = patterns or (settings.PREFILTER_LOW_VALUE_PATTERNS or DEFAULT_LOW_VALUE_PATTERNS)
    text = _text(item)
    title = (getattr(item, "title", "") or "").strip()
    content = (getattr(item, "content", "") or "").strip()

    # 标题过短且正文为空
    if len(title) < 8 and len(content) < 80:
        return False
    # 标题与正文基本相同（无信息增量）
    if title and content and title in content and len(content) - len(title) < 20:
        return False
    # 命中招聘 / 活动 / 播客 / 课程推广等明显非新闻模式
    if any(re.search(p, text, re.I) for p in patterns):
        return False
    return True


def hard_signal_score(item) -> int:
    """硬信息信号评分：实体 / 数字 / 动作 / 政策各 +分。"""
    text = _text(item)
    score = 0
    if contains_number(text):
        score += 1
    if contains_named_entity(text):
        score += 1
    if contains_action_verb(text):
        score += 1
    if contains_policy_or_filing_signal(text):
        score += 2
    return score


def compute_prefilter_score(
    item, quality: SourceQuality | None, tier: str, hard: int | None = None
) -> int:
    """轻量级程序预评分（不替代 LLM 语义判断，仅用于过滤显然无效内容）。"""
    text = _text(item)
    hard = hard_signal_score(item) if hard is None else hard
    entity_score = 1 if contains_named_entity(text) else 0
    number_score = 1 if contains_number(text) else 0
    action_score = 1 if contains_action_verb(text) else 0

    tier_weight = {"A": 2, "B": 1, "C": 0, "D": -1}.get(tier, 1)
    relevance_score = 1 if is_core_topic(text) else 0
    promotional_penalty = 1 if is_promotional(text) else 0
    vague_penalty = 1 if is_vague_opinion(text) else 0

    score = (
        entity_score * 2
        + number_score * 2
        + action_score * 2
        + tier_weight
        + relevance_score
        - promotional_penalty * 3
        - vague_penalty * 2
    )
    return max(0, score)


def contains_major_event_signal(text: str) -> bool:
    """重大事件兜底：强制送评，控制误杀风险。"""
    return bool(MAJOR_EVENT_RE.search(text or ""))


def needs_individual_scoring(item, root: dict) -> tuple[bool, float]:
    """同事件新事实检测：子报道是否还需要单独送 LLM。

    返回 (需要送评, 标题相似度)。仅当标题高度相似且数字 / 实体 / 动作 / 时间均无新增时，
    判定为"同事件无新事实"，可由调用方继承事件根评分而不再单独评分。
    """
    root_title = root.get("title") or ""
    root_content = root.get("content") or ""
    sim = title_similarity(getattr(item, "title", ""), root_title)
    if sim < settings.PREFILTER_EVENT_SIM_THRESHOLD:
        return True, sim

    item_text = _text(item)
    root_text = f"{root_title} {root_content}"

    if extract_numbers(item_text) != extract_numbers(root_text):
        return True, sim
    # 子报道出现根报道没有的实体 → 有新主体
    if extract_entities(item_text) - extract_entities(root_text):
        return True, sim
    # 子报道出现根报道没有的动作或时间点 → 有新进展
    if extract_actions(item_text) - extract_actions(root_text):
        return True, sim
    if extract_dates(item_text) - extract_dates(root_text):
        return True, sim
    return False, sim


async def _load_roots(session, urls: set[str]) -> dict[str, dict]:
    """批量加载事件根（供同事件新事实比较）。"""
    if not urls:
        return {}
    stmt = select(
        News.id, News.url, News.title, News.content, News.ai_score, News.tags
    ).where(News.url.in_(urls))
    try:
        rows = (await session.execute(stmt)).all()
    except Exception as e:
        logger.warning("_load_roots 查询失败，降级为空: %s", e)
        return {}
    return {
        row.url: {
            "id": row.id,
            "title": row.title,
            "content": row.content,
            "ai_score": row.ai_score,
            "tags": row.tags or [],
        }
        for row in rows
    }


# ───────────────────────────────────────────────────────────────────────────
# 决策结构与编排
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class PrefilterDecision:
    url: str
    source: str
    action: str                      # score / inherit / drop / audit（实际执行）
    reasons: list[str] = field(default_factory=list)
    hard_signal_score: int = 0
    prefilter_score: int = 0
    source_tier: str = "B"
    event_sim: float | None = None
    shadow_action: str | None = None  # 影子模式：原本会执行的动作

    def reason_string(self) -> str:
        return "; ".join(self.reasons)


@dataclass
class InheritedItem:
    raw: object
    root_score: float
    root_tags: list[str]
    reason: str


@dataclass
class PrefilterResult:
    kept: list = field(default_factory=list)          # 送 LLM（含审计样本，不含继承）
    inherited: list = field(default_factory=list)     # 正常模式：继承根评分
    dropped_urls: list = field(default_factory=list)  # 正常模式：被丢弃
    decisions: dict = field(default_factory=dict)
    audit_count: int = 0


async def prefilter_news(
    items: list,
    session=None,
    source_quality: dict[str, SourceQuality] | None = None,
    shadow: bool | None = None,
) -> PrefilterResult:
    """对一批新闻执行预筛，返回送评 / 继承 / 丢弃决策。

    不修改传入 items；影子模式下 kept 包含全部 items（仍送 LLM），仅记录决策。
    """
    own_session = session is None
    if own_session:
        session = async_session()
    try:
        if source_quality is None:
            source_quality = await compute_source_quality(session)

        related_urls = {
            getattr(it, "related_to_url", None)
            for it in items
            if getattr(it, "related_to_url", None)
        }
        root_map = await _load_roots(session, related_urls)

        shadow = settings.PREFILTER_SHADOW_MODE if shadow is None else shadow

        result = PrefilterResult()
        audit_rate = settings.PREFILTER_AUDIT_SAMPLE_RATE
        drop_threshold = settings.PREFILTER_DROP_PREFILTER_SCORE

        for it in items:
            url = getattr(it, "url", "") or ""
            src = getattr(it, "source", "") or ""
            text = _text(it)

            quality = source_quality.get(src)
            tier = classify_source(quality, src, url)
            official = is_official_source(src, url)
            hard = hard_signal_score(it)
            pf = compute_prefilter_score(it, quality, tier, hard)
            reasons: list[str] = []
            real_action = "score"  # 默认送评；后续规则可能改写为 drop/inherit

            # 1) 高价值兜底：官方 / 重大事件强制送评
            if official:
                real_action = "score"
                reasons.append("官方/权威信源强制送评")
            elif contains_major_event_signal(text):
                real_action = "score"
                reasons.append("重大事件信号强制送评")
            else:
                # 2) 内容完整性 / 低价值模式
                if not has_minimum_information(it):
                    real_action = "drop"
                    reasons.append("内容不完整/命中低价值模式")
                # 3) 同事件新事实压缩
                elif getattr(it, "related_to_url", None):
                    root = root_map.get(it.related_to_url)
                    if root and root.get("ai_score") is not None:
                        need, sim = needs_individual_scoring(it, root)
                        if not need:
                            real_action = "inherit"
                            reasons.append(
                                f"同事件无新事实(标题相似度{sim:.2f})，继承根评分"
                            )
                        else:
                            reasons.append(
                                f"同事件有新事实(标题相似度{sim:.2f})，送评"
                            )
                    # 根尚未入库（同批次首篇）→ 正常送评
                # 4) 信源分级门控
                if real_action == "score":
                    if tier == "D":
                        # 长期噪声信源：默认限流，仅抽样送评
                        if random.random() >= audit_rate:
                            real_action = "drop"
                            reasons.append("D级信源限流（仅抽样送评）")
                        else:
                            reasons.append("D级信源抽样送评（审计）")
                    elif tier == "C" and hard < settings.PREFILTER_TIER_C_MIN_HARD_SIGNAL:
                        real_action = "drop"
                        reasons.append(
                            f"C级信源硬信号不足(hard={hard}<{settings.PREFILTER_TIER_C_MIN_HARD_SIGNAL})"
                        )
                # 5) prefilter_score 极低兜底（官方/重大事件已提前放行，不受此限）
                if real_action == "score" and pf <= drop_threshold:
                    real_action = "drop"
                    reasons.append(f"prefilter_score 过低({pf}<={drop_threshold})")

            # 审计抽样（正常模式，针对将丢弃项）
            if real_action == "drop" and not shadow and random.random() < audit_rate:
                real_action = "audit"
                result.audit_count += 1
                reasons.append("审计抽样：仍送 LLM")

            dec = PrefilterDecision(
                url=url,
                source=src,
                action="score" if shadow else real_action,
                reasons=reasons,
                hard_signal_score=hard,
                prefilter_score=pf,
                source_tier=tier,
                event_sim=None,
                shadow_action=real_action if shadow else None,
            )

            if shadow:
                result.kept.append(it)
            else:
                if real_action in ("score", "audit"):
                    result.kept.append(it)
                elif real_action == "inherit":
                    root = root_map.get(it.related_to_url)
                    result.inherited.append(
                        InheritedItem(
                            raw=it,
                            root_score=float(root["ai_score"]),
                            root_tags=root.get("tags") or [],
                            reason=dec.reason_string(),
                        )
                    )
                else:  # drop
                    result.dropped_urls.append(url)
            result.decisions[url] = dec

        _log_decisions(result, shadow)
        return result
    finally:
        if own_session:
            await session.close()


def _log_decisions(result: PrefilterResult, shadow: bool) -> None:
    mode = "shadow" if shadow else "live"
    if shadow:
        drop = sum(1 for d in result.decisions.values() if d.shadow_action == "drop")
        inherit = sum(1 for d in result.decisions.values() if d.shadow_action == "inherit")
        logger.info(
            "[预筛:%s] 总量=%d 若启用将 drop=%d inherit=%d（当前仅记录不生效）",
            mode, len(result.decisions), drop, inherit,
        )
    else:
        logger.info(
            "[预筛:%s] 送评=%d 继承=%d 丢弃=%d 审计=%d",
            mode, len(result.kept), len(result.inherited),
            len(result.dropped_urls), result.audit_count,
        )
