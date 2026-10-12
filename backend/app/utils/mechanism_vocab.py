"""机制词表 —— 世界线 P1-b。

把 LLM 输出的自由文本机制提示归一为受控枚举，供 P1-c 归线算法的
「机制门控」使用。

设计要点：
1. 枚举封闭：LLM 只能从本表选，输出未知词一律丢弃（不落 unknown，
   而是直接不参与门控，见 §2.3 的 unknown 保留策略）。
2. unknown 的语义：mechanism_hints 为空数组 → 该事件对所有线「机制兼容」，
   而不是归到某条默认线。空 = 无约束，不等于某种机制。
3. 与 events.outcome_type（事件结局）、thread_transmissions.evidence_status
   （因果边可信度）三者完全不同义，不可复用。
"""

# 受控机制枚举。key 为落库值，value 为中文说明（供 prompt 与人工治理界面展示）。
MECHANISM_VOCAB: dict[str, str] = {
    # ── 地缘 / 军事 ──
    "military_conflict": "军事冲突",
    "military_control": "军事控制 / 占领",
    "territorial_dispute": "领土争端",
    "sanction": "制裁 / 出口管制",
    "blockade": "封锁 / 禁运",
    # ── 航运 / 供应链 ──
    "shipping_disruption": "航运中断",
    "supply_chain": "供应链扰动",
    "logistics_delay": "物流延误",
    # ── 价格 / 成本传导 ──
    "cost_passthrough": "成本传导",
    "price_shock": "价格冲击",
    "risk_premium": "风险溢价",
    "insurance_cost": "保险 / 费率成本",
    # ── 货币 / 金融 ──
    "monetary_policy": "货币政策",
    "fiscal_policy": "财政政策",
    "liquidity": "流动性",
    "credit_risk": "信用风险",
    "capital_flow": "资本流动",
    # ── 产业 / 公司 ──
    "capacity": "产能",
    "merger_acquisition": "并购重组",
    "regulation": "监管政策",
    "tech_disruption": "技术变革",
    "labor_action": "劳工行动",
    # ── 能源 / 商品 ──
    "energy_supply": "能源供给",
    "commodity_supply": "商品供给",
    # ── 政治 / 选举 ──
    "election": "选举 / 政权更替",
    "policy_shift": "政策转向",
    "diplomacy": "外交谈判",
}

# 单个事件最多保留的机制数（防止 LLM 把所有词都勾上，导致门控失效）
MAX_MECHANISMS = 4

# 争夺标的最大保留数
MAX_CONTESTED_ASSETS = 4

# 争夺标的单条最大长度（防 LLM 输出长句）
MAX_ASSET_LEN = 40


def normalize_mechanisms(raw: object) -> list[str]:
    """把 LLM 输出的 mechanism_hints 归一为受控枚举列表。

    - 非列表 / 空 → []（语义：不参与门控，对所有线兼容）
    - 未知词一律丢弃（不做模糊匹配，避免同义词各行其是）
    - 去重保序，截断到 MAX_MECHANISMS

    返回空列表不是错误，是「该事件未识别到机制」的正常表达。
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        key = item.strip().lower()
        if key in MECHANISM_VOCAB and key not in out:
            out.append(key)
        if len(out) >= MAX_MECHANISMS:
            break
    return out


def normalize_assets(raw: object) -> list[str]:
    """把 LLM 输出的 contested_assets 归一为字符串列表。

    - 非列表 / 空 → []
    - 去空白、截断长度、去重保序
    - 丢弃空串

    争夺标的是自由文本（曼德海峡 / 红海航线 / 台积电先进制程），
    不做枚举约束——枚举会限制表达，且这个字段主要用于展示与人工判断。
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip()[:MAX_ASSET_LEN].strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= MAX_CONTESTED_ASSETS:
            break
    return out


def mechanism_display(key: str) -> str:
    """枚举值 → 中文说明。未知 key 原样返回（不应发生，防御用）。"""
    return MECHANISM_VOCAB.get(key, key)
