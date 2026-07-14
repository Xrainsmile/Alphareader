"""投资策略配置中心 — 策略画像、基准指数、规则版本。

本文件是 PRD「策略配置表」的代码侧实现（MVP 阶段以代码配置为主，
后续可平移为数据库 strategy_config 表 + 版本管理）。

当前 VCP 实装，其余策略（右侧趋势 / 催化剂 / 价投 / 模拟仓）仅预留配置结构，
前端据此渲染「即将上线」状态，禁止空白页。

规则版本（RULE_VERSION）随阈值/权重调整而递增，用于结果可追溯：
同一 (market, strategy, trade_date, rule_version) 下计算结果必须完全一致。
"""

from __future__ import annotations

from datetime import date

# ───────────────────────────────────────────────────────────
# 规则版本：任何阈值 / 权重 / 文案变更都必须 +1，以便历史结果可回溯
# ───────────────────────────────────────────────────────────
RULE_VERSION = "vcp-mvp-1"

# 适配度三档（70-100 适合关注 / 45-69 中性观察 / 0-44 谨慎参与）
LEVEL_FAVORABLE = "favorable"   # 适合关注
LEVEL_NEUTRAL = "neutral"       # 中性观察
LEVEL_CAUTIOUS = "cautious"     # 谨慎参与

LEVEL_LABELS = {
    LEVEL_FAVORABLE: "适合关注",
    LEVEL_NEUTRAL: "中性观察",
    LEVEL_CAUTIOUS: "谨慎参与",
}

# 维度 key → 中文名 / 权重 / 满分
VCP_DIMENSIONS = [
    {"key": "trend", "name": "大盘趋势", "weight": 25, "max": 25},
    {"key": "breadth", "name": "市场宽度", "weight": 20, "max": 20},
    {"key": "volatility", "name": "波动环境", "weight": 20, "max": 20},
    {"key": "breakout", "name": "突破有效性", "weight": 25, "max": 25},
    {"key": "activity", "name": "交易活跃度", "weight": 10, "max": 10},
]


def level_from_score(total_score: float) -> str:
    """根据内部 0-100 分映射到三档等级。"""
    if total_score >= 70:
        return LEVEL_FAVORABLE
    if total_score >= 45:
        return LEVEL_NEUTRAL
    return LEVEL_CAUTIOUS


# ───────────────────────────────────────────────────────────
# 基准指数定义
#   A 股默认沪深 300（akshare 代码 000300），可切换中证 1000（000852）
#   美股默认标普 500（yfinance ^GSPC），可切换纳斯达克（^IXIC）
# ───────────────────────────────────────────────────────────
BENCHMARK_INDEX = {
    "CN": {"primary": "000300", "alternatives": ["000852"], "name": "沪深300"},
    "US": {"primary": "^GSPC", "alternatives": ["^IXIC"], "name": "标普500"},
}


# ───────────────────────────────────────────────────────────
# 策略画像（PRD 13 文案示例 + 5.2 模块要求）
# ───────────────────────────────────────────────────────────
STRATEGY_PROFILES: dict[str, dict] = {
    "vcp": {
        "id": "vcp",
        "name": "VCP 波动收缩策略",
        "enabled": True,
        "type": "趋势动量 / 形态突破",
        "target": "寻找趋势向上、波动逐步收窄且接近关键突破位置的股票。",
        "suitable_market": "适合市场趋势稳定、波动适中、突破延续性较好的阶段。",
        "typical_cycle": "中线（数周至数月），等待波动收缩后的突破确认。",
        "core_signals": [
            "价格波动逐级收窄（VCP 收缩）",
            "中期趋势向上（价格位于 20/60 日均线上方）",
            "成交量在收缩末端下降、突破时放大",
            "接近或站上枢轴高位（pivot high）",
        ],
        "risk_hints": [
            "形态风险：收缩不完整或假突破，需以量价确认过滤。",
            "市场风险：大盘趋势破坏或波动骤升时，突破失败率上升。",
            "数据风险：样本不足时信号参考价值下降，仅作辅助。",
        ],
    },
    # ── 以下为预留结构，enabled=False 时前端渲染「即将上线」──
    "trend": {
        "id": "trend",
        "name": "右侧趋势策略",
        "enabled": False,
        "coming_soon": True,
        "target": "捕捉已确立上升趋势、回踩确认的板块龙头。",
        "core_signals": ["中期均线多头排列", "ADX 强势", "放量突破后缩量回踩"],
    },
    "catalyst": {
        "id": "catalyst",
        "name": "催化剂策略",
        "enabled": False,
        "coming_soon": True,
        "target": "事件驱动：新闻/财报/政策催化与基本面、技术面共振。",
        "core_signals": ["高分新闻命中", "产业链受益映射", "量价异动"],
    },
    "value": {
        "id": "value",
        "name": "价投策略",
        "enabled": False,
        "coming_soon": True,
        "target": "低估价值挖掘：稳健现金流与合理估值下的长期布局。",
        "core_signals": ["低估值分位", "盈利质量稳定", "分红/回购支撑"],
    },
    "sandbox": {
        "id": "sandbox",
        "name": "模拟仓",
        "enabled": True,  # 模拟仓本身可用，但不参与市场适配度
        "no_adaptability": True,
        "target": "组合管理与策略回测的沙盒环境。",
    },
    # RS Rating 当前前端隐藏，仅作兼容占位（coming_soon 避免 404）
    "rs": {
        "id": "rs",
        "name": "RS 强度",
        "enabled": False,
        "coming_soon": True,
        "target": "个股相对强度排行（IBD/Minervini 方法）。",
    },
}


def get_strategy_profile(strategy_id: str) -> dict | None:
    """返回策略画像；不存在返回 None。"""
    return STRATEGY_PROFILES.get(strategy_id)


def list_strategies(market: str = "CN") -> list[dict]:
    """返回策略列表（含状态），用于顶部导航与策略列表接口。

    顺序即为导航展示顺序；sandbox 始终置底。
    """
    order = ["vcp", "trend", "catalyst", "value", "sandbox"]
    result = []
    for sid in order:
        prof = STRATEGY_PROFILES.get(sid)
        if prof is None:
            continue
        result.append({
            "id": prof["id"],
            "name": prof["name"],
            "enabled": prof.get("enabled", False),
            "coming_soon": prof.get("coming_soon", False),
            "no_adaptability": prof.get("no_adaptability", False),
        })
    return result
