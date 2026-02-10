"""Mock DeepSeek API response pool.

Contains realistic "dirty" LLM outputs that exercise every edge case in the
JSON extraction and parsing pipeline:

  - <think> reasoning blocks (DeepSeek R1)
  - Markdown ```json``` code fences
  - Mixed: think + fence + filler text before/after
  - Dict wrappers: {"results": [...]}
  - Unicode-heavy Chinese content
  - English news with chinese_title / chinese_summary
  - Edge scores (0, 6, 10, 11 capped to 10)

Each entry is a tuple of (description, raw_llm_text, expected_item_count).
"""

# ═════════════════════════════════════════════════════════════
# Chinese news mock responses
# ═════════════════════════════════════════════════════════════

CN_MOCK_PURE_JSON = (
    "纯净 JSON，无任何包装",
    '[{"id": 1, "score": 9, "reason": "含具体营收数据，对A股光伏板块有直接影响", '
    '"summary": "隆基绿能发布年报，营收1200亿元同比增长28%", '
    '"tags": ["光伏", "新能源"]}, '
    '{"id": 2, "score": 3, "reason": "无实质数据的评论文章", '
    '"summary": "专家看好新能源未来发展", "tags": ["新能源"]}, '
    '{"id": 3, "score": 8, "reason": "央行重大政策变动", '
    '"summary": "央行宣布降准0.5个百分点释放长期资金约1万亿元", '
    '"tags": ["货币政策", "宏观"]}]',
    3,  # 3 items in the array (but only score >= 6 pass threshold)
)

CN_MOCK_THINK_ONLY = (
    "<think> 标签 + 纯 JSON",
    """<think>
让我逐条分析这些新闻：
第1条是宁德时代的财报，包含具体数据——营收、净利、增长率，非常有价值。打9分。
第2条是某明星代言新能源汽车，属于娱乐软文，打1分。
第3条是美联储议息会议结果，重大宏观事件，打8分。
</think>
[{"id": 1, "score": 9, "reason": "含详细财务数据：营收3562亿，净利润441亿，同比+22%", "summary": "宁德时代2025年营收3562亿元净利润441亿元同比增长22%", "tags": ["锂电池", "新能源", "财报"]},
{"id": 2, "score": 1, "reason": "明星代言属于娱乐软文无实质信息", "summary": "某流量明星成为某新能源品牌代言人", "tags": ["新能源汽车"]},
{"id": 3, "score": 8, "reason": "美联储降息25bp属于重大宏观事件", "summary": "美联储宣布降息25个基点联邦基金利率降至4.25%-4.50%", "tags": ["美联储", "货币政策", "宏观"]}]""",
    3,
)

CN_MOCK_MARKDOWN_FENCE = (
    "Markdown 代码块包裹",
    """```json
[
  {"id": 1, "score": 7, "reason": "行业政策变动", "summary": "工信部发布智能网联汽车标准体系指南", "tags": ["智能汽车", "政策"]},
  {"id": 2, "score": 9, "reason": "包含具体财务数据和重大人事变动", "summary": "比亚迪Q3营收2011亿元同比增长38%净利润116亿元", "tags": ["新能源汽车", "财报"]},
  {"id": 3, "score": 2, "reason": "推广软文", "summary": "某券商推荐关注半导体板块", "tags": ["半导体"]}
]
```""",
    3,
)

CN_MOCK_THINK_FENCE_FILLER = (
    "<think> + Markdown 代码块 + 前后废话（最复杂场景）",
    """<think>
好的，让我仔细分析用户给出的这5条新闻：

第1条：隆基绿能的产能扩张计划，包含具体投资金额和产能数据，有价值。
第2条：某分析师的口头看法，无具体数据支撑，低价值。
第3条：中国CPI数据，重要宏观指标。
第4条：某网红直播卖理财产品，属于软广告。
第5条：港交所上市新规修订，对港股市场结构有影响。

让我给出评分和摘要。
</think>

好的，以下是我对这批新闻的评估结果：

```json
[
  {"id": 1, "score": 8, "reason": "包含具体投资金额45亿和产能数据20GW", "summary": "隆基绿能计划投资45亿元建设20GW单晶硅片产能", "tags": ["光伏", "新能源"]},
  {"id": 2, "score": 2, "reason": "分析师个人观点无数据支撑", "summary": "某分析师表示看好A股后市", "tags": ["市场观点"]},
  {"id": 3, "score": 9, "reason": "核心宏观经济指标发布", "summary": "中国1月CPI同比上涨0.5%PPI同比下降2.3%低于市场预期", "tags": ["CPI", "宏观经济"]},
  {"id": 4, "score": 0, "reason": "网红推广内容无实质金融信息", "summary": "某网红直播推荐理财产品", "tags": []},
  {"id": 5, "score": 7, "reason": "交易所制度变革对市场结构有影响", "summary": "港交所修订上市规则降低科技企业上市门槛", "tags": ["港股", "IPO", "政策"]}
]
```

以上就是我的分析结果，希望对您有帮助。如有疑问请随时提出。""",
    5,
)

CN_MOCK_DICT_WRAPPER = (
    "JSON 被 dict wrapper 包裹 {'results': [...]}",
    """<think>分析完毕</think>
{"results": [
  {"id": 1, "score": 8, "reason": "重大并购事件", "summary": "中芯国际拟收购某半导体设备公司交易金额约50亿元", "tags": ["半导体", "并购"]},
  {"id": 2, "score": 6, "reason": "有一定参考价值的数据", "summary": "沪深两市成交额突破1.5万亿元创近期新高", "tags": ["市场情绪"]}
]}""",
    2,
)


