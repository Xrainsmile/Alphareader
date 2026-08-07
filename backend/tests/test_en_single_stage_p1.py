"""P1 英文单阶段实验：路由、prompt、解析单测。

注意：本文件只覆盖「代码正确性」（实验开关路由、单阶段 prompt 复用评分段、
单阶段 JSON 解析低分/高分分支），不覆盖 LLM 质量对比——后者由
scripts/ab_test_en_single_stage.py 用真实英文新闻做 A/B。
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.services import llm_news_filter as LNF
from app.services.llm_news_filter import (
    SYSTEM_PROMPT_EN_SINGLE,
    SYSTEM_PROMPT_EN_SCORE,
    BatchResult,
    ScoredNewsItem,
    _parse_response_detailed,
    filter_batch_detailed,
)
from app.services.rss_fetcher import RawNewsItem


def _mk_items(n=3):
    return [
        RawNewsItem(
            title=f"English headline number {i}",
            content="Some english content here for testing.",
            url=f"https://x/{i}", source="test",
            published_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )
        for i in range(1, n + 1)
    ]


def test_single_stage_prompt_reuses_score_rubric():
    """单阶段 prompt 必须复用两阶段阶段一的评分段，保证评分口径可比。"""
    p = SYSTEM_PROMPT_EN_SINGLE
    for frag in (
        "0—2：无有效事实",
        "5—6：宏观数据",
        "7—8：业绩超/不及预期",
        "9—10：重大政策转向",
        "超过7天且无新增事实最高4分",
    ):
        assert frag in p, frag
    # 单阶段自己会翻译，不应保留「不做翻译」的限制句
    assert "不做标题或摘要翻译" not in p
    # 条件输出规则
    assert "score < 6：id、score" in p
    assert "chinese_title" in p and "is_highlight" in p


def test_single_stage_prompt_score_head_matches_two_stage():
    """构造出的评分段应与 SYSTEM_PROMPT_EN_SCORE 的评分段逐字一致（除角色句外）。"""
    single_head = SYSTEM_PROMPT_EN_SINGLE.split("## 翻译")[0]
    score_head = SYSTEM_PROMPT_EN_SCORE.split("## 输出")[0]
    # 把单阶段被改写过的角色句还原回两阶段原句，应完全相等
    restored = single_head.replace(
        "你是财经新闻分析师兼中英金融翻译。评估每条英文新闻的投资参考价值，"
        "并（仅对 score>=6 的命中条目）生成简体中文标题、摘要与投资意义。",
        "你是财经新闻分析师。仅评估每条英文新闻的投资参考价值，不做标题或摘要翻译。",
    )
    assert restored.strip() == score_head.strip()


def test_experiment_flag_routes_to_single_stage(monkeypatch):
    called = {"single": False, "two": False}

    async def fake_single(batch, client):
        called["single"] = True
        return BatchResult(scored=[], status="ok")

    async def fake_two(batch, client):
        called["two"] = True
        return BatchResult(scored=[], status="ok")

    monkeypatch.setattr(LNF, "_score_en_single_stage", fake_single)
    monkeypatch.setattr(LNF, "_score_en_two_stage", fake_two)
    monkeypatch.setattr(LNF.settings, "LLM_EN_SINGLE_STAGE_EXPERIMENT", True)
    monkeypatch.setattr(LNF.settings, "LLM_TWO_STAGE_EN_ENABLED", True)
    monkeypatch.setattr(LNF.settings, "LLM_API_KEY", "x")
    asyncio.run(filter_batch_detailed(_mk_items(), is_english=True, client=AsyncMock()))
    assert called["single"] is True
    assert called["two"] is False


def test_two_stage_flag_routes_to_two_stage(monkeypatch):
    called = {"single": False, "two": False}

    async def fake_single(batch, client):
        called["single"] = True
        return BatchResult(scored=[], status="ok")

    async def fake_two(batch, client):
        called["two"] = True
        return BatchResult(scored=[], status="ok")

    monkeypatch.setattr(LNF, "_score_en_single_stage", fake_single)
    monkeypatch.setattr(LNF, "_score_en_two_stage", fake_two)
    monkeypatch.setattr(LNF.settings, "LLM_EN_SINGLE_STAGE_EXPERIMENT", False)
    monkeypatch.setattr(LNF.settings, "LLM_TWO_STAGE_EN_ENABLED", True)
    monkeypatch.setattr(LNF.settings, "LLM_API_KEY", "x")
    asyncio.run(filter_batch_detailed(_mk_items(), is_english=True, client=AsyncMock()))
    assert called["two"] is True
    assert called["single"] is False


def test_single_stage_parser_low_vs_high():
    """单阶段 JSON：<6 仅 id+score（无翻译）；>=6 全量字段。"""
    items = _mk_items(2)
    resp = [
        {"id": 1, "score": 5},  # <6：仅 id+score，不翻译
        {"id": 2, "score": 8, "chinese_title": "某公司营收超预期",
         "chinese_summary": "季度营收同比增长。", "why_it_matters": "利好盈利。",
         "tags": ["财报", "超预期"], "is_highlight": True},
    ]
    raw = json.dumps(resp)
    scored_list = _parse_response_detailed(raw, items, is_english=True)[0]
    by_id = {s.original_id: s for s in scored_list}
    assert 1 in by_id and 2 in by_id
    # 低分：无翻译字段
    assert by_id[1].score == 5
    assert by_id[1].chinese_title == ""
    assert by_id[1].is_highlight is False
    # 高分：完整字段
    assert by_id[2].score == 8
    assert by_id[2].chinese_title == "某公司营收超预期"
    assert by_id[2].summary == "季度营收同比增长。"
    assert by_id[2].why_it_matters == "利好盈利。"
    assert by_id[2].tags == ["财报", "超预期"]
    assert by_id[2].is_highlight is True
