"""英文两阶段 vs 单阶段 A/B 实验（P1）

目的
----
对比「当前两阶段（先评分后翻译，≥6 条目二次调用翻译）」与
「单阶段实验（一次调用完成评分 + 对 score>=6 条目条件翻译）」在
固定真实英文新闻上的表现与 token 成本，用于决定达标后是否切换。

运行方式（在 web 容器内，具备 DB 与 LLM API 密钥）：

    docker compose run --rm -w /app -e PYTHONPATH=/app \
        -v $(pwd)/scripts/ab_test_en_single_stage.py:/tmp/ab.py \
        web python /tmp/ab.py --limit 400 --out /tmp/en_ab_result.json

真实数据来源（固定、可复现）：
    - 默认从生产库 news 表取 content 长度足够、按 id 升序的前 N 条英文新闻；
    - 首次运行可用 --save-fixture 落盘为 JSON，之后用 --fixture 复用同一固定集合，
      保证多次实验使用完全相同的输入（LLM 非确定性仅影响输出，不影响输入分布）。

输出指标（对齐 P1 需求）：
    - score 一致率 / score 平均绝对差(MAE)
    - ≥6 分类一致率 / ≥8 分类一致率
    - highlight 一致率
    - 中文标题可用率 / 摘要可用率（单阶段 vs 两阶段，均基于各自 ≥6 集合）
    - JSON 解析失败率 / missing id 率
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
from app.services.rss_fetcher import RawNewsItem  # noqa: E402
from app.services.llm_news_filter import (  # noqa: E402
    SYSTEM_PROMPT_EN_SCORE,
    SYSTEM_PROMPT_EN_SINGLE,
    _chinese_ratio,
    _detect_is_english,
    _score_batch_once,
    _translate_batch_once,
)


# ── token 捕获：按 method 分桶 ──
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


# ── 数据加载 ──
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


# ── 单方法运行 ──
async def run_two_stage(batch: list[RawNewsItem], client: httpx.AsyncClient):
    """当前两阶段：阶段一评分（SYSTEM_PROMPT_EN_SCORE）+ 阶段二翻译（≥6）"""
    _CUR["m"] = "two_stage"
    scores = await _score_batch_once(batch, True, client, system_prompt=SYSTEM_PROMPT_EN_SCORE)
    recs: dict[int, dict] = {}
    for si in scores.scored:
        recs[si.original_id] = {
            "score": si.score, "tags": si.tags, "is_highlight": si.is_highlight,
            "chinese_title": "", "summary": "", "why_it_matters": "",
            "present": True, "status": scores.status,
        }
    to_trans = [si for si in scores.scored if si.score >= 6]
    bs = int(getattr(settings, "LLM_TRANSLATE_BATCH_SIZE", 20))
    for i in range(0, len(to_trans), bs):
        sub = to_trans[i:i + bs]
        trans = await _translate_batch_once([si.raw for si in sub], client, ids=[si.original_id for si in sub])
        for si in sub:
            t = trans.get(si.original_id)
            if t:
                recs[si.original_id].update({
                    "chinese_title": t.get("chinese_title", ""),
                    "summary": t.get("summary", ""),
                    "why_it_matters": t.get("why_it_matters", ""),
                })
    return scores, recs


async def run_single(batch: list[RawNewsItem], client: httpx.AsyncClient):
    """单阶段实验：一次调用（SYSTEM_PROMPT_EN_SINGLE）同时评分 + 条件翻译"""
    _CUR["m"] = "single_stage"
    res = await _score_batch_once(batch, True, client, system_prompt=SYSTEM_PROMPT_EN_SINGLE)
    recs: dict[int, dict] = {}
    for si in res.scored:
        recs[si.original_id] = {
            "score": si.score, "tags": si.tags, "is_highlight": si.is_highlight,
            "chinese_title": si.chinese_title or "", "summary": si.summary or "",
            "why_it_matters": si.why_it_matters or "",
            "present": True, "status": res.status,
        }
    return res, recs


# ── 可用率判定 ──
def _usable(text: str, min_ratio: float) -> bool:
    return bool(text) and _chinese_ratio(text) >= min_ratio


def _summarize(recs: dict[int, dict], min_ratio_title: float, min_ratio_summary: float) -> dict:
    ge6 = [r for r in recs.values() if r["score"] >= 6]
    ge8 = [r for r in recs.values() if r["score"] >= 8]
    title_ok = sum(1 for r in ge6 if _usable(r["chinese_title"], min_ratio_title)) if ge6 else 0
    summ_ok = sum(1 for r in ge6 if _usable(r["summary"], min_ratio_summary)) if ge6 else 0
    return {
        "n_ge6": len(ge6), "n_ge8": len(ge8),
        "title_usable": title_ok, "title_usable_rate": (title_ok / len(ge6)) if ge6 else None,
        "summary_usable": summ_ok, "summary_usable_rate": (summ_ok / len(ge6)) if ge6 else None,
    }


async def main():
    ap = argparse.ArgumentParser(description="英文两阶段 vs 单阶段 A/B 实验")
    ap.add_argument("--limit", type=int, default=400, help="从 DB 加载的最大条数（默认 400）")
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
        print(f"WARNING: 仅 {len(items)} 条 (<200)，统计置信度有限，建议扩大输入", file=sys.stderr)

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
            ts_res, ts_recs = await run_two_stage(batch, client)
            ss_res, ss_recs = await run_single(batch, client)

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
            if ts_res.status not in ("ok",):
                ts_batches_fail += 1
            if ss_res.status not in ("ok",):
                ss_batches_fail += 1
            if (bidx + 1) % 5 == 0 or bidx == len(batches) - 1:
                print(f"[run] batch {bidx + 1}/{len(batches)} done "
                      f"(aligned so far={n_items}, ts_fail={ts_batches_fail}, ss_fail={ss_batches_fail})")

    # ── 指标计算 ──
    def rate(pred):
        return sum(1 for r in rows if pred(r)) / len(rows) if rows else None

    score_match = rate(lambda r: r["ts_score"] == r["ss_score"])
    mae = (sum(abs(r["ts_score"] - r["ss_score"]) for r in rows) / len(rows)) if rows else None
    ge6 = rate(lambda r: (r["ts_score"] >= 6) == (r["ss_score"] >= 6))
    ge8 = rate(lambda r: (r["ts_score"] >= 8) == (r["ss_score"] >= 8))
    hl = rate(lambda r: bool(r["ts_hl"]) == bool(r["ss_hl"]))

    # 重建每方法 recs（仅对齐条目）以算可用率
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

    # token
    def _tok_total(m):
        return sum(_TOK.get(m, {}).values())
    ts_total = _tok_total("two_stage")
    ss_total = _tok_total("single_stage")
    tok_saving = (1 - ss_total / ts_total) if ts_total else None

    metrics = {
        "n_input_items": len(items),
        "n_batches": n_batches,
        "n_aligned_items": n_items,
        "score_match_rate": score_match,
        "score_mae": mae,
        "ge6_class_match_rate": ge6,
        "ge8_class_match_rate": ge8,
        "highlight_match_rate": hl,
        "two_stage": {
            "title_usable_rate": ts_sum["title_usable_rate"],
            "summary_usable_rate": ss_sum["title_usable_rate"],  # placeholder, fixed below
            "json_fail_rate": ts_fail_rate,
            "missing_id_rate": (ts_missing / (n_items + ts_missing)) if (n_items + ts_missing) else None,
            "tokens": dict(_TOK.get("two_stage", {})),
            "token_total": ts_total,
        },
        "single_stage": {
            "title_usable_rate": ss_sum["title_usable_rate"],
            "summary_usable_rate": ss_sum["summary_usable_rate"],
            "json_fail_rate": ss_fail_rate,
            "missing_id_rate": (ss_missing / (n_items + ss_missing)) if (n_items + ss_missing) else None,
            "tokens": dict(_TOK.get("single_stage", {})),
            "token_total": ss_total,
        },
        "token_saving_vs_twostage": tok_saving,
    }
    # 修正两阶段 summary 可用率字段
    metrics["two_stage"]["summary_usable_rate"] = ts_sum["summary_usable_rate"]

    # ── 报告 ──
    print("\n" + "=" * 60)
    print("A/B 结果：两阶段 vs 单阶段")
    print("=" * 60)
    print(f"输入英文新闻：{len(items)} 条 / {n_batches} batches；对齐条目：{n_items}")
    print(f"score 一致率      : {score_match}")
    print(f"score MAE         : {mae}")
    print(f"≥6 分类一致率     : {ge6}")
    print(f"≥8 分类一致率     : {ge8}")
    print(f"highlight 一致率  : {hl}")
    print(f"中文标题可用率    : 两阶段={ts_sum['title_usable_rate']}  单阶段={ss_sum['title_usable_rate']}  (n_ge6: {ts_sum['n_ge6']}/{ss_sum['n_ge6']})")
    print(f"摘要可用率        : 两阶段={ts_sum['summary_usable_rate']}  单阶段={ss_sum['summary_usable_rate']}")
    print(f"JSON 失败率       : 两阶段={ts_fail_rate}  单阶段={ss_fail_rate}")
    print(f"missing id 率     : 两阶段={metrics['two_stage']['missing_id_rate']}  单阶段={metrics['single_stage']['missing_id_rate']}")
    print(f"tokens(total)     : 两阶段={ts_total}  单阶段={ss_total}  节省={tok_saving}")
    print("=" * 60)
    print("[达标判据] ≥6一致>=0.95 & ≥8一致>=0.95 & 标题/摘要可用率无退化(>=两阶段-0.05) & JSON失败率不高于两阶段")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"[out] {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
