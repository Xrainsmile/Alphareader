"""世界线 P1-c：归线打分器（S = 0.55E + 0.30M + 0.15R）。

评分只做「事件该不该挂到某条线」的判定，不负责建线、不负责写线卡。
影子模式下（THREAD_ROUTING_SHADOW=True）只算分 + 留痕，不写 thread_events。

设计要点：
1. 三步走：eligible() 硬筛选 → 打分 → 阈值判定。
   硬筛选里 is_manually_excluded 排第一，因为人工摘除过的线不能再自动归回，
   否则治理失效（人工治理是权威，算法必须服从）。
2. E 用标准加权 Jaccard（Σmin/Σmax），不用覆盖率。
   覆盖率会让长线（实体多）天然吸走所有事件，正是要防的「强行归类」。
3. is_generic 实体一律排除在 E 之外。否则两条无关的线会因为都提到
   「市场」「美国」而被判相似。
4. mechanism_hints 为空 **= 该维度无信息**，做权重重分配而非补固定分
   （P0-1，2026-10-14）。旧实现补 1.0/0.5 后照常按 0.30 加权，等于白送分；
   生产库覆盖率仅 1.9%，实测 S 有 79% 与"是否同一条线"无关。
5. R 用指数衰减（半衰期 72h），天然落在 (0,1]，不需要额外的 CAP。
   活跃线滚雪球的问题由衰减本身解决。
6. 披露形式 / 通用名词实体（8-K、原油、AI…）一律排除（P0-3）。
   它们描述"怎么说的"而非"说的是谁"，作为锚点会把无关事件串成一条线。
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.config import settings
from app.database import async_session
from app.services.entity_writer import canonicalize  # noqa: F401  P0-6 动态归一化

logger = logging.getLogger(__name__)

# 不参与归线的线状态（已合并/已拆分，保留重定向指针但不再接收新事件）
_INELIGIBLE_STATUS = {"merged", "split"}

# P0-3 黑名单缓存（配置不变时不重复构造集合）
_DENY_CACHE: set[str] | None = None


def weighted_jaccard(
    ev_entities: dict[str, int],
    thread_entities: dict[str, int],
) -> float:
    """标准加权 Jaccard：Σmin(w) / Σmax(w)。

    不用「覆盖率」Σ(交集)/Σ(事件)，因为覆盖率会让实体多的长线天然吸走
    所有事件——那正是要防的强行归类。

    Args:
        ev_entities:      {实体规范名: 权重}，来自 event_entities（已排除 is_generic）
        thread_entities:  {实体规范名: 权重}，线的 core_entities

    Returns:
        0.0 ~ 1.0。两边都为空时返回 0.0（无实体可比对，不该给分）。
    """
    if not ev_entities and not thread_entities:
        return 0.0
    keys = set(ev_entities) | set(thread_entities)
    inter = sum(min(ev_entities.get(k, 0), thread_entities.get(k, 0)) for k in keys)
    union = sum(max(ev_entities.get(k, 0), thread_entities.get(k, 0)) for k in keys)
    if union <= 0:
        return 0.0
    return inter / union


def weighted_jaccard_normalized(
    ev_entities: dict[str, int],
    thread_entities: dict[str, int],
) -> float:
    """归一化加权 Jaccard（P0-5）：两侧各除以自身 Σw 后再算 Σmin/Σmax。

    解决 core_entities 权重跨章节累加导致的 E 被系统性压低问题，
    详见 compute_score 内注释。归一化后 E 与线的成熟度解耦。
    """
    if not ev_entities or not thread_entities:
        return 0.0
    se = sum(ev_entities.values()) or 1
    st = sum(thread_entities.values()) or 1
    keys = set(ev_entities) | set(thread_entities)
    inter = sum(min(ev_entities.get(k, 0) / se, thread_entities.get(k, 0) / st) for k in keys)
    union = sum(max(ev_entities.get(k, 0) / se, thread_entities.get(k, 0) / st) for k in keys)
    return inter / union if union > 0 else 0.0


def shared_entity_count(
    ev_entities: dict[str, int],
    thread_entities: dict[str, int],
) -> int:
    """事件与线共有的**非泛化**实体个数。

    与 E 互补：E 是比例，共现数是绝对量。两者都要——
    E 防「长线靠比例优势吸事件」，共现数防「小线靠一两个实体硬凑高 E」。
    """
    return len(set(ev_entities) & set(thread_entities))


def entity_gate(
    e: float,
    shared: int,
) -> tuple[bool, str]:
    """实体门控：归线的立身之本，不满足则一票否决（不看 S）。

    两道关：
      1. E >= THREAD_T_JOIN_ENTITY：实体重合比例过低
      2. shared >= THREAD_MIN_SHARED_ENTITIES：只共享 1 个实体不足以证明同线

    为什么必须独立于 S：S 是加分制，M 与 R 会在实体薄弱时把总分抬过阈值。
    实测「任一共同实体 → S = 0.30*1.0 + 0.15*1.0 = 0.45 >= 0.40」，
    单靠阈值挡不住。门控把「实体重合」从加分项改回**必要条件**。

    ★ 为什么用「共同实体数」而不是「共同**核心**实体（weight>=3）」：
      link_event_entities 的唯一调用点（event_synthesizer）用默认
      default_weight=1 入参，全库 event_entities.weight 恒为 1，
      weight >= THREAD_CORE_ENTITY_WEIGHT(3) 永远不成立。
      若按核心实体判定，本门控会否决掉 100% 的候选，归线彻底停摆。

    Returns:
        (是否放行, 否决原因)。放行时原因为空串。
    """
    if not settings.THREAD_ENTITY_GATE_ENABLED:
        # 紧急回退：只保留「E<=0 一票否决」，退回收紧前的宽松行为。
        # 用于门控误杀正常归线时，改配置重启即可止血，无需改代码发版。
        if e <= 0:
            return False, "E=0"
        return True, ""

    if e < settings.THREAD_T_JOIN_ENTITY:
        return False, f"E={e:.4f} < {settings.THREAD_T_JOIN_ENTITY}"
    if shared < settings.THREAD_MIN_SHARED_ENTITIES:
        return False, f"shared={shared} < {settings.THREAD_MIN_SHARED_ENTITIES}"
    return True, ""


def mechanism_score(
    ev_mechanisms: list[str] | None,
    thread_mechanism: str | None,
) -> float:
    """机制匹配分 M。

    三条规则，优先级从高到低：
    1. 事件机制为空数组 / None → THREAD_M_MISSING_SCORE（默认 0.5，中性）
    2. 线未设机制（None 或空串）→ 0.5（中性，不惩罚也不奖励）
    3. 两者都有 → 命中 1.0，未命中 0.0

    ★ 第 1 条曾被实现为 1.0，语义是「不参与门控」，但这是错的：
    归线是**加分制**而非门控制，返回 1.0 等于每条线白送 0.30 分。
    实测机制抽取覆盖率极低（绝大多数事件 mechanism_hints 为空），
    于是 0.30 的加权被无条件发放；叠加新线 last_event_at=None 时
    recency_bonus 也返回 1.0 的 0.15，S 恒 >= 0.45 ——
    无论实体重不重合都能过 T_JOIN=0.40。

    真正「不参与门控」的正确做法是让该分项取中性值，使总分由 E 主导。
    0.5 而非 0.0：0.0 会让机制明确冲突的线与机制未知的线同分，
    丢失了「线有机制、事件无机制」时应有的中间态信息。
    """
    if not ev_mechanisms:
        # ★ P0-1：返回 None 表示"该维度无信息"，由 compute_score 做权重重分配。
        # 旧实现返回固定分（1.0 / 0.5）并照常计入加权和，等于白送 0.30 分。
        return None
    if not thread_mechanism:
        return 0.5
    return 1.0 if thread_mechanism in ev_mechanisms else 0.0


def recency_bonus(last_event_at: datetime | None, now: datetime | None = None) -> float:
    """活跃度奖励 R = 0.5 ** (hours_since / half_life)，落在 (0, 1]。

    用指数衰减而非线性，避免「刚更新」和「3 天前更新」差距过小。
    天然有上界 1.0，不需要再设 CAP——这正是你担心的活跃线滚雪球的解法：
    越久远的线奖励越低，新线不会因为没有历史而被老线压制。
    """
    if last_event_at is None:
        return 1.0  # 全新的线，给满奖励（鼓励胚胎线成长）
    now = now or datetime.now(timezone.utc)
    if last_event_at.tzinfo is None:
        last_event_at = last_event_at.replace(tzinfo=timezone.utc)
    hours = (now - last_event_at).total_seconds() / 3600.0
    if hours <= 0:
        return 1.0
    half_life = max(settings.THREAD_RECENCY_HALF_LIFE_HOURS, 1e-6)
    return 0.5 ** (hours / half_life)


def compute_score(
    ev_entities: dict[str, int],
    thread_entities: dict[str, int],
    ev_mechanisms: list[str] | None,
    thread_mechanism: str | None,
    last_event_at: datetime | None,
    now: datetime | None = None,
) -> tuple[float, float, float, float]:
    """算 S 总分。返回 (S, E, M, R)——分项一并返回，影子期调权重要靠它。

    影子模式的核心产出就是这个四元组：没有分项，7 天后无法判断
    是 E 偏高还是 M 偏低导致的误判，权重就没法调。
    """
    # ★ P0-5（2026-10-14）：加权 Jaccard 归一化（修复 E 被系统性压低）。
    #
    # 背景：core_entities 权重是**跨章节累加**的（伊朗在某线出现 21 章 → 权
    # 重 21），Σw 随线成熟单调增长；单事件 Σw 通常只有 3~6。未归一化时：
    #     分子 ≤ min(事件Σw, 线Σw) ≈ 5    分母 ≈ 5 + 63 = 68  → E ≤ 0.073
    # 实测 441 条真实配对（事件 vs 其人工基线所属线）E 中位数仅 0.036、
    # p75 仅 0.077；六条主线的 E 理论上限只有 0.073~0.161。
    # 后果：T_JOIN_ENTITY 设 0.15 或 0.30 都会误杀几乎全部真阳性——
    # 门控越紧、线越成熟，误杀越彻底（负反馈：好线反而归不进去）。
    #
    # 正解：两侧各除以自身 Σw，让 Jaccard 比较**权重分布形态**而非绝对量级，
    # E 回到 0~1 且与线的成熟度解耦。实测中位数 0.036 → 0.111。
    if settings.THREAD_E_NORMALIZE:
        e = weighted_jaccard_normalized(ev_entities, thread_entities)
    else:
        e = weighted_jaccard(ev_entities, thread_entities)
    m = mechanism_score(ev_mechanisms, thread_mechanism)
    r = recency_bonus(last_event_at, now)

    # ★ P0-1（2026-10-14）：机制未知时做权重重分配，而非给固定分。
    #
    # 背景：生产库 mechanism_hints 抽取覆盖率仅 1.9%（16/838），98% 的事件
    # 走 M_MISSING 分支。若照旧按 0.30 权重计入一个固定值（原 1.0、现 0.5），
    # 等于向每条候选线无条件发放 0.30*0.5=0.15 ~ 0.30*1.0=0.30 的"保底分"；
    # 叠加 R≈1 的 0.15，S 凭空 >= 0.30，实体门控一旦放宽就立刻过线。
    # 实测现网 S 有 79% 来自 M+R、与"是否同一条线"无关，M 均值 0.991。
    #
    # 正解：机制未知 = 该维度无信息，应将其权重**摊回**已知维度（E、R），
    # 使 S 始终表示"已有证据下的加权平均"，而不是"未知项按中位猜测补齐"。
    # 这样 S 与 E 单调相关，T_JOIN 才真正有区分度。
    w_e = settings.THREAD_SCORE_W_ENTITY
    w_m = settings.THREAD_SCORE_W_MECHANISM
    w_r = settings.THREAD_SCORE_W_RECENCY
    if settings.THREAD_M_REDISTRIBUTE_WEIGHT and m is None:
        s = (w_e * e + w_r * r) / max(w_e + w_r, 1e-6)
    else:
        # m 为 None 时回落到 M_MISSING_SCORE（兼容开关关闭的旧行为）
        s = w_e * e + w_m * (settings.THREAD_M_MISSING_SCORE if m is None else m) + w_r * r
    return s, e, (0.5 if m is None else m), r


def infer_event_kind(title: str, entities: list[str] | None = None) -> str:
    """P1-6（2026-10-14）：推断事件类型，用于跨类型硬门控。

    返回类型标签：
        disclosure  信息披露（8-K / 财报 / 监管文件）
        market      市场快照（指数 / 板块 / 开盘收盘）
        rating      投行评级 / 目标价调整
        geopolitics 地缘冲突 / 军事 / 制裁
        macro       宏观数据 / 央行政策
        earnings    公司业绩 / 经营
        deal        并购 / 融资 / 资本运作
        product     产品发布 / 技术进展
        other       其他

    为什么需要：现网把"闪迪业绩指引"和"伊朗封锁海峡"混在同一条线，
    根因是只比实体不比类型——两者可能共享"油价""美股"这类通用实体。
    世界线是**争夺标的 + 推进机制**的连续叙事，类型不同则机制必然不同。
    """
    t = (title or "").strip()
    if not t:
        return "other"
    rules: list[tuple[str, list[str]]] = [
        ("disclosure", [r"8-K", r"8-K/A", r"10-K", r"10-Q", r"6-K", r"20-F",
                        r"提交.{0,4}文件", r"披露.{0,6}文件", r"SEC"]),
        ("rating", [r"目标价", r"评级", r"跑赢行业", r"上调.{0,4}至", r"下调.{0,4}至",
                    r"维持.{0,4}评级", r"给予.{0,4}评级"]),
        ("market", [r"开盘", r"收盘", r"收涨", r"收跌", r"领涨", r"领跌", r"走强",
                    r"走弱", r"下挫", r"翻红", r"低开", r"高开", r"盘中", r"夜盘",
                    r"盘初", r"三大指数", r"创业板指", r"恒指", r"科创50"]),
        ("geopolitics", [r"袭击", r"遭袭", r"遇袭", r"军事", r"军演", r"制裁",
                         r"封锁", r"停火", r"武装", r"导弹", r"无人机袭击",
                         r"霍尔木兹", r"海峡", r"战争", r"冲突"]),
        ("macro", [r"CPI", r"PPI", r"PMI", r"非农", r"失业率", r"GDP", r"通胀",
                   r"美联储", r"央行", r"利率", r"加息", r"降息", r"国债收益率",
                   r"贸易帐", r"逆差", r"顺差", r"LPR", r"MLF", r"消费信心"]),
        ("deal", [r"收购", r"洽购", r"合并", r"并购", r"私有化", r"融资",
                  r"配售", r"增发", r"IPO", r"招股", r"定增", r"要约"]),
        ("earnings", [r"业绩", r"财报", r"半年报", r"中报", r"净利", r"营收",
                      r"盈利", r"亏损", r"指引", r"派息", r"股息", r"回购"]),
        ("product", [r"发布", r"推出", r"上线", r"获批", r"试乘", r"量产",
                     r"下线", r"首发", r"亮相"]),
    ]
    for kind, pats in rules:
        for p in pats:
            if re.search(p, t, re.I):
                return kind
    return "other"


# ★ P1-6：跨类型禁止合并的组合。
# 设计原则：不是列"哪些能合"（列不全），而是列"哪些绝不能合"。
# 前者会随业务演进失效，后者是守恒的硬约束。
_INCOMPATIBLE_KINDS: dict[str, set[str]] = {
    "geopolitics": {"earnings", "product", "rating"},
    "earnings": {"geopolitics", "market", "disclosure"},
    "market": {"earnings", "geopolitics", "deal"},
    # ★ 2026-10-16 P0：disclosure 补 other。
    #   根因：8-K 是纯披露格式，标题不携带业务语义（"XX提交8-K披露经营业绩"），
    #   bge-m3 靠"经营业绩/协议"等通用词把它推到语义最近的大线上；
    #   而叙事线标题（"AI应用软件与云厂商变现"）不含类型关键词，
    #   _infer_thread_kind 判为 other，kind_conflict 对 other 一律放行，
    #   于是 19/53 条待落地事件全是 8-K 误归（实测 S 0.597~0.656）。
    #   disclosure 的价值在"披露动作"而非"叙事推进"，与任何未定型线都不相容。
    #   风险：真实含 8-K 的并购/业绩事件会被一并拦下——但 8-K 标题本身
    #   不携带业务语义，拦掉不亏（C 收容线兜底）。
    "disclosure": {"earnings", "geopolitics", "market", "other"},
    "rating": {"geopolitics", "market"},
    "product": {"geopolitics"},
    "macro": {"earnings", "product"},
    "deal": {"market", "geopolitics"},
}


def kind_conflict(kind_a: str, kind_b: str) -> bool:
    """两个事件类型是否互斥（不可归入同一条线）。"""
    if not kind_a or not kind_b or kind_a == kind_b:
        return False
    # ★ 2026-10-16 P0：disclosure 对"未定型线(other)"同样否决，
    #   故本条必须**先于** other 早退判断，否则永不生效。
    #   8-K 是纯披露格式，标题不携带业务语义，与任何叙事线都不相容；
    #   叙事线标题又常判不出类型（→other），两者叠加正是 8-K 扎堆的成因。
    if kind_a == "disclosure" and kind_b == "other":
        return True
    if kind_a == "other" or kind_b == "other":
        return False   # 未知类型不参与否决，避免误杀
    return kind_b in _INCOMPATIBLE_KINDS.get(kind_a, set())


async def _load_event_title(event_id: uuid.UUID) -> str:
    """取事件标题（P1-6 类型推断用）。失败返回空串，不阻断归线。"""
    sql = text("SELECT COALESCE(title, '') FROM events WHERE id = :eid")
    async with async_session() as session:
        val = (await session.execute(sql, {"eid": event_id})).scalar()
    return str(val or "")


def _infer_thread_kind(thread: dict) -> str:
    """推断一条线的事件类型。

    优先用线标题（rollup 后的标题最能代表线主题）；标题缺失时退回
    mechanism_key。返回 'other' 表示未知——未知类型不参与互斥否决，
    避免门控误杀真实归线（宁可放过，不可错杀）。
    """
    t = (thread.get("title") or "").strip()
    if t:
        k = infer_event_kind(t)
        if k != "other":
            return k
        # ★ 2026-10-16：title 判不出类型时回退 mechanism_key。
        #   原写法 `if t: return infer_event_kind(t)` 让下面整段成为死代码——
        #   线都有 title，且叙事线标题（"存储与HBM超级周期""AI应用软件与云厂商变现"）
        #   不含任何类型关键词，一律判 other；other 又不参与互斥否决，
        #   于是 8-K 长驱直入。这是 8-K 扎堆的**第二层根因**（第一层是 A）。
    mk = (thread.get("mechanism_key") or "").strip()
    if not mk:
        return "other"
    # 机制键形如「地缘对抗」「价格传导」「业绩兑现」，用关键词回退映射
    if re.search(r"地缘|制裁|军事|冲突", mk):
        return "geopolitics"
    if re.search(r"价格|供需|油价", mk):
        return "macro"
    if re.search(r"业绩|营收|财报", mk):
        return "earnings"
    if re.search(r"模型|产品|技术", mk):
        return "product"
    # ★ 2026-10-16 P1（治本）：补 mechanism_key → kind 的映射缺口。
    #   现网 36 条线里大量叙事线的 mechanism_key 含明确机制词，
    #   却落到最后 return "other" —— 因为上面 4 条分支覆盖不全。
    #   后果：other 不参与互斥否决，任何类型都能飘进来（8-K 扎堆的放大器）。
    #   实测缺口线：存储与HBM「供需缺口→涨价→股价与下游成本」、
    #   AI应用软件「AI收入→指引修正→股价分化」等，均应为 earnings/product 类
    #   叙事线，此前一律判 other。
    #   顺序要紧：先判具体机制，再回退宏泛词。
    if re.search(r"产能|订单|出货|供应链|库存|涨价|缺口", mk):
        return "earnings"
    if re.search(r"指引|订阅|变现|收入|商业化|定价", mk):
        return "product"
    if re.search(r"利率|通胀|政策|流动性|估值|资产|资本|融资|募资|回购", mk):
        return "macro"
    if re.search(r"监管|审批|审查|谈判|管制|出口", mk):
        return "deal"
    if re.search(r"发射|频谱|部署|试点|扩张|投入", mk):
        return "product"
    return "other"


def is_market_snapshot(title: str) -> bool:
    """P2-11（2026-10-14）：是否为日频市场快照（不进世界线）。

    现网约 150 条「港股开盘XX」「A股三大指数XX」被当成世界线章节。
    它们是**市场脉搏**——描述当天盘面，不构成"争夺标的 + 推进机制"的叙事。
    混进世界线会稀释主线：一条 33 章的线里可能有一半是无关的收盘综述。
    """
    if not settings.THREAD_MARKET_SNAPSHOT_ENABLED or not title:
        return False
    # 1) 强信号：直接判快照（描述的是盘面本身，无追踪标的）
    for p in settings.THREAD_MARKET_SNAPSHOT_STRONG:
        if re.search(p, title):
            return True

    # 2) 弱信号：先检查是否有豁免事件（有具体事件 → 盘面只是结果）
    weak_hit = False
    for p in settings.THREAD_MARKET_SNAPSHOT_WEAK:
        if re.search(p, title):
            weak_hit = True
            break
    if weak_hit:
        for p in settings.THREAD_MARKET_SNAPSHOT_RESCUE:
            if re.search(p, title):
                return False
        return True

    return False


def time_gap_penalty(last_event_at, now: datetime) -> float:
    """P1-7（2026-10-14）：时间断线惩罚系数，落在 (0, 1]。

    世界线是**连续追踪**的叙事。现网 33 章巨型线跨 2026-08-05 ~ 10-13，
    中间 9 月完全空窗仍算同一条线——那是两条被硬粘起来的线。
    规则：间隔超过 THREAD_TIME_GAP_DAYS 后线性衰减，超过 2 倍则趋于 0，
    由调用方乘到 S 上（软惩罚，不硬否决：避免误杀确有长期跨度的线）。
    """
    if last_event_at is None:
        return 1.0
    if last_event_at.tzinfo is None:
        last_event_at = last_event_at.replace(tzinfo=timezone.utc)
    days = (now - last_event_at).total_seconds() / 86400.0
    limit = max(settings.THREAD_TIME_GAP_DAYS, 1e-6)
    if days <= limit:
        return 1.0
    # 超过 limit 后线性降到 0（2*limit 天时归零）
    return max(0.0, 1.0 - (days - limit) / limit)


def _denylist() -> set[str]:
    """P0-3：披露形式 / 通用名词实体黑名单（带缓存）。

    设计要点：这是**减法**而非加法——不去穷举"哪些实体有区分度"
    （永远列不全），而是剔除已知的"形式类"与"通用类"名字。
    """
    global _DENY_CACHE
    if _DENY_CACHE is None:
        _DENY_CACHE = {str(x).strip() for x in (settings.THREAD_ENTITY_DENYLIST or []) if str(x).strip()}
    return _DENY_CACHE


async def _load_event_entities(event_id: uuid.UUID) -> dict[str, int]:
    """加载事件的实体权重表，已排除 is_generic。

    核心实体（weight >= THREAD_CORE_ENTITY_WEIGHT）放大 3 倍——
    这是你公式里「核心实体 3 倍加权」的落点。
    """
    sql = text("""
        SELECT e.canonical_name, ee.weight
        FROM event_entities ee
        JOIN entities e ON e.id = ee.entity_id
        WHERE ee.event_id = :eid
          AND COALESCE(e.is_generic, false) = false
    """)
    async with async_session() as session:
        rows = (await session.execute(sql, {"eid": event_id})).all()
    core = settings.THREAD_CORE_ENTITY_WEIGHT
    blocked = _denylist()
    out: dict[str, int] = {}
    for name, w in rows:
        if not name:
            continue
        # ★ P0-3：披露形式不参与归线。
        #   它们描述的是"怎么说的"而非"说的是谁"，作为锚点会把无关事件串线。
        if name in blocked:
            continue
        # ★ P0-6：加载时动态归一化。
        #   ALIAS_MAP 是**持续扩充**的，而存量 canonical_name 是写入那一刻的
        #   快照。实测 18 个实体（Nvidia/AMD/IEA/三星电子/美光科技...）在库里
        #   仍是英文或啰嗦写法，与线侧中文规范名零交集，E 恒为 0。
        #   比较时才归一化，可覆盖全部存量，无需回刷数据库。实测 +3 条。
        name = canonicalize(name)[0]
        if name in blocked:
            continue
        w = int(w or 1)
        # 同一规范名可能有多条关联（不同别名归并后），取最大权重
        out[name] = max(out.get(name, 0), core if w >= core else w)
    return out


async def _load_event_mechanisms(event_id: uuid.UUID) -> list[str] | None:
    """加载事件的机制列表。

    返回 None 表示「从未抽取」（区分于空数组「明确无机制」）。
    """
    sql = text("SELECT mechanism_hints FROM events WHERE id = :eid")
    async with async_session() as session:
        val = (await session.execute(sql, {"eid": event_id})).scalar()
    return list(val) if val is not None else None


async def _load_manual_exclusions(event_id: uuid.UUID) -> set[uuid.UUID]:
    """查询该事件被人工排除过的线集合。

    只认 'remove' 且未 'restore' 的记录。restore 是 remove 的撤销操作，
    两者配对——误摘后必须能恢复，否则治理不可逆。
    """
    sql = text("""
        SELECT DISTINCT thread_id FROM thread_operations o
        WHERE o.target_type = 'event'
          AND o.target_id = :eid
          AND o.operation = 'remove'
          AND o.thread_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM thread_operations r
              WHERE r.target_type = 'event'
                AND r.target_id = o.target_id
                AND r.thread_id = o.thread_id
                AND r.operation = 'restore'
                AND r.created_at > o.created_at
          )
    """)
    async with async_session() as session:
        rows = (await session.execute(sql, {"eid": event_id})).scalars().all()
    return {r for r in rows if r is not None}


async def _load_candidate_threads() -> list[dict]:
    """加载候选线（active/dormant/embryo，按最近更新倒序）。"""
    sql = text("""
        SELECT id, title, mechanism_key, core_entities, last_event_at, status
        FROM threads
        WHERE status NOT IN ('merged', 'split')
        ORDER BY last_event_at DESC NULLS LAST
        LIMIT :lim
    """)
    async with async_session() as session:
        rows = (await session.execute(
            sql, {"lim": settings.THREAD_CANDIDATE_LIMIT}
        )).mappings().all()
    return [dict(r) for r in rows]


def _thread_entity_weights(core_entities: object) -> dict[str, int]:
    """把 threads.core_entities（JSONB）转成 {名称: 权重}。

    兼容两种存法：
    - 对象式 {"胡塞武装": 3, "曼德海峡": 1}
    - 数组式 ["胡塞武装", "曼德海峡"]（默认权重 1）
    """
    blocked = _denylist()
    if isinstance(core_entities, dict):
        raw = {str(k): int(v or 1) for k, v in core_entities.items()}
    elif isinstance(core_entities, list):
        raw = {str(x): 1 for x in core_entities}
    else:
        return {}

    # ★ P0-6：与事件侧对称，线侧也在比较时动态归一化。
    #   ALIAS_MAP 持续扩充，存量 core_entities 里的旧写法（如「霍尔木兹」）
    #   需要在此归一到线侧规范名，才能与事件侧对齐。
    out: dict[str, int] = {}
    for k, v in raw.items():
        c = canonicalize(k)[0]
        if c in blocked:
            continue
        out[c] = max(out.get(c, 0), v)
    return out


async def _load_disclosure_sink() -> dict | None:
    """取 8-K 收容线（按 mechanism_key 识别，人工预置）。

    为什么用 mechanism_key 而不是固定 uuid：uuid 在不同环境（本地/服务器/容器）
    不一致，硬编码会在换库后指向空线。mechanism_key 是业务语义，可移植。
    """
    sql = text("""
        SELECT id, title, mechanism_key, status
        FROM threads
        WHERE mechanism_key = :mk
          AND status NOT IN ('merged', 'split')
        ORDER BY chapter_count DESC, created_at ASC
        LIMIT 1
    """)
    async with async_session() as session:
        row = (await session.execute(
            sql, {"mk": settings.THREAD_DISCLOSURE_SINK_KEY}
        )).mappings().first()
    return dict(row) if row else None


async def _route_disclosure_sink(
    event_id: uuid.UUID, ev_kind: str, excluded: set
) -> list[dict] | None:
    """8-K 等纯披露事件 → 收容线短路归线。

    Returns:
        None = 不适用（未启用 / 非 disclosure / 无收容线），调用方继续走语义路
        list = 已命中收容线，调用方应直接返回

    设计取舍：S 固定 1.0 而非语义分。收容线是"垃圾桶"不是"叙事线"，
    语义分对它没有意义；给它 1.0 是为了让 thread_route_scores 里
    这批记录可辨识（gate='disclosure_sink'），方便日后统计与审计。
    """
    if not settings.THREAD_DISCLOSURE_SINK_ENABLED:
        return None
    if ev_kind != "disclosure":
        return None

    sink = await _load_disclosure_sink()
    if sink is None:
        return None

    tid = sink["id"]
    if tid in excluded:
        return None   # 人工排除优先于一切，与规则路/语义路一致

    return [{
        "thread_id": tid,
        "title": sink.get("title"),
        "S": 1.0, "sim": 1.0, "E": 0.0, "M": 0.0, "R": 0.0,
        "join": True,
        "gate": "disclosure_sink",
    }]


async def _semantic_route(
    event_id: uuid.UUID,
    ev_title: str,
    ev_kind: str,
    excluded: set,
    now: datetime,
) -> list[dict] | None:
    """P3-1：语义归线。cos(事件向量, 线原型) 排序取 Top-1。

    Returns:
        None = 语义不可用（无事件向量 / 无线有原型）→ 调用方决定是否回退规则
        list = 排序后的候选，命中项 join=True

    ★ 与规则路的三点本质差异：
      1. 不设绝对阈值（实测 F1 从 0.766 掉到 0.562），只按 rank 取第一
      2. 不做 entity_gate（主题型线 84% 的漏归出自此处）
      3. 仍是「先硬拦截、后排序」：market_snapshot / 人工排除 / 类型互斥
         三类拦截型规则保留，它们决定"要不要归"，语义只决定"归哪条"
    """
    from app.services import thread_prototype as tp

    ev_vec = await _load_event_embedding(event_id)
    if ev_vec is None:
        return None

    protos = await _load_thread_prototypes()
    if not protos:
        return None

    threads = await _load_candidate_threads()
    tmap = {str(t["id"]): t for t in threads}

    scored: list[dict] = []
    for tid, proto in protos.items():
        t = tmap.get(tid)
        if t is None:
            continue
        # ① 人工排除优先于一切（与规则路一致）
        if uuid.UUID(tid) in excluded:
            continue
        # ② 类型互斥一票否决（与规则路一致）
        th_kind = _infer_thread_kind(t)
        if settings.THREAD_KIND_GATE_ENABLED and kind_conflict(ev_kind, th_kind):
            scored.append({
                "thread_id": uuid.UUID(tid), "title": t.get("title"),
                "S": 0.0, "sim": 0.0, "join": False,
                "gate": f"kind_conflict:{ev_kind}/{th_kind}",
            })
            continue

        sim = tp.cosine(ev_vec, proto)
        # ③ 时间断线：作为**排序微调**（乘在相似度上），不做门控。
        #    规则路把它放在门控之后调权，语义路没有门控，故直接乘。
        gap = (time_gap_penalty(t.get("last_event_at"), now)
               if settings.THREAD_TIME_GAP_ENABLED else 1.0)
        s = sim * gap

        if sim < settings.THREAD_SEMANTIC_MIN_SIM:
            scored.append({
                "thread_id": uuid.UUID(tid), "title": t.get("title"),
                "S": round(s, 4), "sim": round(sim, 4), "join": False,
                "gate": f"sim<{settings.THREAD_SEMANTIC_MIN_SIM}",
            })
            continue

        scored.append({
            "thread_id": uuid.UUID(tid), "title": t.get("title"),
            "S": round(s, 4), "sim": round(sim, 4),
            "E": 0.0, "M": 0.0, "R": 0.0,
            "join": False,  # 排序后再定
            "gate": "",
        })

    if not scored:
        return None

    scored.sort(key=lambda x: x["S"], reverse=True)
    # ★ 只取第一。人工基线实测每事件恰好归 1 条线（441/441），
    #   Top-1 口径与业务定义吻合；取 Top-2/3 会让精确率从 76.6% 掉到 43.8%/30.1%。
    if scored and scored[0].get("gate") == "":
        scored[0]["join"] = True
    return scored


async def _load_event_embedding(event_id: uuid.UUID) -> "np.ndarray | None":
    """取事件 embedding。同 event_id 多行时取最新一行。"""
    sql = text("""
        SELECT event_embedding FROM news
        WHERE event_id = :eid AND event_embedding IS NOT NULL
        ORDER BY event_last_updated_at DESC NULLS LAST
        LIMIT 1
    """)
    async with async_session() as session:
        row = (await session.execute(sql, {"eid": event_id})).first()
    if not row or row[0] is None:
        return None
    try:
        import numpy as np
        return np.asarray(row[0], dtype=np.float32)
    except Exception:  # noqa: BLE001
        return None


async def _load_thread_prototypes() -> dict[str, "np.ndarray"]:
    """加载所有有原型的线：{thread_id_str: 归一化向量}。"""
    sql = text("""
        SELECT id::text, embedding FROM threads
        WHERE embedding IS NOT NULL
          AND status NOT IN ('merged', 'split')
    """)
    async with async_session() as session:
        rows = (await session.execute(sql)).all()
    out = {}
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return out
    for tid, emb in rows:
        if emb is None:
            continue
        try:
            out[tid] = np.asarray(emb, dtype=np.float32)
        except Exception:  # noqa: BLE001
            continue
    return out


async def route_event(
    event_id: uuid.UUID, reference_at: datetime | None = None
) -> list[dict]:
    """给单个事件归线。返回按 S 倒序的候选列表（含分项，供影子期调参）。

    Args:
        event_id: 待归线事件。
        reference_at: 计算 R（时效性）时的「当前时刻」。
            None（默认）＝实时场景，用 datetime.now()。
            批量回填必须传入事件自身时间——否则历史事件（8~10 月）拿
            now 比会指数衰减到 R≈0，0.15 权重的分项系统性归零，
            实测 S 上限被压到 0.4375，永远跨不过 T_JOIN=0.45。

    影子模式（THREAD_ROUTING_SHADOW=True）：
      - 只算分 + 写 thread_operations 留痕（operation='route'，operator='auto'）
      - 不写 thread_events、不改 threads
    非影子模式：额外把命中的线写入 thread_events。

    Returns:
        [{thread_id, title, S, E, M, R, join: bool}, ...]
    """
    if not settings.THREAD_ROUTING_ENABLED:
        return []

    ev_ents = await _load_event_entities(event_id)
    ev_mechs = await _load_event_mechanisms(event_id)
    excluded = await _load_manual_exclusions(event_id)
    threads = await _load_candidate_threads()

    # ★ P1-6：事件类型硬门控。只比实体不比类型，会把「闪迪业绩指引」
    #   和「伊朗封锁海峡」混进同一条线——两者共享"油价/美股"这类通用实体，
    #   但争夺标的与推进机制完全不同。
    ev_title = await _load_event_title(event_id)
    ev_kind = infer_event_kind(ev_title, list(ev_ents.keys()))

    # ★ P2-11：日频市场快照不进世界线。放在打分之前短路，
    #   既省算力也从根上避免"收盘综述污染主线叙事"。
    if is_market_snapshot(ev_title):
        logger.info("skip market snapshot event %s: %s", event_id, (ev_title or "")[:40])
        return []

    now = reference_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # ★ 2026-10-16 方案C：disclosure 收容线短路，优先于语义路。
    #   顺序要紧：必须在 _semantic_route 之前。8-K 一旦进入语义排序，
    #   就会被"经营业绩/重大协议"等通用词推到最近的大线上（实测 19/53 条）。
    #   收容线命中则不建新线——8-K 没有叙事价值，不该触发 maybe_create_thread。
    if settings.THREAD_DISCLOSURE_SINK_ENABLED:
        sink_hits = await _route_disclosure_sink(event_id, ev_kind, excluded)
        if sink_hits is not None:
            await _record_shadow(event_id, sink_hits)
            if not settings.THREAD_ROUTING_SHADOW:
                await _apply_routes(event_id, sink_hits)
            return sink_hits

    # ★ P3-1（2026-10-14 方向二）：语义归线优先。
    #   实测纯语义 F1=0.766 显著优于规则 0.578，且优于任何融合方案。
    #   语义不可用时按 THREAD_SEMANTIC_FALLBACK_RULE 决定是否回退规则路
    #   （默认 false：回退会拉低精确率 15.8pp）。
    if settings.THREAD_SEMANTIC_ENABLED:
        semantic = await _semantic_route(event_id, ev_title, ev_kind, excluded, now)
        if semantic is not None:
            top = semantic[: settings.THREAD_MAX_LINES_PER_EVENT]
            hits = [x for x in top if x["join"]]

            if hits and settings.THREAD_SEMANTIC_LLM_VERIFY:
                hits = await _llm_verify(event_id, hits)

            await _record_shadow(event_id, top)
            # ★ 只有「非影子」且「确实没归上」才建新线。
            #   影子模式下绝不建线——否则灰度期会凭空多出一堆线，
            #   等切正式开关时这批线已经在污染线池，无法撤销。
            if not settings.THREAD_ROUTING_SHADOW:
                await _apply_routes(event_id, hits)
                if not hits:
                    await maybe_create_thread(event_id)
            return top

        if not settings.THREAD_SEMANTIC_FALLBACK_RULE:
            # 语义不可用且不回退 → 留痕后直接返回，不建线也不乱归。
            # 「宁可不归」优于「归错线」：归错会污染线叙事，不归只是漏。
            logger.info("semantic route unavailable for event %s, no fallback", event_id)
            await _record_shadow(event_id, [])
            return []

    scored: list[dict] = []
    for t in threads:
        tid = t["id"]
        # ① 硬筛选第一关：人工排除优先于一切。
        #    人工治理是权威——被摘除过的线绝不能再自动归回，否则治理失效。
        if tid in excluded:
            continue
        # ★ P1-6 硬筛选第 1.5 关：事件类型互斥则直接否决（一票否决）。
        th_kind = _infer_thread_kind(t)
        if settings.THREAD_KIND_GATE_ENABLED and kind_conflict(ev_kind, th_kind):
            scored.append({
                "thread_id": tid,
                "title": t.get("title"),
                "S": 0.0, "E": 0.0, "M": 0.0, "R": 0.0,
                "join": False,
                "gate": f"kind_conflict:{ev_kind}/{th_kind}",
            })
            continue
        th_ents = _thread_entity_weights(t.get("core_entities"))
        s, e, m, r = compute_score(
            ev_ents, th_ents, ev_mechs, t.get("mechanism_key"),
            t.get("last_event_at"), now,
        )

        # ② 硬筛选第二关：实体门控（E 下限 + 最少共现实体数），一票否决。
        #    仅判 E=0 不够：实测 8-K 线与任意提交 8-K 的事件 E 恒 > 0，
        #    于是 S = 0.30*1.0(M空) + 0.15*1.0(R新线) = 0.45 稳定过阈值，
        #    几十家无关公司被串成一条线。必须给 E 设下限并要共现数兜底。
        # ★ P1-7：时间断线。间隔超过 THREAD_TIME_GAP_DAYS 的线乘衰减系数。
        #   放在门控**之后**：先保证实体/类型合格，再按时间连续性调权，
        #   避免顺序颠倒导致长期线被过早否决。
        gap = time_gap_penalty(t.get("last_event_at"), now) if settings.THREAD_TIME_GAP_ENABLED else 1.0
        if gap < 1.0:
            s = s * gap
        shared = shared_entity_count(ev_ents, th_ents)
        passed, why = entity_gate(e, shared)
        if not passed:
            scored.append({
                "thread_id": tid,
                "title": t.get("title"),
                "S": round(s, 4), "E": round(e, 4),
                "M": round(m, 4), "R": round(r, 4),
                "join": False,
                "gate": why,
            })
            continue

        scored.append({
            "thread_id": tid,
            "title": t.get("title"),
            "S": round(s, 4),
            "E": round(e, 4),
            "M": round(m, 4),
            "R": round(r, 4),
            "join": s >= settings.THREAD_T_JOIN,
            "gate": "",
        })

    scored.sort(key=lambda x: x["S"], reverse=True)
    top = scored[: settings.THREAD_MAX_LINES_PER_EVENT]
    hits = [x for x in top if x["join"]]

    # ★ P2-9：规则判定的灰色地带送 LLM 语义复核。
    #   规则只能判"形似"，判不了"是否同一条叙事"——8-K 扎堆就是铁证。
    if hits and settings.THREAD_LLM_VERIFY_ENABLED:
        hits = await _llm_verify(event_id, hits)

    await _record_shadow(event_id, top)
    if not settings.THREAD_ROUTING_SHADOW:
        await _apply_routes(event_id, hits)

    # 无命中 → 尝试建新线。
    # 必须放在打分之后：只有确认「没有线能收」才该开新线，否则会重复建线。
    if not hits:
        await maybe_create_thread(event_id)
    return top


async def _llm_verify(event_id: uuid.UUID, hits: list[dict]) -> list[dict]:
    """P2-9：对灰色地带的命中做语义复核，返回通过校验的子集。

    只查 should_verify(S) 为真的项；LLM 不可用/返回非法一律放行。
    """
    try:
        from app.services import thread_verifier
    except Exception as exc:  # noqa: BLE001
        logger.warning("thread_verifier import failed: %s", exc)
        return hits

    need = [h for h in hits if thread_verifier.should_verify(h["S"])]
    if not need:
        return hits

    ev_title, ev_summary = await _load_event_text(event_id)
    out = []
    for h in hits:
        if h not in need:
            out.append(h)
            continue
        ch = await _load_recent_chapters(h["thread_id"], limit=5)
        meta = await _load_thread_meta(h["thread_id"])
        verdict = await thread_verifier.verify(
            ev_title, ev_summary,
            meta.get("title") or h.get("title") or "",
            meta.get("contested_asset") or "",
            meta.get("mechanism_key") or "",
            ch,
        )
        if verdict is False:
            logger.info("llm rejected: event=%s thread=%s", event_id, h["thread_id"])
            h["gate"] = "llm_reject"
            continue
        out.append(h)
    return out


async def _load_event_text(event_id: uuid.UUID) -> tuple[str, str]:
    sql = text("SELECT COALESCE(title,''), COALESCE(summary,'') FROM events WHERE id=:eid")
    async with async_session() as session:
        r = (await session.execute(sql, {"eid": event_id})).first()
    return (r[0] or "", r[1] or "") if r else ("", "")


async def _load_recent_chapters(thread_id: uuid.UUID, limit: int = 5) -> list[str]:
    sql = text("""
        SELECT COALESCE(snapshot_title,'') FROM thread_events
        WHERE thread_id=:tid ORDER BY chapter_seq DESC NULLS LAST, created_at DESC LIMIT :lim
    """)
    async with async_session() as session:
        rows = (await session.execute(sql, {"tid": thread_id, "lim": limit})).scalars().all()
    return [x for x in rows if x]


async def _load_thread_meta(thread_id: uuid.UUID) -> dict:
    sql = text("""
        SELECT title, contested_asset, mechanism_key FROM threads WHERE id=:tid
    """)
    async with async_session() as session:
        r = (await session.execute(sql, {"tid": thread_id})).mappings().first()
    return dict(r) if r else {}


async def _record_shadow(event_id: uuid.UUID, scored: list[dict]) -> None:
    """影子期留痕：每对 (event, thread) 的 S/E/M/R 写入 thread_route_scores。

    这是影子期唯一的产出，7 天后靠它做分布分析调权重。
    分项必须落库——只有 S 而无 E/M/R，7 天后看到"归错了"却判断不出
    是 E 偏高还是 M 偏低，权重就没法调。

    写专用影子表而非 thread_operations：后者是人工治理审计表，
    混入算法观测数据会让 /history 被噪声淹没（详见模型注释）。
    """
    if not scored:
        return
    sql = text("""
        INSERT INTO thread_route_scores
            (event_id, thread_id, score, score_entity, score_mechanism,
             score_recency, joined, threshold, shadow, gate)
        VALUES
            (:eid, :tid, :s, :e, :m, :r, :joined, :th, :shadow, :gate)
    """)
    shadow = settings.THREAD_ROUTING_SHADOW
    async with async_session() as session:
        for item in scored:
            await session.execute(sql, {
                "eid": event_id,
                "tid": item["thread_id"],
                "s": item["S"],
                "e": item["E"],
                "m": item["M"],
                "r": item["R"],
                "joined": item["join"],
                "th": settings.THREAD_T_JOIN,
                "shadow": shadow,
                "gate": item.get("gate", ""),
            })
        await session.commit()


async def _attach_event(
    thread_id: uuid.UUID,
    event_id: uuid.UUID,
    score: float,
    session=None,
) -> bool:
    """把事件挂到线上（挂线的唯一入口）。

    为什么必须统一：建线与命中两条路径都要写 thread_events，
    分两处写就会再次出现「建线不挂线」这类只改一边的回归。

    列名用 role 而非 membership_role——ORM 模型把属性名改成了
    membership_role 并映射到列 role，但裸 SQL 必须用真实列名。
    此前写错列名导致 UndefinedColumnError，归线从未成功写入过。

    Args:
        session: 传入则复用外部事务（建线+挂载必须同一事务）。

    Returns:
        是否真的插入（False 表示已存在，幂等跳过）。
    """
    sql = text("""
        INSERT INTO thread_events
            (thread_id, event_id, role, chapter_id,
             assigned_by, match_score, snapshot_title)
        SELECT :tid, :eid, 'core', gen_random_uuid(), 'auto', :score, e.title
        FROM events e
        WHERE e.id = :eid
        ON CONFLICT (thread_id, event_id) DO NOTHING
        RETURNING id
    """)
    owns_session = session is None
    if owns_session:
        async with async_session() as session:
            rid = (await session.execute(
                sql, {"tid": thread_id, "eid": event_id, "score": score}
            )).scalar()
            if rid:
                await _sync_chapter_count(thread_id, session=session)
                await _refresh_profile_safely(thread_id, session)
            await session.commit()
    else:
        rid = (await session.execute(
            sql, {"tid": thread_id, "eid": event_id, "score": score}
        )).scalar()
        # 不 commit：由调用方统一提交，保证建线与挂载原子性
        if rid:
            await _sync_chapter_count(thread_id, session=session)
            # ★ 挂章后必须同步滚动重算线画像，与挂章同一事务。
            #   不做这一步，core_entities 就永远停在「建线时的首章实体」，
            #   而 thread_router 的 Jaccard 分母依赖它——分母冻结的长线
            #   会持续吸事件，正是「8-K 扎堆成一条线」的成因。
            await _refresh_profile_safely(thread_id, session)
            await _refresh_prototype_safely(thread_id, session)
    return rid is not None


async def _refresh_prototype_safely(thread_id: uuid.UUID, session) -> None:
    """P3-1：挂章后重算线语义原型；异常只记 log，绝不阻断挂线。

    与 _refresh_profile_safely 同构：原型是增强功能，刷新失败只会让
    下次归线少一个候选，抛异常却会让整个挂章事务回滚，代价大得多。
    """
    if not settings.THREAD_SEMANTIC_ENABLED:
        return
    try:
        from app.services import thread_prototype
        await thread_prototype.refresh_thread_prototype(thread_id, session=session)
    except Exception as exc:  # noqa: BLE001 — 兜底，绝不阻断挂线
        logger.warning("refresh thread prototype failed (thread=%s): %s", thread_id, exc)


async def _refresh_profile_safely(thread_id: uuid.UUID, session) -> None:
    """挂章后重算线画像；异常只记 log，绝不阻断挂线。

    实体层「失败不影响主流程」的设计约束同样适用于此：画像重算是增强功能，
    挂章成功但画像没刷新只会让下次归线质量下降，不会丢数据；
    而抛异常会让整个挂章事务回滚，代价大得多。
    """
    if not settings.THREAD_PROFILE_REFRESH_ENABLED:
        return
    try:
        from app.services import thread_profile
        await thread_profile.refresh_thread_profile(thread_id, session=session)
    except Exception as exc:  # noqa: BLE001 — 兜底，绝不阻断挂线
        logger.warning("refresh thread profile failed (thread=%s): %s", thread_id, exc)


async def _sync_chapter_count(thread_id: uuid.UUID, session) -> None:
    """把 threads.chapter_count 同步为 thread_events 实际行数。

    chapter_count 是冗余字段，之前只在建线时置 1、后续挂载不递增，
    导致线看着全是单章（孤岛率 100% 的假象），而实际已有 13 章的线。
    统一以关联表为准重算，避免这类字段漂移。
    """
    await session.execute(
        text("""
            UPDATE threads
            SET chapter_count = COALESCE(c.cnt, 0)
            FROM (SELECT COUNT(*) cnt FROM thread_events WHERE thread_id = :tid) c
            WHERE id = :tid
        """),
        {"tid": thread_id},
    )


async def _apply_routes(event_id: uuid.UUID, hits: list[dict]) -> None:
    """非影子模式：把命中的线写入 thread_events（幂等）。

    幂等靠 uq_thread_event 唯一约束 + ON CONFLICT DO NOTHING。
    chapter_no/chapter_seq 此处先置 NULL，由章节重排任务统一分配——
    归线只负责「挂不挂」，不负责「排第几」。
    """
    if not hits:
        return
    async with async_session() as session:
        for h in hits:
            await _attach_event(
                h["thread_id"], event_id, h["S"], session=session
            )
        await session.commit()
    logger.info("routed event %s -> %d threads", event_id, len(hits))


# ─────────────────────────── 自动建线（冷启动） ───────────────────────────

async def _load_event_core_entities(
    event_id: uuid.UUID, limit: int = 5
) -> list[tuple[str, int, int]]:
    """取事件的核心实体（已排除 is_generic），按 mention_count 倒序。

    返回 [(canonical_name, weight, mention_count), ...]。
    mention_count 用于「事件本身的实体是否够格开线」的门槛判定——
    一次性提及的生僻实体不该单独立线，否则线会碎片化。
    """
    sql = text("""
        SELECT e.canonical_name, ee.weight, COALESCE(e.mention_count, 1)
        FROM event_entities ee
        JOIN entities e ON e.id = ee.entity_id
        WHERE ee.event_id = :eid
            AND COALESCE(e.is_generic, false) = false
        ORDER BY ee.weight DESC, COALESCE(e.mention_count, 1) DESC
        LIMIT :lim
    """)
    async with async_session() as session:
        rows = (await session.execute(sql, {"eid": event_id, "lim": limit})).all()
    # ★ P1-5（2026-10-14）：线的锚实体必须是专有名词（公司、地名、人名、
    #   商品名），剔除披露形式与通用名词。现网 33 章巨型线的 core_entities
    #   是 {伊朗, 原油, 石油}——后两个跨所有能源新闻，不具区分度，
    #   是"该拆的没拆"的直接成因。
    blocked = _denylist()
    return [
        (r[0], int(r[1] or 1), int(r[2] or 1))
        for r in rows if r[0] and str(r[0]) not in blocked
    ]


async def maybe_create_thread(event_id: uuid.UUID) -> uuid.UUID | None:
    """无命中时按设计规则建新线（embryo），返回新线 id 或 None。

    规则（world-thread-design.md §5.3）：
        无命中 且 核心实体 >= 2 且 mention_count 达标 → 建线 embryo

    为什么必须实现：router 只在已有线里挑，没有线就永远「无命中」，
    无命中又不建线 → 冷启动死锁，thread_route_scores 永远空。
    这是影子期跑不出来的根因。

    建线后必须立即把当前事件挂进去作为第 1 章，且与建线在同一事务提交。
    否则新线 chapter_count=0 是空壳，批量回填时后续事件看不到线内容，
    最终得到大量只有一章甚至零章的孤岛线。

    Returns:
        新建线的 id；未达建线门槛时返回 None。
    """
    if not settings.THREAD_ROUTING_ENABLED:
        return None

    ents = await _load_event_core_entities(event_id)
    if len(ents) < settings.THREAD_MIN_CORE_ENTITIES:
        return None

    # mention_count 门槛：至少 THREAD_MIN_CORE_ENTITIES 个实体达标，
    # 避免「一个热实体 + 一个冷门实体」凑数开线。
    qualified = [x for x in ents if x[2] >= settings.THREAD_MIN_MENTION_COUNT]
    if len(qualified) < settings.THREAD_MIN_CORE_ENTITIES:
        return None

    core = {name: weight for name, weight, _ in qualified[: settings.THREAD_MAX_CORE_ENTITIES]}
    mechs = await _load_event_mechanisms(event_id)
    mechanism = mechs[0] if mechs else None

    sql = text("""
        INSERT INTO threads
            (title, mechanism_key, status, core_entities, chapter_count, last_event_at)
        SELECT e.title, :mech, 'embryo', CAST(:core AS jsonb), 0, e.last_updated_at
        FROM events e
        WHERE e.id = :eid
        RETURNING id
    """)
    async with async_session() as session:
        tid = (await session.execute(sql, {
            "eid": event_id, "mech": mechanism, "core": json.dumps(core),
        })).scalar()
        if tid:
            # 建线与挂载同一事务：要么新线带着第 1 章一起出现，要么都不出现。
            # 分两次提交会在中途崩溃时留下零章空线。
            await _attach_event(tid, event_id, 1.0, session=session)
            await session.execute(
                text("UPDATE threads SET chapter_count = 1 WHERE id = :tid"),
                {"tid": tid},
            )
        await session.commit()

    if tid:
        logger.info(
            "auto-created thread %s for event %s (entities=%d, mech=%s)",
            tid, event_id, len(qualified), mechanism,
        )
    return tid


# ─────────────────────────── 章节重排（chapter_no 分配） ───────────────────────────

async def renumber_thread_chapters(thread_id: uuid.UUID, session=None) -> int:
    """给一条线的章节重新分配 chapter_no：按事件发生时间**升序**，越早章号越小。

    ★ 为什么需要它：
      _attach_event 归线时把 chapter_no 置 NULL（归线只管「挂不挂」，
      不管「排第几」），设计上由本函数统一分配。此前这个分配任务从未注册，
      于是新章节永远停在 NULL，工作台按 total-i+1 反推，
      把**最新的新闻编成最小的章号**（2026-10-16 的新闻显示为第 1~4 章），
      即「越老的时间章节号反而更大」。

    ★ 排序键：COALESCE(occurred_at, created_at) ASC
      occurred_at 是事件发生时间（可能精确到日，00:00:00），
      created_at 是归线写入时间（有秒级精度）。两者结合可保证同日多章
      也有稳定次序。NULLS LAST 兜底极端情况。

    ★ 必须两阶段更新，不能用单条 UPDATE ... FROM 原地重排：
      thread_events 上有 UNIQUE(thread_id, chapter_no)，PostgreSQL 的唯一约束
      是「逐行立即检查」而非语句末检查。原地把 1,2,3... 改成 3,2,1 时，
      中间态必然出现同一 (thread_id, no) 被两行同时持有 → UniqueViolation。
      实测 37 条线中 27 条因此失败。
      阶段一先把该线全部置 NULL（NULL 不参与唯一约束，多行 NULL 合法），
      阶段二再从 NULL 逐个赋 1..N，新值互不相同，不再冲突。

    ★ 幂等：整线全量重排，重复执行结果一致；返回赋值的章节数。

    ★ 只动 core/context，noise 保持 NULL（与 chapter_seq 的口径一致）。
    """
    clear_sql = text("""
        UPDATE thread_events
        SET chapter_no = NULL
        WHERE thread_id = :tid
          AND COALESCE(role, 'core') <> 'noise'
          AND chapter_no IS NOT NULL
    """)
    assign_sql = text("""
        UPDATE thread_events te
        SET chapter_no = r.no
        FROM (
            SELECT chapter_id,
                   ROW_NUMBER() OVER (
                       ORDER BY COALESCE(occurred_at, created_at) ASC NULLS LAST,
                                created_at ASC,
                                chapter_id ASC
                   ) AS no
            FROM thread_events
            WHERE thread_id = :tid
              AND COALESCE(role, 'core') <> 'noise'
        ) r
        WHERE te.chapter_id = r.chapter_id
    """)
    owns = session is None
    if owns:
        async with async_session() as session:
            await session.execute(clear_sql, {"tid": thread_id})
            res = await session.execute(assign_sql, {"tid": thread_id})
            await session.commit()
            return res.rowcount or 0
    await session.execute(clear_sql, {"tid": thread_id})
    res = await session.execute(assign_sql, {"tid": thread_id})
    return res.rowcount or 0


async def renumber_all_threads() -> dict:
    """全量重排所有线的章节号，供定时任务与一次性回填调用。

    逐线单独事务：单线失败不影响其余线，失败数计入 errors。
    """
    async with async_session() as session:
        ids = (await session.execute(
            text("SELECT id FROM threads ORDER BY created_at")
        )).scalars().all()

    updated = 0
    errors = 0
    for tid in ids:
        try:
            updated += await renumber_thread_chapters(tid)
        except Exception as e:  # noqa: BLE001  单线失败不阻断全局
            errors += 1
            logger.warning("renumber failed for thread %s: %s", tid, e)
    logger.info(
        "chapter renumber finished: threads=%d, chapters_updated=%d, errors=%d",
        len(ids), updated, errors,
    )
    return {"threads": len(ids), "chapters_updated": updated, "errors": errors}
