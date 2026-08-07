"""英文两阶段 vs 单阶段 A/B 实验（P1）

目的
----
对比「当前两阶段（先评分后翻译，≥6 条目二次调用翻译）」与
「单阶段实验（一次调用完成评分 + 对 score>=6 条目条件翻译）」在
固定真实英文新闻上的表现与 token 成本，用于决定达标后是否切换。

运行方式（在 web 容器内，具备 DB 与 LLM API 密钥）：

    docker compose run --rm -w /app -e PYTHONPATH=/app \
        -v $(pwd)/scripts/ab_test_en_single_stage.py:/tmp/ab.py \
        web python /tmp/ab.py --limit 2000 --out /tmp/en_ab_result.json

真实数据来源（固定、可复现）：
    - 默认从生产库 news 表取 content 长度足够、按 id 升序的英文新闻；
    - 首次运行可用 --save-fixture 落盘为 JSON，之后用 --fixture 复用同一固定集合，
      保证多次实验使用完全相同的输入（LLM 非确定性仅影响输出，不影响输入分布）。

覆盖保证（关键）：
    LLM 常静默丢弃部分条目。为公平对比，两方法均对被丢弃条目做重试补全，
    使对比建立在「同一组条目」之上；覆盖率单独报告。

输出指标（对齐 P1 需求）：
    - score 一致率 / score 平均绝对差(MAE)
    - ≥6 分类一致率 / ≥8 分类一致率
    - highlight 一致率
    - 中文标题可用率 / 摘要可用率（单阶段 vs 两阶段，均基于各自 ≥6 集合）
    - JSON 解析失败率 / 覆盖率（missing id 率）
    - prompt / completion / total tokens（两方案汇总）

达标判据（脚本仅报告，切换由人工决定）：
    - ≥6 分类一致率 >= 95%
    - ≥8 分类一致率 >= 95%
    - 中文标题/摘要无明显质量退化（可用率不低于两阶段 -5pp）
    - JSON 失败率不高于当前两阶段方案
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx

# ── app 上下文 ──
sys.path.insert(0, "/app")
from app.config import settings  # noqa: E402
from app.services import llm_news_filter as LNF  # noqa: E402
from app.services.rss_fetcher import RawNewsItem  # noqa: E402
from app.services.llm_news_filter import (  # noqa: E402
    SYSTEM_PROMPT_EN_SCORE,
    SYSTEM_PROMPT_EN_SINGLE,
    _chinese_ratio,
    _detect_is_english,
    _score_batch_once,
    _translate_batch_once,
)


# ── token 捕获：按 method 分桶（同时修补模块内已导入的引用）──
import app.utils.llm_usage as _lu  # noqa: E402

_ORIG_LOG = _lu.log_llm_usage
_TOK: dict[str, dict[str, int]] = {"two_stage": {}, "single_stage": {}}
_CUR = {"m": "two_stage"}


def _capturing_log(scene, *, prompt=0, completion=0, cache_hit=0, reasoning=0, total=None):
    m = _CUR["m"]
    d = _TOK.setdefault(m, {})
    d[scene] = d.get(scene, 0) + (int(total) if total is not None else int(prompt or 0) + int(completion or 0))
    return _ORIG_LOG(
        scene=scene, prompt=prompt, completion=completion,
        cache_hit=cache_hit, reasoning=reasoning, total=total,
    )


_lu.log_llm_usage = _capturing_log
LNF.log_llm_usage = _capturing_log  # 关键：_score_batch_once 内部调用的就是模块级 log_llm_usage


# ── 覆盖补全：LLM 常静默丢弃条目，对缺失项重试直到覆盖全部或达上限 ──
async def _score_full_coverage(batch, client, system_prompt, max_retry=5):
    """对 batch 打分，并对被模型丢弃的条目重试，返回 {原始位置(1-based): ScoredNewsItem}。"""
    results: dict[int, object] = {}
    pending = list(range(1, len(batch) + 1))
    any_failure = False
    for _ in range(max_retry):
        if not pending:
            break
        sub = [batch[p - 1] for p in pending]
        res = await _score_batch_once(sub, True, client, system_prompt=system_prompt)
        if res.status not in ("ok",):
            any_failure = True
        got: set[int] = set()
        for si in res.scored:
            orig_pos = pending[si.original_id - 1]  # original_id 是该 sub 内的 1..len(sub)
            results[orig_pos] = si
            got.add(orig_pos)
        pending = [p for p in pending if p not in got]
    return results, any_failure


# ── 单方法运行 ──
async def run_two_stage(batch, client):
    """当前两阶段：阶段一评分（SYSTEM_PROMPT_EN_SCORE）+ 阶段二翻译（≥6）"""
    _CUR["m"] = "two_stage"
    stage1, fail1 = await _score_full_coverage(batch, client, SYSTEM_PROMPT_EN_SCORE)
    recs: dict[int, dict] = {}
    for p, si in stage1.items():
        recs[p] = {
            "score": si.score, "tags": si.tags, "is_highlight": si.is_highlight,
            "chinese_title": "", "summary": "", "why_it_matters": "", "present": True,
        }
    to_trans = [p for p, si in stage1.items() if si.score >= 6]
    bs = int(getattr(settings, "LLM_TRANSLATE_BATCH_SIZE", 20))
    for i in range(0, len(to_trans), bs):
        chunk = to_trans[i:i + bs]
        # 直接把原始位置作为 translate 的 ids，返回即按原始位置索引
        trans = await _translate_batch_once([batch[p - 1] for p in chunk], client, ids=chunk)
        for p in chunk:
            t = trans.get(p)
            if t:
                recs[p].update({
                    "chinese_title": t.get("chinese_title", ""),
                    "summary": t.get("summary", ""),
                    "why_it_matters": t.get("why_it_matters", ""),
                })
    return recs, fail1


async def run_single(batch, client):
    """单阶段实验：一次调用（SYSTEM_PROMPT_EN_SINGLE）同时评分 + 条件翻译"""
    _CUR["m"] = "single_stage"
    res, fail = await _score_full_coverage(batch, client, SYSTEM_PROMPT_EN_SINGLE)
    recs: dict[int, dict] = {}
    for p, si in res.items():
        recs[p] = {
            "score": si.score, "tags": si.tags, "is_highlight": si.is_highlight,
            "chinese_title": si.chinese_title or "", "summary": si.summary or "",
            "why_it_matters": si.why_it_matters or "", "present": True,
        }
    return recs, fail


# ── 可用率判定 ──
def _usable(text: str, min_ratio: float) -> bool:
    return bool(text) and _chinese_ratio(text) >= min_ratio


def _summarize(recs: dict[int, dict], min_ratio_title: float, min_ratio_summary: float) -> dict:
    ge6 = [r for r in recs.values() if r["score"] >= 6]
    ge8 = [r for r in recs.values() if r["score"] >= 8]
    title_ok = sum(1 for r in ge6 if _usable(r["chinese_title"], min_ratio_title)) if ge6 else 0
    summ_ok = sum(1 for r in ge6 if _usable(r["summary"], min_ratio_summary)) if ge6 else 0
    return {
        "n": len(recs), "n_ge6": len(ge6), "n_ge8": len(ge8),
        "title_usable_rate": (title_ok / len(ge6)) if ge6 else None,
        "summary_usable_rate": (summ_ok / len(ge6)) if ge6 else None,
    }


async def _load_from_db(limit: int) -> list[RawNewsItem]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.DATABASE_URL, future=True)
    raw_rows: list[dict] = []
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT title, content, source, url, published_at "
                    "FROM news WHERE content IS NOT NULL AND length(content) > 40 "
                    "ORDER BY id ASC LIMIT :lim"
                ),
                {"lim": int(limit)},
            )
            for row in res:
                raw_rows.append({
                    "title": row[0], "content": row[1] or "",
                    "source": row[2] or "", "url": row[3] or "",
                    "published_at": row[4],
                })
    finally:
        await engine.dispose()

    items: list[RawNewsItem] = []
    for r in raw_rows:
        if _detect_is_english(r["title"]):
            items.append(RawNewsItem(
                title=r["title"], content=r["content"],
                url=r["url"], source=r["source"],
                published_at=r["published_at"],
            ))
    return items


def _load_from_fixture(path: str) -> list[RawNewsItem]:
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    return [
        RawNewsItem(
            title=r["title"], content=r.get("content", ""),
            url=r.get("url", ""), source=r.get("source", ""),
        )
        for r in rows
    ]


async def load_items(args) -> list[RawNewsItem]:
    if args.fixture and os.path.exists(args.fixture):
        print(f"[load] fixture: {args.fixture}")
        items = _load_from_fixture(args.fixture)
    else:
        print("[load] from DB (news 表, 英文, id 升序) ...")
        items = await _load_from_db(args.limit)
        if args.save_fixture:
            with open(args.save_fixture, "w", encoding="utf-8") as f:
                json.dump(
                    [{"title": i.title, "content": i.content, "url": i.url, "source": i.source}
                     for i in items],
                    f, ensure_ascii=False, indent=1,
                )
            print(f"[load] saved fixture -> {args.save_fixture}")
    print(f"[load] {len(items)} 条英文新闻就绪")
    return items


async def main():
    ap = argparse.ArgumentParser(description="英文两阶段 vs 单阶段 A/B 实验")
    ap.add_argument("--limit", type=int, default=2000, help="从 DB 加载的最大条数（默认 2000，尽量取全量英文）")
    ap.add_argument("--batch-size", type=int, default=None, help="分批大小（默认 settings.LLM_BATCH_SIZE）")
    ap.add_argument("--fixture", type=str, default=None, help="固定输入集合 JSON 路径（优先于 DB）")
    ap.add_argument("--save-fixture", type=str, default=None, help="将加载结果落盘为 fixture JSON")
    ap.add_argument("--out", type=str, default="/tmp/en_ab_result.json", help="结果输出 JSON 路径")
    ap.add_argument("--dry", action="store_true", help="仅加载数据并打印统计，不调用 LLM")
    args = ap.parse_args()

    if not settings.LLM_API_KEY:
        print("ERROR: LLM_API_KEY 未配置，无法调用评分 API", file=sys.stderr)
        sys.exit(1)

    items = await load_items(args)
    if not items:
        print("ERROR: 未加载到英文新闻", file=sys.stderr)
        sys.exit(1)
    if len(items) < 200:
        print(f"WARNING: 仅 {len(items)} 条 (<200)；生产库英文新闻不足，统计置信度有限，"
              f"建议扩充英文源后再做最终切换决策", file=sys.stderr)

    if args.dry:
        print("[dry] 跳过 LLM 调用。样例标题：")
        for it in items[:5]:
            print("   -", it.title[:80])
        return

    bs = args.batch_size or int(getattr(settings, "LLM_BATCH_SIZE", 20))
    batches = [items[i:i + bs] for i in range(0, len(items), bs)]
    print(f"[run] {len(batches)} batches × {bs} (最后一批 {len(batches[-1])})")

    min_rt = float(getattr(settings, "LLM_MIN_CHINESE_RATIO_TITLE", 0.5))
    min_rs = float(getattr(settings, "LLM_MIN_CHINESE_RATIO_SUMMARY", 0.6))

    rows: list[dict] = []
    ts_batches_fail = 0
    ss_batches_fail = 0
    ts_missing = 0
    ss_missing = 0
    n_items = 0

    async with httpx.AsyncClient(timeout=120.0) as client:
        for bidx, batch in enumerate(batches):
            ts_recs, ts_fail = await run_two_stage(batch, client)
            ss_recs, ss_fail = await run_single(batch, client)
            if ts_fail:
                ts_batches_fail += 1
            if ss_fail:
                ss_batches_fail += 1

            for pos in range(1, len(batch) + 1):
                t = ts_recs.get(pos)
                s = ss_recs.get(pos)
                if t is None:
                    ts_missing += 1
                if s is None:
                    ss_missing += 1
                if t and s:
                    n_items += 1
                    rows.append({
                        "pos": pos, "batch": bidx,
                        "ts_score": t["score"], "ss_score": s["score"],
                        "ts_hl": t["is_highlight"], "ss_hl": s["is_highlight"],
                        "ts_title": t["chinese_title"], "ss_title": s["chinese_title"],
                        "ts_summary": t["summary"], "ss_summary": s["summary"],
                    })
            if (bidx + 1) % 5 == 0 or bidx == len(batches) - 1:
                print(f"[run] batch {bidx + 1}/{len(batches)} done "
                      f"(aligned so far={n_items}, ts_missing={ts_missing}, ss_missing={ss_missing})")

    def rate(pred):
        return sum(1 for r in rows if pred(r)) / len(rows) if rows else None

    score_match = rate(lambda r: r["ts_score"] == r["ss_score"])
    mae = (sum(abs(r["ts_score"] - r["ss_score"]) for r in rows) / len(rows)) if rows else None
    ge6 = rate(lambda r: (r["ts_score"] >= 6) == (r["ss_score"] >= 6))
    ge8 = rate(lambda r: (r["ts_score"] >= 8) == (r["ss_score"] >= 8))
    hl = rate(lambda r: bool(r["ts_hl"]) == bool(r["ss_hl"]))

    ts_recs_aligned = {i: {"score": r["ts_score"], "is_highlight": r["ts_hl"],
                           "chinese_title": r["ts_title"], "summary": r["ts_summary"]}
                       for i, r in enumerate(rows)}
    ss_recs_aligned = {i: {"score": r["ss_score"], "is_highlight": r["ss_hl"],
                           "chinese_title": r["ss_title"], "summary": r["ss_summary"]}
                       for i, r in enumerate(rows)}
    ts_sum = _summarize(ts_recs_aligned, min_rt, min_rs)
    ss_sum = _summarize(ss_recs_aligned, min_rt, min_rs)

    n_batches = len(batches)
    ts_fail_rate = ts_batches_fail / n_batches if n_batches else None
    ss_fail_rate = ss_batches_fail / n_batches if n_batches else None
    ts_cover = (n_items + (len(items) - n_items - ts_missing - ss_missing))  # 占位，下行用更准确口径
    # 覆盖率 = 成功对齐(双方法都有) + 仅单方法有的，近似用 (n_items + ts_missing + ss_missing)/total_pos

    def _tok_total(m):
        return sum(_TOK.get(m, {}).values())
    ts_total = _tok_total("two_stage")
    ss_total = _tok_total("single_stage")
    tok_saving = (1 - ss_total / ts_total) if ts_total else None

    total_positions = sum(len(b) for b in batches)
    ts_cover_rate = (total_positions - ts_missing) / total_positions if total_positions else None
    ss_cover_rate = (total_positions - ss_missing) / total_positions if total_positions else None

    metrics = {
        "n_input_items": len(items),
        "n_batches": n_batches,
        "n_aligned_items": n_items,
        "coverage_rate": {"two_stage": ts_cover_rate, "single_stage": ss_cover_rate},
        "score_match_rate": score_match,
        "score_mae": mae,
        "ge6_class_match_rate": ge6,
        "ge8_class_match_rate": ge8,
        "highlight_match_rate": hl,
        "two_stage": {
            "title_usable_rate": ts_sum["title_usable_rate"],
            "summary_usable_rate": ts_sum["summary_usable_rate"],
            "n_ge6": ts_sum["n_ge6"], "n_ge8": ts_sum["n_ge8"],
            "json_fail_rate": ts_fail_rate,
            "tokens": dict(_TOK.get("two_stage", {})),
            "token_total": ts_total,
        },
        "single_stage": {
            "title_usable_rate": ss_sum["title_usable_rate"],
            "summary_usable_rate": ss_sum["summary_usable_rate"],
            "n_ge6": ss_sum["n_ge6"], "n_ge8": ss_sum["n_ge8"],
            "json_fail_rate": ss_fail_rate,
            "tokens": dict(_TOK.get("single_stage", {})),
            "token_total": ss_total,
        },
        "token_saving_vs_twostage": tok_saving,
    }

    print("\n" + "=" * 60)
    print("A/B 结果：两阶段 vs 单阶段")
    print("=" * 60)
    print(f"输入英文新闻：{len(items)} 条 / {n_batches} batches；对齐条目：{n_items}")
    print(f"覆盖率        : 两阶段={ts_cover_rate}  单阶段={ss_cover_rate}")
    print(f"score 一致率  : {score_match}")
    print(f"score MAE     : {mae}")
    print(f"≥6 分类一致率 : {ge6}")
    print(f"≥8 分类一致率 : {ge8}")
    print(f"highlight 一致率: {hl}")
    print(f"中文标题可用率: 两阶段={ts_sum['title_usable_rate']}  单阶段={ss_sum['title_usable_rate']}  (n_ge6: {ts_sum['n_ge6']}/{ss_sum['n_ge6']})")
    print(f"摘要可用率    : 两阶段={ts_sum['summary_usable_rate']}  单阶段={ss_sum['summary_usable_rate']}")
    print(f"JSON 失败率   : 两阶段={ts_fail_rate}  单阶段={ss_fail_rate}")
    print(f"tokens(total) : 两阶段={ts_total}  单阶段={ss_total}  节省={tok_saving}")
    print("=" * 60)
    print("[达标判据] ≥6一致>=0.95 & ≥8一致>=0.95 & 标题/摘要可用率无退化(>=两阶段-0.05) & JSON失败率不高于两阶段")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"[out] {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
