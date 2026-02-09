"""Robust JSON extraction from LLM responses.

Handles DeepSeek R1 chain-of-thought (<think> tags), Markdown code fences,
and conversational filler text that wraps the actual JSON payload.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("alphareader.json_extractor")


def _clean_llm_output(raw_text: str) -> str:
    """Pre-clean LLM output before JSON extraction.

    Steps:
      1. Strip <think>...</think> reasoning blocks (DeepSeek R1).
      2. Strip Markdown code fences (```json ... ```).
      3. Locate outermost JSON brackets, discard surrounding filler.
    """
    text = raw_text.strip()

    # 1. Strip <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # 2. Extract content inside markdown code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # 3. Find first [ or { ... last ] or }
    first_bracket = -1
    last_bracket = -1
    for i, ch in enumerate(text):
        if ch in ("[", "{"):
            first_bracket = i
            break
    for i in range(len(text) - 1, -1, -1):
        if text[i] in ("]", "}"):
            last_bracket = i
            break

    if first_bracket != -1 and last_bracket > first_bracket:
        text = text[first_bracket : last_bracket + 1]

    return text


def extract_json_from_deepseek(raw_text: str) -> list[dict] | dict | None:
    """Extract JSON (array or object) from a DeepSeek LLM response.

    Pipeline:
      1. Clean output (strip <think>, markdown fences, filler).
      2. json.loads() on cleaned text.
      3. Fallback: greedy regex for [ ... ] on original text.
      4. Log raw response on total failure.

    Returns parsed JSON (list or dict), or None on failure.
    """
    cleaned = _clean_llm_output(raw_text)

    # Strategy 1: Direct parse on cleaned text
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.debug("Direct parse failed after cleaning: %s", e)

    # Strategy 2: Greedy regex for [ ... ] on ORIGINAL text
    bracket_match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if bracket_match:
        try:
            result = json.loads(bracket_match.group())
            return result
        except json.JSONDecodeError:
            pass

    # All strategies failed
    logger.error(
        "JSON extraction failed.\n"
        "── Cleaned text (%d chars) ──\n%s\n"
        "── Raw LLM response (%d chars) ──\n%s\n"
        "── End ──",
        len(cleaned),
        cleaned[:1500],
        len(raw_text),
        raw_text[:1500],
    )
    return None


if __name__ == "__main__":
    # ── Test with a realistic DeepSeek R1 response ──
    sample = """<think>
The user wants me to score financial news. Let me analyze each item carefully.
Item 1 is about NVIDIA earnings - very significant. Score 9.
Item 2 is a celebrity gossip piece - score 0.
</think>

```json
[
  {"id": 1, "score": 9, "chinese_title": "英伟达第三季度财报超预期", "chinese_summary": "英伟达营收350亿美元同比增长94%", "tags": ["半导体"], "relevant_tickers": ["NVDA"]},
  {"id": 2, "score": 0, "chinese_title": "某明星离婚", "chinese_summary": "娱乐新闻无金融影响", "tags": [], "relevant_tickers": []}
]
```

That's my analysis."""

    print("=" * 60)
    print("Test 1: <think> + markdown fence + filler text")
    print("=" * 60)
    result = extract_json_from_deepseek(sample)
    if result:
        print(f"✅ Parsed {len(result)} items:")
        for item in result:
            print(f"   [{item['id']}] score={item['score']} → {item.get('chinese_title', item.get('title', ''))}")
    else:
        print("❌ Failed to extract JSON")

    print()

    # ── Test with plain JSON (no wrapper) ──
    sample_clean = '[{"id": 1, "score": 7, "reason": "IPO data", "summary": "测试摘要", "tags": ["科技"]}]'
    print("=" * 60)
    print("Test 2: Clean JSON (no wrapper)")
    print("=" * 60)
    result2 = extract_json_from_deepseek(sample_clean)
    print(f"✅ Parsed: {result2}" if result2 else "❌ Failed")

    print()

    # ── Test with broken JSON ──
    sample_broken = "<think>thinking...</think>\nHere is my analysis: not valid json at all"
    print("=" * 60)
    print("Test 3: Broken response (should fail gracefully)")
    print("=" * 60)
    result3 = extract_json_from_deepseek(sample_broken)
    print(f"Result: {result3}  (expected: None)")
