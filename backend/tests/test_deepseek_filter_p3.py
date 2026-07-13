"""P3 自测：中英文 schema 对称 / 两阶段评分 / prompt 注入防护 / 原始顺序保留。

覆盖：
- P3 ①：中英文解析对称（中文有 summary+why_it_matters，英文有 reason）
- P3 ②：英文两阶段评分（先评分后翻译，低分不翻译）
- P3 ③：prompt 注入防护（安全声明存在）
- P3 ④：原始顺序保留（语言分组后仍按原始 index 排序）
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.deepseek_filter import (
    BatchResult,
    FilterResult,
    RawNewsItem,
    ScoredNewsItem,
    SYSTEM_PROMPT_CN,
    SYSTEM_PROMPT_EN,
    SYSTEM_PROMPT_EN_SCORE,
    SYSTEM_PROMPT_EN_TRANSLATE,
    _parse_response_detailed,
    _parse_translate_response,
    _score_en_two_stage,
    filter_batch_detailed,
    filter_news,
)


def _make_cn_item(i: int) -> RawNewsItem:
    return RawNewsItem(
        title=f"测试新闻{i}",
        url=f"https://example.com/cn/{i}",
        content=f"这是第{i}条中文新闻正文，内容充实。" * 3,
        source="财联社",
    )


def _make_en_item(i: int) -> RawNewsItem:
    return RawNewsItem(
        title=f"Test News {i}",
        url=f"https://example.com/en/{i}",
        content=f"This is content for news {i}, with enough text for analysis. " * 3,
        source="Reuters",
    )


# ═══════════════════════════════════════════════════════════════
# P3 ①：中英文 schema 对称
# ═══════════════════════════════════════════════════════════════

class TestSchemaSymmetry:
    """中英文解析后 ScoredNewsItem 字段对称。"""

    def test_cn_has_summary_and_why_it_matters(self):
        """中文新闻解析后 summary 和 why_it_matters 来自 LLM 输出（不再为空/复用 reason）。"""
        raw = json.dumps([{
            "id": 1, "score": 7, "is_highlight": False,
            "reason": "CPI数据发布",
            "summary": "国家统计局公布8月CPI同比上涨0.6%",
            "why_it_matters": "通胀温和回升，关注货币政策空间",
            "tags": ["宏观"], "relevant_tickers": [],
        }], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(raw, [_make_cn_item(1)], False)
        assert ok and len(scored) == 1
        si = scored[0]
        assert si.reason == "CPI数据发布"
        assert si.summary == "国家统计局公布8月CPI同比上涨0.6%"
        assert si.why_it_matters == "通胀温和回升，关注货币政策空间"
        assert si.chinese_title == ""  # 中文新闻不需要翻译标题

    def test_en_has_reason(self):
        """英文新闻解析后 reason 来自 LLM 输出（不再硬编码空）。"""
        raw = json.dumps([{
            "id": 1, "score": 8, "is_highlight": True,
            "reason": "业绩超预期且指引上调",
            "chinese_title": "英伟达Q3业绩指引大幅上调",
            "chinese_summary": "英伟达公布Q3营收350亿美元，同比增长94%",
            "tags": ["AI算力"], "relevant_tickers": ["NVDA"],
            "why_it_matters": "业绩超预期，关注AI算力产业链",
        }], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(raw, [_make_en_item(1)], True)
        assert ok and len(scored) == 1
        si = scored[0]
        assert si.reason == "业绩超预期且指引上调"
        assert si.summary == "英伟达公布Q3营收350亿美元，同比增长94%"
        assert si.why_it_matters == "业绩超预期，关注AI算力产业链"
        assert si.chinese_title == "英伟达Q3业绩指引大幅上调"

    def test_cn_missing_summary_defaults_empty(self):
        """中文新闻 LLM 未输出 summary 时安全降级为空（不崩溃）。"""
        raw = json.dumps([{
            "id": 1, "score": 7, "is_highlight": False,
            "reason": "ok", "tags": [], "relevant_tickers": [],
        }], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(raw, [_make_cn_item(1)], False)
        assert ok and len(scored) == 1
        assert scored[0].summary == ""
        assert scored[0].why_it_matters == ""

    def test_en_missing_reason_defaults_empty(self):
        """英文新闻 LLM 未输出 reason 时安全降级为空。"""
        raw = json.dumps([{
            "id": 1, "score": 7, "is_highlight": False,
            "chinese_title": "测试标题", "chinese_summary": "测试摘要",
            "tags": [], "relevant_tickers": [], "why_it_matters": "ok",
        }], ensure_ascii=False)
        scored, _, _, _, ok = _parse_response_detailed(raw, [_make_en_item(1)], True)
        assert ok and len(scored) == 1
        assert scored[0].reason == ""


# ═══════════════════════════════════════════════════════════════
# P3 ②：英文两阶段评分
# ═══════════════════════════════════════════════════════════════

class TestTwoStageScoring:
    """英文两阶段评分：先评分（不翻译），后翻译通过阈值的。"""

    def test_translate_response_parsing(self):
        """翻译阶段响应解析正确。"""
        raw = json.dumps([
            {"id": 1, "chinese_title": "英伟达业绩超预期",
             "chinese_summary": "英伟达Q3营收350亿美元同比增长94%",
             "why_it_matters": "关注AI算力"},
            {"id": 2, "chinese_title": "腾讯回购加码",
             "chinese_summary": "腾讯本周回购金额创新高",
             "why_it_matters": "支撑估值"},
        ], ensure_ascii=False)
        batch = [_make_en_item(1), _make_en_item(2)]
        translations = _parse_translate_response(raw, batch)
        assert len(translations) == 2
        assert translations[1]["chinese_title"] == "英伟达业绩超预期"
        assert translations[2]["why_it_matters"] == "支撑估值"

    def test_translate_response_chinese_ratio_check(self):
        """翻译阶段也做中文占比校验，纯英文标题被丢弃后从 summary 兜底。"""
        raw = json.dumps([
            {"id": 1, "chinese_title": "NVIDIA beats earnings",
             "chinese_summary": "英伟达Q3营收超预期",
             "why_it_matters": "关注AI"},
        ], ensure_ascii=False)
        batch = [_make_en_item(1)]
        translations = _parse_translate_response(raw, batch)
        # 纯英文标题被丢弃 → 从中文 summary 截前30字兜底
        assert "NVIDIA" not in translations[1]["chinese_title"]
        assert translations[1]["summary"] == "英伟达Q3营收超预期"

    @pytest.mark.asyncio
    async def test_two_stage_score_then_translate(self):
        """两阶段流程：阶段一评分，阶段二翻译，最终 ScoredNewsItem 有翻译字段。"""
        items = [_make_en_item(i) for i in range(1, 4)]

        call_count = {"score": 0, "translate": 0}

        async def fake_call(payload, headers, client):
            system_msg = payload["messages"][0]["content"]
            if "仅对每条新闻进行评分" in system_msg:
                # 阶段一：评分
                call_count["score"] += 1
                raw = json.dumps([
                    {"id": i, "score": 8, "is_highlight": False,
                     "reason": f"理由{i}", "tags": [], "relevant_tickers": []}
                    for i in range(1, 4)
                ], ensure_ascii=False)
                return raw, "ok", ""
            elif "精通中英双语金融翻译" in system_msg:
                # 阶段二：翻译
                call_count["translate"] += 1
                raw = json.dumps([
                    {"id": i, "chinese_title": f"中文标题{i}",
                     "chinese_summary": f"中文摘要{i}",
                     "why_it_matters": f"推荐理由{i}"}
                    for i in range(1, 4)
                ], ensure_ascii=False)
                return raw, "ok", ""
            return None, "api_error", "unknown prompt"

        mock_settings = MagicMock()
        mock_settings.SILICONFLOW_API_KEY = "k"
        mock_settings.SILICONFLOW_LLM_MODEL = "m"
        mock_settings.SILICONFLOW_API_URL = "http://mock"
        mock_settings.DEEPSEEK_BATCH_SIZE = 20
        mock_settings.DEEPSEEK_SCORE_THRESHOLD = 5
        mock_settings.DEEPSEEK_MAX_RETRIES = 2
        mock_settings.DEEPSEEK_CONTENT_PREVIEW_CHARS = 800
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_TITLE = 0.5
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY = 0.6
        mock_settings.DEEPSEEK_CONTENT_RISK_BISECT_ENABLED = True
        mock_settings.DEEPSEEK_CONTENT_RISK_MAX_DEPTH = 6
        mock_settings.DEEPSEEK_TWO_STAGE_EN_ENABLED = True
        mock_settings.DEEPSEEK_TRANSLATE_BATCH_SIZE = 20

        mock_client = MagicMock()

        with patch("app.services.deepseek_filter.settings", mock_settings), \
             patch("app.services.deepseek_filter._call_llm_once", side_effect=fake_call):
            result = await filter_batch_detailed(items, is_english=True, client=mock_client)

        assert call_count["score"] == 1
        assert call_count["translate"] == 1
        assert len(result.scored) == 3
        for si in result.scored:
            assert si.reason != ""  # 阶段一输出
            assert si.chinese_title != ""  # 阶段二输出
            assert si.summary != ""  # 阶段二输出
            assert si.why_it_matters != ""  # 阶段二输出

    @pytest.mark.asyncio
    async def test_two_stage_low_score_not_translated(self):
        """低分新闻不进入翻译阶段（节省 token）。"""
        items = [_make_en_item(i) for i in range(1, 5)]

        translate_input_items = {"titles": []}

        async def fake_call(payload, headers, client):
            system_msg = payload["messages"][0]["content"]
            if "仅对每条新闻进行评分" in system_msg:
                # 2条高分，2条低分
                raw = json.dumps([
                    {"id": 1, "score": 8, "is_highlight": False, "reason": "高", "tags": [], "relevant_tickers": []},
                    {"id": 2, "score": 3, "is_highlight": False, "reason": "低", "tags": [], "relevant_tickers": []},
                    {"id": 3, "score": 7, "is_highlight": False, "reason": "高", "tags": [], "relevant_tickers": []},
                    {"id": 4, "score": 2, "is_highlight": False, "reason": "低", "tags": [], "relevant_tickers": []},
                ], ensure_ascii=False)
                return raw, "ok", ""
            elif "精通中英双语金融翻译" in system_msg:
                # 翻译阶段只收到通过阈值的条目
                user_msg = payload["messages"][1]["content"]
                for title in ["Test News 1", "Test News 2", "Test News 3", "Test News 4"]:
                    if title in user_msg:
                        translate_input_items["titles"].append(title)
                raw = json.dumps([
                    {"id": 1, "chinese_title": "标题一", "chinese_summary": "摘要一", "why_it_matters": "理由一"},
                    {"id": 2, "chinese_title": "标题二", "chinese_summary": "摘要二", "why_it_matters": "理由二"},
                ], ensure_ascii=False)
                return raw, "ok", ""
            return None, "api_error", "unknown"

        mock_settings = MagicMock()
        mock_settings.SILICONFLOW_API_KEY = "k"
        mock_settings.SILICONFLOW_LLM_MODEL = "m"
        mock_settings.SILICONFLOW_API_URL = "http://mock"
        mock_settings.DEEPSEEK_BATCH_SIZE = 20
        mock_settings.DEEPSEEK_SCORE_THRESHOLD = 5
        mock_settings.DEEPSEEK_MAX_RETRIES = 2
        mock_settings.DEEPSEEK_CONTENT_PREVIEW_CHARS = 800
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_TITLE = 0.5
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY = 0.6
        mock_settings.DEEPSEEK_CONTENT_RISK_BISECT_ENABLED = True
        mock_settings.DEEPSEEK_CONTENT_RISK_MAX_DEPTH = 6
        mock_settings.DEEPSEEK_TWO_STAGE_EN_ENABLED = True
        mock_settings.DEEPSEEK_TRANSLATE_BATCH_SIZE = 20

        mock_client = MagicMock()

        with patch("app.services.deepseek_filter.settings", mock_settings), \
             patch("app.services.deepseek_filter._call_llm_once", side_effect=fake_call):
            result = await filter_batch_detailed(items, is_english=True, client=mock_client)

        # 只有2条通过阈值 → 翻译阶段只翻译2条
        assert len(result.scored) == 2
        # 翻译输入只包含高分条目（Test News 1 和 Test News 3）
        assert "Test News 1" in translate_input_items["titles"]
        assert "Test News 3" in translate_input_items["titles"]
        assert "Test News 2" not in translate_input_items["titles"]
        assert "Test News 4" not in translate_input_items["titles"]

    @pytest.mark.asyncio
    async def test_two_stage_translate_failure_keeps_score(self):
        """翻译阶段失败时，评分结果仍保留（只是没有翻译字段）。"""
        items = [_make_en_item(i) for i in range(1, 3)]

        async def fake_call(payload, headers, client):
            system_msg = payload["messages"][0]["content"]
            if "仅对每条新闻进行评分" in system_msg:
                raw = json.dumps([
                    {"id": i, "score": 8, "is_highlight": False, "reason": "ok", "tags": [], "relevant_tickers": []}
                    for i in range(1, 3)
                ], ensure_ascii=False)
                return raw, "ok", ""
            elif "精通中英双语金融翻译" in system_msg:
                return None, "api_error", "translate failed"
            return None, "api_error", "unknown"

        mock_settings = MagicMock()
        mock_settings.SILICONFLOW_API_KEY = "k"
        mock_settings.SILICONFLOW_LLM_MODEL = "m"
        mock_settings.SILICONFLOW_API_URL = "http://mock"
        mock_settings.DEEPSEEK_BATCH_SIZE = 20
        mock_settings.DEEPSEEK_SCORE_THRESHOLD = 5
        mock_settings.DEEPSEEK_MAX_RETRIES = 2
        mock_settings.DEEPSEEK_CONTENT_PREVIEW_CHARS = 800
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_TITLE = 0.5
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY = 0.6
        mock_settings.DEEPSEEK_CONTENT_RISK_BISECT_ENABLED = True
        mock_settings.DEEPSEEK_CONTENT_RISK_MAX_DEPTH = 6
        mock_settings.DEEPSEEK_TWO_STAGE_EN_ENABLED = True
        mock_settings.DEEPSEEK_TRANSLATE_BATCH_SIZE = 20

        mock_client = MagicMock()

        with patch("app.services.deepseek_filter.settings", mock_settings), \
             patch("app.services.deepseek_filter._call_llm_once", side_effect=fake_call):
            result = await filter_batch_detailed(items, is_english=True, client=mock_client)

        assert len(result.scored) == 2
        for si in result.scored:
            assert si.score == 8  # 评分保留
            assert si.reason == "ok"  # reason 保留
            assert si.chinese_title == ""  # 翻译失败，无翻译
            assert si.summary == ""

    @pytest.mark.asyncio
    async def test_two_stage_disabled_uses_single_stage(self):
        """DEEPSEEK_TWO_STAGE_EN_ENABLED=False 时走单阶段（SYSTEM_PROMPT_EN）。"""
        items = [_make_en_item(1)]

        call_count = {"n": 0}

        async def fake_call(payload, headers, client):
            call_count["n"] += 1
            system_msg = payload["messages"][0]["content"]
            # 单阶段 prompt 包含"每条新闻都必须翻译"
            assert "每条新闻都必须翻译" in system_msg
            raw = json.dumps([{
                "id": 1, "score": 8, "is_highlight": False, "reason": "ok",
                "chinese_title": "测试标题", "chinese_summary": "测试摘要",
                "tags": [], "relevant_tickers": [], "why_it_matters": "理由",
            }], ensure_ascii=False)
            return raw, "ok", ""

        mock_settings = MagicMock()
        mock_settings.SILICONFLOW_API_KEY = "k"
        mock_settings.SILICONFLOW_LLM_MODEL = "m"
        mock_settings.SILICONFLOW_API_URL = "http://mock"
        mock_settings.DEEPSEEK_BATCH_SIZE = 20
        mock_settings.DEEPSEEK_SCORE_THRESHOLD = 5
        mock_settings.DEEPSEEK_MAX_RETRIES = 2
        mock_settings.DEEPSEEK_CONTENT_PREVIEW_CHARS = 800
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_TITLE = 0.5
        mock_settings.DEEPSEEK_MIN_CHINESE_RATIO_SUMMARY = 0.6
        mock_settings.DEEPSEEK_CONTENT_RISK_BISECT_ENABLED = True
        mock_settings.DEEPSEEK_CONTENT_RISK_MAX_DEPTH = 6
        mock_settings.DEEPSEEK_TWO_STAGE_EN_ENABLED = False  # 关闭两阶段
        mock_settings.DEEPSEEK_TRANSLATE_BATCH_SIZE = 20

        mock_client = MagicMock()

        with patch("app.services.deepseek_filter.settings", mock_settings), \
             patch("app.services.deepseek_filter._call_llm_once", side_effect=fake_call):
            result = await filter_batch_detailed(items, is_english=True, client=mock_client)

        assert call_count["n"] == 1  # 只调1次（单阶段）
        assert len(result.scored) == 1


# ═══════════════════════════════════════════════════════════════
# P3 ③：prompt 注入防护
# ═══════════════════════════════════════════════════════════════

class TestPromptInjectionGuard:
    """所有 system prompt 包含安全声明。"""

    def test_cn_prompt_has_safety_declaration(self):
        assert "不可信待分析数据" in SYSTEM_PROMPT_CN
        assert "忽略" in SYSTEM_PROMPT_CN or "绝不可作为" in SYSTEM_PROMPT_CN

    def test_en_prompt_has_safety_declaration(self):
        assert "不可信待分析数据" in SYSTEM_PROMPT_EN

    def test_en_score_prompt_has_safety_declaration(self):
        assert "不可信待分析数据" in SYSTEM_PROMPT_EN_SCORE

    def test_en_translate_prompt_has_safety_declaration(self):
        assert "不可信待分析数据" in SYSTEM_PROMPT_EN_TRANSLATE


# ═══════════════════════════════════════════════════════════════
# P3 ④：原始顺序保留
# ═══════════════════════════════════════════════════════════════

class TestOriginalOrderPreservation:
    """filter_news 输出按原始输入顺序排序，而非"中文全在前英文全在后"。"""

    @pytest.mark.asyncio
    async def test_order_preserved_after_language_split(self):
        """中英文混合输入 → 输出顺序与输入顺序一致。"""
        # 交替排列：中文1, 英文1, 中文2, 英文2, 中文3
        items = [
            _make_cn_item(1),
            _make_en_item(1),
            _make_cn_item(2),
            _make_en_item(2),
            _make_cn_item(3),
        ]

        async def fake_filter_batch_detailed(batch, is_english, client, **kwargs):
            scored = []
            for it in batch:
                scored.append(ScoredNewsItem(
                    raw=it, score=7, reason="ok", summary="摘要",
                    tags=[], relevant_tickers=[], why_it_matters="理由",
                    chinese_title="翻译标题" if is_english else "",
                ))
            return BatchResult(scored=scored, status="ok",
                               processed_ids=set(range(1, len(batch) + 1)))

        with patch("app.services.deepseek_filter.filter_batch_detailed",
                    side_effect=fake_filter_batch_detailed):
            result = await filter_news(items)

        assert len(result.scored) == 5
        # 验证顺序：原始 index 0,1,2,3,4
        assert result.scored[0].raw.title == "测试新闻1"
        assert result.scored[1].raw.title == "Test News 1"
        assert result.scored[2].raw.title == "测试新闻2"
        assert result.scored[3].raw.title == "Test News 2"
        assert result.scored[4].raw.title == "测试新闻3"

    @pytest.mark.asyncio
    async def test_order_preserved_all_english_then_chinese_input(self):
        """输入顺序为"全英文后全中文"时，输出也保持该顺序（非中文优先）。"""
        items = [
            _make_en_item(1),
            _make_en_item(2),
            _make_cn_item(1),
            _make_cn_item(2),
        ]

        async def fake_filter_batch_detailed(batch, is_english, client, **kwargs):
            scored = [
                ScoredNewsItem(raw=it, score=7, reason="ok", summary="s",
                               tags=[], why_it_matters="w")
                for it in batch
            ]
            return BatchResult(scored=scored, status="ok",
                               processed_ids=set(range(1, len(batch) + 1)))

        with patch("app.services.deepseek_filter.filter_batch_detailed",
                    side_effect=fake_filter_batch_detailed):
            result = await filter_news(items)

        assert len(result.scored) == 4
        # 原始顺序：en1, en2, cn1, cn2
        assert "Test News 1" == result.scored[0].raw.title
        assert "Test News 2" == result.scored[1].raw.title
        assert "测试新闻1" == result.scored[2].raw.title
        assert "测试新闻2" == result.scored[3].raw.title


# ═══════════════════════════════════════════════════════════════
# P3 ⑤：批次并发执行
# ═══════════════════════════════════════════════════════════════

class TestConcurrentBatching:
    """filter_news 的批次并发执行，而非串行。"""

    @pytest.mark.asyncio
    async def test_batches_run_concurrently(self):
        """多个 batch 并发执行：总耗时 ≈ 单批耗时（而非 N×单批）。"""
        import asyncio as _asyncio

        # 6 个中文条目 → batch_size=2 → 3 个 batch
        items = [_make_cn_item(i) for i in range(1, 7)]

        call_times: list[float] = []

        async def fake_filter_batch_detailed(batch, is_english, client, **kwargs):
            call_times.append(_asyncio.get_event_loop().time())
            # 模拟每批 0.3s 延迟
            await _asyncio.sleep(0.3)
            scored = [
                ScoredNewsItem(raw=it, score=7, reason="ok", summary="s",
                               tags=[], why_it_matters="w")
                for it in batch
            ]
            return BatchResult(scored=scored, status="ok",
                               processed_ids=set(range(1, len(batch) + 1)))

        with patch("app.services.deepseek_filter.filter_batch_detailed",
                    side_effect=fake_filter_batch_detailed), \
             patch("app.services.deepseek_filter.settings") as mock_s:
            mock_s.DEEPSEEK_BATCH_SIZE = 2
            mock_s.DEEPSEEK_MAX_CONCURRENCY = 3
            t0 = _asyncio.get_event_loop().time()
            result = await filter_news(items)
            elapsed = _asyncio.get_event_loop().time() - t0

        assert len(result.scored) == 6
        # 3 批并发（max_concurrency=3）→ 总耗时 ≈ 0.3s，而非 0.9s
        # 留余量：< 0.7s 说明确实并发了
        assert elapsed < 0.7, f"Expected concurrent (<0.7s), got {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_concurrency_limit_respected(self):
        """并发度限制生效：max_concurrency=1 时退化为串行。"""
        import asyncio as _asyncio

        items = [_make_cn_item(i) for i in range(1, 7)]

        active = {"n": 0, "max": 0}

        async def fake_filter_batch_detailed(batch, is_english, client, **kwargs):
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            await _asyncio.sleep(0.1)
            active["n"] -= 1
            scored = [
                ScoredNewsItem(raw=it, score=7, reason="ok", summary="s",
                               tags=[], why_it_matters="w")
                for it in batch
            ]
            return BatchResult(scored=scored, status="ok",
                               processed_ids=set(range(1, len(batch) + 1)))

        with patch("app.services.deepseek_filter.filter_batch_detailed",
                    side_effect=fake_filter_batch_detailed), \
             patch("app.services.deepseek_filter.settings") as mock_s:
            mock_s.DEEPSEEK_BATCH_SIZE = 2
            mock_s.DEEPSEEK_MAX_CONCURRENCY = 1
            await filter_news(items)

        # max_concurrency=1 → 同时最多 1 个 batch 在跑
        assert active["max"] == 1

    @pytest.mark.asyncio
    async def test_concurrency_3_allows_parallel(self):
        """并发度=3 时多个 batch 同时在跑。"""
        import asyncio as _asyncio

        items = [_make_cn_item(i) for i in range(1, 7)]

        active = {"n": 0, "max": 0}

        async def fake_filter_batch_detailed(batch, is_english, client, **kwargs):
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            await _asyncio.sleep(0.1)
            active["n"] -= 1
            scored = [
                ScoredNewsItem(raw=it, score=7, reason="ok", summary="s",
                               tags=[], why_it_matters="w")
                for it in batch
            ]
            return BatchResult(scored=scored, status="ok",
                               processed_ids=set(range(1, len(batch) + 1)))

        with patch("app.services.deepseek_filter.filter_batch_detailed",
                    side_effect=fake_filter_batch_detailed), \
             patch("app.services.deepseek_filter.settings") as mock_s:
            mock_s.DEEPSEEK_BATCH_SIZE = 2
            mock_s.DEEPSEEK_MAX_CONCURRENCY = 3
            await filter_news(items)

        # 3 批 max_concurrency=3 → 全部同时跑
        assert active["max"] == 3
