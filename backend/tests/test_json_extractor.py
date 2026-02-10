"""Tests for app.utils.json_extractor — LLM response JSON extraction."""

from app.utils.json_extractor import extract_json_from_deepseek


class TestExtractJsonFromDeepseek:
    """Cover the three extraction strategies: direct, regex fallback, failure."""

    def test_clean_json_array(self):
        raw = '[{"id": 1, "score": 8}]'
        result = extract_json_from_deepseek(raw)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["score"] == 8

    def test_clean_json_object(self):
        raw = '{"key": "value"}'
        result = extract_json_from_deepseek(raw)
        assert isinstance(result, dict)
        assert result["key"] == "value"

    def test_think_tags_stripped(self):
        raw = (
            "<think>Let me analyze this...</think>\n"
            '[{"id": 1, "score": 9}]'
        )
        result = extract_json_from_deepseek(raw)
        assert isinstance(result, list)
        assert result[0]["score"] == 9

    def test_markdown_fence_stripped(self):
        raw = '```json\n[{"id": 1, "score": 7}]\n```'
        result = extract_json_from_deepseek(raw)
        assert isinstance(result, list)
        assert result[0]["score"] == 7

    def test_think_plus_fence_plus_filler(self):
        raw = (
            "<think>\nReasoning here.\n</think>\n\n"
            "Here is my analysis:\n\n"
            "```json\n"
            '[{"id": 1, "score": 9, "chinese_title": "测试"}]\n'
            "```\n\n"
            "That's my response."
        )
        result = extract_json_from_deepseek(raw)
        assert isinstance(result, list)
        assert result[0]["chinese_title"] == "测试"

    def test_filler_text_around_json(self):
        raw = "Sure! Here is the result:\n[{\"id\": 1, \"score\": 5}]\nHope this helps!"
        result = extract_json_from_deepseek(raw)
        assert isinstance(result, list)
        assert result[0]["id"] == 1

    def test_broken_response_returns_none(self):
        raw = "<think>thinking...</think>\nHere is my analysis: not valid json at all"
        result = extract_json_from_deepseek(raw)
        assert result is None

    def test_empty_string_returns_none(self):
        result = extract_json_from_deepseek("")
        assert result is None

    def test_nested_json(self):
        raw = '[{"id": 1, "data": {"nested": true}}]'
        result = extract_json_from_deepseek(raw)
        assert isinstance(result, list)
        assert result[0]["data"]["nested"] is True

    def test_multiple_think_blocks(self):
        raw = (
            "<think>first thought</think>\n"
            "<think>second thought</think>\n"
            '[{"id": 1, "score": 6}]'
        )
        result = extract_json_from_deepseek(raw)
        assert isinstance(result, list)
        assert len(result) == 1
