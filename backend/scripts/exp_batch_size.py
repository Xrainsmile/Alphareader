"""英文/中文评分 Batch Size 实验（离线，真实历史新闻）。

目的：验证将 LLM_BATCH_SIZE 从 20 提升到 30 / 40 时，
System Prompt 被更多条目摊薄后 prompt_tokens/item 的下降幅度，
以及缺失 ID / JSON 解析失败 / 重试 / 内容安全 / 延迟 是否明显恶化。

设计：
- 仅测「评分」调用（CN→SYSTEM_PROMPT_CN，EN→SYSTEM_PROMPT_EN_SCORE，均走 _score_batch_once）。
  翻译阶段使用独立的固定 LLM_TRANSLATE_BATCH_SIZE，不受评分 batch_size 影响，不在本实验口径内。
- 三组 batch_size 共用同一份输入集合，仅改变分批大小，保证可比。
- 指标采集：
  * token：patch log_llm_usage，仅累计 scoring 场景（news_score_cn / news_score_en）。
  * 延迟/请求数：patch _call_llm_once，记录每次 HTTP 调用的耗时（并发安全）。
  * 缺失/重复/状态：从每个 BatchResult 直接累加。

用法：
  python scripts/exp_batch_size.py --dry                 # 仅加载+分批校验，不调 LLM
  python scripts/exp_batch_size.py --limit 1500          # 全量实跑 20/30/40
  python scripts/exp_batch_size.py --fixture /tmp/bs.json --out /tmp/bs_out.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, "/app")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.services.rss_fetcher import RawNewsItem
import app.utils.llm_usage as _lu
import app.services.llm_news_filter as LNF
from app.services.llm_news_filter import (
    _score_batch_once,
    SYSTEM_PROMPT_CN,
    SYSTEM_PROMPT_EN_SCORE,
    _detect_is_english,
)

# ── token 捕获（仅 scoring 场景）──
_TOK = {
    "news_score_cn": defaultdict(int),
    "news_score_en": defaultdict(int),
}
_CALL_COMPLETION: list[int] = []  # 每次 scoring 调用的 completion tokens
_ORIG_LOG = _lu.log_llm_usage


def _capturing_log(scene, *, prompt=0, completion=0, cache_hit=0, reasoning=0, total=None):
    if scene in _TOK:
        d = _TOK[scene]
        d["prompt"] += int(prompt or 0)
        d["completion"] += int(completion or 0)
        d["total"] += int(total) if total is not None else int(prompt or 0) + int(completion or 0)
        d["calls"] += 1
        _CALL_COMPLETION.append(int(completion or 0))
    return _ORIG_LOG(
        scene=scene, prompt=prompt, completion=completion,
        cache_hit=cache_hit, reasoning=reasoning, total=total,
    )


_lu.log_llm_usage = _capturing_log
LNF.log_llm_usage = _capturing_log  # 关键：_score_batch_once 内部调用的是模块级 log_llm_usage

# ── 延迟 / 请求数 捕获（patch _call_llm_once）──
_LAT: list[float] = []
_ORIG_CALL = LNF._call_llm_once


async def _wrapped_call(payload, headers, client, *, scene="news_score"):
    t0 = time.perf_counter()
    raw, status, body, ra = await _ORIG_CALL(payload, headers, client, scene=scene)
    _LAT.append(time.perf_counter() - t0)
    return raw, status, body, ra


LNF._call_llm_once = _wrapped_call


# ── 数据加载 ──
def _split(items):
    cn = [it for it in items if not _detect_is_english(it.title)]
    en = [it for it in items if _detect_is_english(it.title)]
    return cn, en


async def _load_from_db(limit: int) -> list[RawNewsItem]:
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    rows: list[dict] = []
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
                rows.append({
                    "title": row[0], "content": row[1] or "",
                    "source": row[2] or "", "url": row[3] or "",
                    "published_at": row[4],
                })
    finally:
        await engine.dispose()
    default_dt = datetime.now()
    items: list[RawNewsItem] = []
    for r in rows:
        items.append(RawNewsItem(
            title=r["title"], content=r["content"],
            url=r["url"], source=r["source"],
            published_at=r["published_at"] or default_dt,
        ))
    return items


def _load_fixture(path: str) -> list[RawNewsItem]:
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    items: list[RawNewsItem] = []
    for r in rows:
        items.append(RawNewsItem(
            title=r["title"], content=r.get("content", ""),
            url=r.get("url", ""), source=r.get("source", ""),
            published_at=datetime.now(),
        ))
    return items


# ── 单次 batch_size 运行 ──
def _reset_run_state():
    for d in _TOK.values():
        d.clear()
    _CALL_COMPLETION.clear()
    _LAT.clear()


async def run_one_bs(items, B: int, concurrency: int) -> dict:
    _reset_run_state()
    cn, en = _split(items)
    cn_chunks = [cn[i:i + B] for i in range(0, len(cn), B)]
    en_chunks = [en[i:i + B] for i in range(0, len(en), B)]
    batches = [(b, False) for b in cn_chunks] + [(b, True) for b in en_chunks]

    m = {
        "B": B,
        "n_items": len(items),
        "n_cn": len(cn), "n_en": len(en),
        "n_batches": len(batches),
        "requests": 0,
        "parse_error_batches": 0,
        "api_error_batches": 0,
        "content_risk_batches": 0,
        "content_risk_dropped": 0,
        "missing_ids": 0,
        "duplicate_ids": 0,
        "done": 0,
    }

    sem = asyncio.Semaphore(concurrency)

    async def process(batch, is_en):
        sp = SYSTEM_PROMPT_EN_SCORE if is_en else SYSTEM_PROMPT_CN
        async with sem:
            res = await _score_batch_once(batch, is_en, client, system_prompt=sp)
        m["requests"] += 1  # 顶层 batch 计 1；实际请求数用 len(_LAT) 校正
        st = res.status
        if st == "parse_error":
            m["parse_error_batches"] += 1
        elif st == "api_error":
            m["api_error_batches"] += 1
        elif st == "content_risk":
            m["content_risk_batches"] += 1
        m["content_risk_dropped"] += int(res.content_risk_dropped or 0)
        m["missing_ids"] += len(res.missing_ids or [])
        m["duplicate_ids"] += len(res.duplicate_ids or [])
        m["done"] += 1
        if m["done"] % 10 == 0 or m["done"] == m["n_batches"]:
            print(f"  [B={B}] {m['done']}/{m['n_batches']} batches | "
                  f"req={len(_LAT)} miss={m['missing_ids']} perr={m['parse_error_batches']}",
                  flush=True)

    async with __import__("httpx").AsyncClient(timeout=180.0) as client:
        await asyncio.gather(*[process(b, e) for b, e in batches])

    # token（scoring 场景）
    prompt_tok = _TOK["news_score_cn"]["prompt"] + _TOK["news_score_en"]["prompt"]
    comp_tok = _TOK["news_score_cn"]["completion"] + _TOK["news_score_en"]["completion"]
    total_tok = _TOK["news_score_cn"]["total"] + _TOK["news_score_en"]["total"]
    actual_requests = len(_LAT)

    m.update({
        "actual_requests": actual_requests,
        "prompt_tokens": prompt_tok,
        "completion_tokens": comp_tok,
        "total_tokens": total_tok,
        "prompt_per_item": (prompt_tok / m["n_items"]) if m["n_items"] else 0,
        "completion_per_item": (comp_tok / m["n_items"]) if m["n_items"] else 0,
        "missing_rate": (m["missing_ids"] / m["n_items"]) if m["n_items"] else 0,
        "duplicate_rate": (m["duplicate_ids"] / m["n_items"]) if m["n_items"] else 0,
        "parse_error_rate": (m["parse_error_batches"] / m["n_batches"]) if m["n_batches"] else 0,
        "api_error_rate": (m["api_error_batches"] / m["n_batches"]) if m["n_batches"] else 0,
        "content_risk_rate": (m["content_risk_batches"] / m["n_batches"]) if m["n_batches"] else 0,
        "content_risk_item_rate": (m["content_risk_dropped"] / m["n_items"]) if m["n_items"] else 0,
        "extra_call_rate": ((actual_requests - m["n_batches"]) / m["n_batches"]) if m["n_batches"] else 0,
        "avg_latency": (statistics.mean(_LAT) if _LAT else 0),
        "p95_latency": (sorted(_LAT)[int(len(_LAT) * 0.95) - 1] if len(_LAT) >= 20 else (max(_LAT) if _LAT else 0)),
        "max_completion": (max(_CALL_COMPLETION) if _CALL_COMPLETION else 0),
        "near_ceiling_calls": sum(1 for c in _CALL_COMPLETION if c >= 4090),
        "tok_cn": dict(_TOK["news_score_cn"]),
        "tok_en": dict(_TOK["news_score_en"]),
    })
    return m


def _fmt_pct(x):
    return f"{x*100:.2f}%"


def _print_table(results: dict[int, dict]):
    keys = ["B", "n_items", "n_batches", "actual_requests", "prompt_tokens",
            "prompt_per_item", "completion_per_item", "total_tokens",
            "missing_rate", "duplicate_rate", "parse_error_rate", "api_error_rate",
            "content_risk_rate", "extra_call_rate", "avg_latency", "p95_latency",
            "max_completion", "near_ceiling_calls"]
    print("\n" + "=" * 110)
    print("Batch Size 实验对比（仅评分调用；翻译独立固定 batch，未计入）")
    print("=" * 110)
    hdr = " | ".join([
        "B", "items", "batches", "reqs", "prompt_tok", "prompt/item",
        "compl/item", "tot_tok", "miss%", "dup%", "parseErr%", "apiErr%",
        "crisk%", "extra%", "avgLat", "p95Lat", "maxCompl", "≈ceil",
    ])
    print(hdr)
    for B in sorted(results):
        r = results[B]
        row = " | ".join([
            f"{r['B']:>3}", f"{r['n_items']:>5}", f"{r['n_batches']:>5}",
            f"{r['actual_requests']:>5}", f"{r['prompt_tokens']:>9}",
            f"{r['prompt_per_item']:>9.1f}", f"{r['completion_per_item']:>8.1f}",
            f"{r['total_tokens']:>9}", f"{r['missing_rate']*100:>5.2f}",
            f"{r['duplicate_rate']*100:>4.2f}", f"{r['parse_error_rate']*100:>6.2f}",
            f"{r['api_error_rate']*100:>6.2f}", f"{r['content_risk_rate']*100:>5.2f}",
            f"{r['extra_call_rate']*100:>5.2f}", f"{r['avg_latency']:>5.2f}",
            f"{r['p95_latency']:>5.2f}", f"{r['max_completion']:>6}", f"{r['near_ceiling_calls']:>4}",
        ])
        print(row)
    print("=" * 110)


def _decide(results: dict[int, dict]):
    r20 = results.get(20)
    r30 = results.get(30)
    r40 = results.get(40)
    lines = []

    if r20 and r30:
        reduce30 = (r20["prompt_per_item"] - r30["prompt_per_item"]) / r20["prompt_per_item"] if r20["prompt_per_item"] else 0
        cond_a = reduce30 >= 0.10
        cond_b = r30["parse_error_rate"] <= r20["parse_error_rate"] + 0.005
        cond_c = r30["missing_rate"] <= max(r20["missing_rate"] * 1.5, r20["missing_rate"] + 0.005)
        cond_d = r30["extra_call_rate"] <= r20["extra_call_rate"] + 0.05
        ok30 = cond_a and cond_b and cond_c and cond_d
        lines.append(f"[30 vs 20] prompt/item 下降 {reduce30*100:.1f}%"
                     f" | parseErr {_fmt_pct(r20['parse_error_rate'])}→{_fmt_pct(r30['parse_error_rate'])}"
                     f" | miss {_fmt_pct(r20['missing_rate'])}→{_fmt_pct(r30['missing_rate'])}"
                     f" | extra {_fmt_pct(r20['extra_call_rate'])}→{_fmt_pct(r30['extra_call_rate'])}")
        lines.append(f"  条件A(降幅≥10%)={cond_a} B(parse不恶化)={cond_b} C(miss不恶化)={cond_c} D(retry不恶化)={cond_d}"
                     f" → 建议默认改30 = {ok30}")
    else:
        ok30 = False

    warn40 = False
    if r30 and r40:
        miss_worse = r40["missing_rate"] > max(r30["missing_rate"] * 1.5, 0.02)
        parse_worse = r40["parse_error_rate"] > r30["parse_error_rate"] + 0.01
        trunc = r40["near_ceiling_calls"] > 0 and (parse_worse or miss_worse)
        warn40 = miss_worse or parse_worse or trunc
        lines.append(f"[40 vs 30] miss {_fmt_pct(r30['missing_rate'])}→{_fmt_pct(r40['missing_rate'])}"
                     f" | parseErr {_fmt_pct(r30['parse_error_rate'])}→{_fmt_pct(r40['parse_error_rate'])}"
                     f" | maxCompl={r40['max_completion']} ≈ceilCalls={r40['near_ceiling_calls']}")
        lines.append(f"  40 出现明显漏ID/JSON截断风险 = {warn40} → 不建议使用40 = {warn40}")

    print("\n".join(lines))
    if ok30:
        print("✅ 决策：按规则将默认 LLM_BATCH_SIZE 改为 30（40 不启用）。")
    else:
        print("⚠️ 决策：30 未达切换条件，保持默认 20；40 不启用。")
    if warn40:
        print("🚫 明确：40 存在漏ID/截断风险，绝不设为默认值。")
    return ok30, warn40


async def main():
    ap = argparse.ArgumentParser(description="评分 Batch Size 实验（20/30/40）")
    ap.add_argument("--limit", type=int, default=1500, help="从 DB 加载的最大条数（默认 1500，≥1000）")
    ap.add_argument("--batch-sizes", type=str, default="20,30,40", help="逗号分隔的分批大小")
    ap.add_argument("--concurrency", type=int, default=3, help="并发评分请求数（默认 3，贴近生产）")
    ap.add_argument("--fixture", type=str, default=None, help="固定输入集合 JSON（优先于 DB）")
    ap.add_argument("--save-fixture", type=str, default=None, help="将加载结果落盘为 fixture")
    ap.add_argument("--out", type=str, default="/tmp/batch_size_exp.json", help="结果输出 JSON")
    ap.add_argument("--dry", action="store_true", help="仅加载+分批，不调 LLM")
    args = ap.parse_args()

    if not settings.LLM_API_KEY:
        print("ERROR: LLM_API_KEY 未配置", file=sys.stderr)
        sys.exit(1)

    batch_sizes = [int(x) for x in args.batch_sizes.split(",") if x.strip()]

    # 加载（三个 batch_size 共用同一份输入）
    if args.fixture and os.path.exists(args.fixture):
        items = _load_fixture(args.fixture)
        print(f"[load] fixture: {args.fixture} ({len(items)} 条)")
    else:
        print("[load] from DB (news 表, id 升序) ...")
        items = await _load_from_db(args.limit)
        if args.save_fixture:
            with open(args.save_fixture, "w", encoding="utf-8") as f:
                json.dump(
                    [{"title": i.title, "content": i.content, "url": i.url, "source": i.source}
                     for i in items], f, ensure_ascii=False, indent=1)
            print(f"[load] saved fixture -> {args.save_fixture}")
    if not items:
        print("ERROR: 未加载到新闻", file=sys.stderr)
        sys.exit(1)
    cn, en = _split(items)
    print(f"[load] 共 {len(items)} 条（CN={len(cn)} EN={len(en)}）")

    if args.dry:
        for B in batch_sizes:
            c = [cn[i:i + B] for i in range(0, len(cn), B)]
            e = [en[i:i + B] for i in range(0, len(en), B)]
            print(f"[dry] B={B}: cn_batches={len(c)} en_batches={len(e)} "
                  f"last_cn={len(c[-1]) if c else 0} last_en={len(e[-1]) if e else 0}")
        return

    results: dict[int, dict] = {}
    for B in batch_sizes:
        print(f"\n>>> 运行 batch_size={B} ...")
        t0 = time.perf_counter()
        r = await run_one_bs(items, B, args.concurrency)
        r["elapsed_s"] = round(time.perf_counter() - t0, 1)
        results[B] = r
        print(f">>> B={B} 完成：{r['elapsed_s']}s | prompt/item={r['prompt_per_item']:.1f} "
              f"| miss={_fmt_pct(r['missing_rate'])} | parseErr={_fmt_pct(r['parse_error_rate'])} "
              f"| reqs={r['actual_requests']}")

    _print_table(results)
    ok30, warn40 = _decide(results)

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_items": len(items), "concurrency": args.concurrency,
        "results": results,
        "decision": {"switch_default_to_30": ok30, "warn_against_40": warn40},
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[done] 结果已写入 {args.out}")
    # 决策结论以退出码形式供调用方感知（0=未达切换，2=建议切30）
    sys.exit(2 if ok30 else 0)


if __name__ == "__main__":
    asyncio.run(main())