# ═════════════════════════════════════════════════════════════
# English news mock responses
# ═════════════════════════════════════════════════════════════

EN_MOCK_PURE_JSON = (
    "英文新闻 — 纯净 JSON",
    '[{"id": 1, "score": 9, "chinese_title": "英伟达第四季度财报大幅超预期", '
    '"chinese_summary": "英伟达公布第四季度营收393亿美元，同比增长78%，数据中心业务营收同比增长93%", '
    '"tags": ["半导体", "人工智能"], "relevant_tickers": ["NVDA"]}, '
    '{"id": 2, "score": 7, "chinese_title": "特斯拉上海工厂产能创新高", '
    '"chinese_summary": "特斯拉上海超级工厂月产量突破10万辆创历史新纪录", '
    '"tags": ["新能源汽车"], "relevant_tickers": ["TSLA"]}]',
    2,
)

EN_MOCK_THINK_FENCE_FILLER = (
    "英文新闻 — <think> + 代码块 + 前后废话",
    """<think>
Let me analyze these English financial news articles:

1. The first one is about Apple's quarterly earnings - very significant with concrete revenue data.
2. The second is about Fed minutes - important macro event.
3. The third is a minor executive appointment at a small company - low relevance.

I need to provide Chinese translations for all titles and summaries.
</think>

Here are the scoring results for the batch:

```json
[
  {
    "id": 1,
    "score": 9,
    "chinese_title": "苹果公司第一财季营收创历史新高",
    "chinese_summary": "苹果公布第一财季营收1240亿美元，同比增长4%，每股收益2.40美元超出华尔街预期",
    "tags": ["科技", "消费电子", "财报"],
    "relevant_tickers": ["AAPL"]
  },
  {
    "id": 2,
    "score": 8,
    "chinese_title": "美联储会议纪要显示鹰派立场",
    "chinese_summary": "美联储最新会议纪要显示多数委员支持维持高利率更长时间以抑制通胀",
    "tags": ["美联储", "货币政策", "宏观"],
    "relevant_tickers": []
  },
  {
    "id": 3,
    "score": 2,
    "chinese_title": "某小型科技公司任命新首席财务官",
    "chinese_summary": "一家市值不足10亿美元的科技公司宣布新的首席财务官人选",
    "tags": ["科技"],
    "relevant_tickers": []
  }
]
```

That concludes my analysis of this batch.""",
    3,
)

EN_MOCK_EDGE_SCORES = (
    "英文新闻 — 边界分数测试（0, 6, 10, 超过10 capped）",
    """<think>Scoring edge cases</think>
[
  {"id": 1, "score": 0, "chinese_title": "某公司发布无关公告", "chinese_summary": "无关紧要的公告", "tags": [], "relevant_tickers": []},
  {"id": 2, "score": 6, "chinese_title": "高盛上调中国经济增长预期", "chinese_summary": "高盛将中国2026年经济增长预期从4.5%上调至5.0%", "tags": ["宏观", "中国经济"], "relevant_tickers": []},
  {"id": 3, "score": 10, "chinese_title": "摩根大通发布重磅研报", "chinese_summary": "摩根大通将半导体行业评级上调至超配预计未来12个月涨幅达30%", "tags": ["半导体"], "relevant_tickers": ["INTC", "TSM"]},
  {"id": 4, "score": 11, "chinese_title": "亚马逊云计算业务强劲增长", "chinese_summary": "亚马逊云计算部门营收同比增长35%超出市场预期", "tags": ["云计算"], "relevant_tickers": ["AMZN"]}
]""",
    4,
)

EN_MOCK_MULTIPLE_THINK_BLOCKS = (
    "英文新闻 — 多个 <think> 块穿插",
    """<think>
First, let me understand the context of each article.
Article 1 is about semiconductor export controls.
</think>

<think>
Article 2 is about oil prices. Let me check the relevance to Chinese markets...
Yes, oil price movements affect PetroChina, CNOOC, etc.
</think>

[{"id": 1, "score": 8, "chinese_title": "美国扩大对华半导体出口管制", "chinese_summary": "美国商务部宣布将新增12家中国半导体企业列入实体清单限制先进制程设备出口", "tags": ["半导体", "中美关系", "政策"], "relevant_tickers": ["ASML", "LRCX"]},
{"id": 2, "score": 7, "chinese_title": "国际油价突破每桶90美元", "chinese_summary": "布伦特原油期货价格涨至每桶91.5美元为近三个月最高受中东局势紧张影响", "tags": ["能源", "大宗商品"], "relevant_tickers": ["USO"]}]""",
    2,
)


# ═════════════════════════════════════════════════════════════
# Aggregated pools
# ═════════════════════════════════════════════════════════════

CN_MOCK_POOL: list[tuple[str, str, int]] = [
    CN_MOCK_PURE_JSON,
    CN_MOCK_THINK_ONLY,
    CN_MOCK_MARKDOWN_FENCE,
    CN_MOCK_THINK_FENCE_FILLER,
    CN_MOCK_DICT_WRAPPER,
]

EN_MOCK_POOL: list[tuple[str, str, int]] = [
    EN_MOCK_PURE_JSON,
    EN_MOCK_THINK_FENCE_FILLER,
    EN_MOCK_EDGE_SCORES,
    EN_MOCK_MULTIPLE_THINK_BLOCKS,
]

ALL_MOCK_POOL: list[tuple[str, str, int]] = CN_MOCK_POOL + EN_MOCK_POOL
