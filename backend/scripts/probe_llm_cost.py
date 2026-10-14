#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测 LLM 校验：真实调用，打印 token 与耗时，验证是否真在工作。

回答两个问题：
1. 生产上 LLM 校验会不会浪费 token？（单次消耗 × 触发频次）
2. 它到底有没有真的拦下东西？（还是纯烧钱不干活）
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.config import settings                          # noqa: E402
from app.database import async_session                   # noqa: E402
from app.services import thread_router as tr             # noqa: E402
from app.services import thread_verifier as tv           # noqa: E402


def est_tokens(s: str) -> int:
    """粗估 token：中文按 1 字≈1 token，英文按 4 字符≈1 token 加权。"""
    cn = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    en = len(s) - cn
    return int(cn + en / 3.5)


async def main():
    print("=" * 74)
    print("LLM 校验实测：token 消耗 + 是否真能拦")
    print("=" * 74)
    print(f"开关 ENABLED = {settings.THREAD_LLM_VERIFY_ENABLED}")
    print(f"灰色带       = [{settings.THREAD_T_JOIN}, "
          f"{settings.THREAD_T_JOIN + settings.THREAD_LLM_VERIFY_BAND})")
    print(f"模型         = {settings.LLM_MODEL}")
    print(f"每事件最多线 = {settings.THREAD_MAX_LINES_PER_EVENT}")
    print()

    # 单次 prompt 体积
    sys_t = tv._SYSTEM
    sample_user = tv._USER.format(
        title="霍尔木兹海峡通航权争夺",
        asset="霍尔木兹海峡通航权",
        mech="军事威慑→航运中断→油价上涨",
        chapters="\n".join("- " + f"章节{i}：某事件标题示例二十字左右" for i in range(1, 6)),
        ev_title="阿联酋ADNOC船只霍尔木兹海峡遇袭",
        ev_summary="某摘要内容" * 30,
    )
    in_tok = est_tokens(sys_t + sample_user)
    out_tok = 40  # max_tokens=120，实际 JSON 约 30-40
    print("─" * 74)
    print("单次调用 token（真实 prompt 估算）")
    print("─" * 74)
    print(f"  system prompt  {est_tokens(sys_t):>5} token（固定开销，每次都发）")
    print(f"  user prompt    {est_tokens(sample_user):>5} token（线标题+5章节+事件）")
    print(f"  输入合计       {in_tok:>5} token")
    print(f"  输出           {out_tok:>5} token（verdict JSON）")
    print(f"  单次合计       {in_tok + out_tok:>5} token")
    print()
    print(f"  ⚠ system prompt 占输入 {100*est_tokens(sys_t)/in_tok:.0f}%，"
          f"是每次都重复付的固定成本")
    print()

    # 真实调用一发，看耗时
    print("─" * 74)
    print("真实调用 1 次（验证链路通不通）")
    print("─" * 74)
    t0 = time.time()
    v = await tv.verify(
        ev_title="Eagle Nuclear Energy 提交8-K披露经营业绩",
        ev_summary="该公司向SEC提交8-K文件，披露近期经营业绩。",
        thread_title="霍尔木兹海峡通航权争夺",
        thread_asset="霍尔木兹海峡通航权",
        thread_mech="军事威慑→航运中断→油价上涨",
        chapters=["章节1", "章节2"],
    )
    dt = time.time() - t0
    print(f"  返回 verdict = {v}（False=拦下，True/None=放行）")
    print(f"  耗时 {dt:.2f}s")
    print()

    # 统计生产上灰色带实际占比
    async with async_session() as s:
        rows = (await s.execute(text("""
            SELECT score, joined, gate FROM thread_route_scores
        """))).all()
    if rows:
        hit = [r for r in rows if r[1]]
        band = [r for r in hit
                if settings.THREAD_T_JOIN <= (r[0] or 0)
                < settings.THREAD_T_JOIN + settings.THREAD_LLM_VERIFY_BAND]
        print("─" * 74)
        print("生产留痕统计（thread_route_scores）")
        print("─" * 74)
        print(f"  打分行数 {len(rows)}｜命中行数 {len(hit)}｜灰色带 {len(band)}")
        if hit:
            print(f"  灰色带占命中 {100*len(band)/len(hit):.1f}%")
        gates = {}
        for r in rows:
            gates[r[2] or "(空)"] = gates.get(r[2] or "(空)", 0) + 1
        print(f"  gate 分布：{gates}")
        print(f"  llm_reject 次数：{gates.get('llm_reject', 0)}")
        print()

    # 成本推算
    print("─" * 74)
    print("成本推算")
    print("─" * 74)
    async with async_session() as s:
        n24 = (await s.execute(text(
            "SELECT count(*) FROM events WHERE created_at > now()-interval '24 hours'"
        ))).scalar() or 0
    per_tok = in_tok + out_tok
    for label, calls in (("每天（假设每事件1次）", n24),
                         ("每天（假设每事件2次）", n24 * 2)):
        total = calls * per_tok
        print(f"  {label:<22} {calls:>4} 次 × {per_tok} token = {total:>7} token/天"
              f"  ≈ {total*30/1000:.1f}K/月")
    print()
    print("  deepseek-flash 参考价：输入 ¥1/M token，输出 ¥8/M token（以官网为准）")
    in_c = n24 * in_tok / 1_000_000 * 1
    out_c = n24 * out_tok / 1_000_000 * 8
    print(f"  按每事件1次：日成本 ≈ ¥{in_c + out_c:.4f}"
          f"｜月成本 ≈ ¥{(in_c + out_c) * 30:.2f}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
