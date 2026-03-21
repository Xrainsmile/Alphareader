"""本地离线验证 Daily Briefing — 收集数据 + 生成报告，打印到终端/文件。

用法：
  cd backend
  python3 test_briefing.py               # 默认今天
  python3 test_briefing.py 2026-03-20    # 指定日期
  python3 test_briefing.py --dry-run     # 只看 prompt，不调用 DeepSeek
"""

from __future__ import annotations

import asyncio
import sys
import os
from datetime import date, datetime

# 确保能从 backend/ 目录导入 app 包
sys.path.insert(0, os.path.dirname(__file__))


async def main():
    # 解析参数
    dry_run = "--dry-run" in sys.argv
    target_date = None
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        try:
            target_date = date.fromisoformat(arg)
        except ValueError:
            print(f"⚠️  无法解析日期: {arg}，使用今天")

    from app.config import settings
    import pytz

    tz = pytz.timezone(settings.TIMEZONE)
    if target_date is None:
        target_date = datetime.now(tz).date()

    print(f"{'='*60}")
    print(f"  Daily Briefing 离线验证")
    print(f"  日期: {target_date}")
    print(f"  数据库: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")
    print(f"  模式: {'DRY-RUN（只看 prompt）' if dry_run else '完整（调用 DeepSeek）'}")
    print(f"{'='*60}\n")

    # ---------- 1. 收集数据 ----------
    from app.services.briefing_service import (
        _fetch_vcp_watchlist,
        _fetch_trend_watchlist,
        _fetch_value_stocks,
        _fetch_stock_quotes,
        _fetch_rs_ratings,
        _fetch_news_digests,
        _fetch_nav,
        _build_briefing_prompt,
        _call_deepseek_briefing,
    )

    print("📡 正在收集数据...")

    vcp_list, trend_list, value_list, digests, nav = await asyncio.gather(
        _fetch_vcp_watchlist(target_date),
        _fetch_trend_watchlist(target_date),
        _fetch_value_stocks(),
        _fetch_news_digests(target_date),
        _fetch_nav(target_date),
    )

    all_codes = list(set(
        [s["ts_code"] for s in vcp_list]
        + [s["ts_code"] for s in trend_list]
        + [s["ts_code"] for s in value_list]
    ))

    quotes, rs_ratings = await asyncio.gather(
        _fetch_stock_quotes(all_codes, target_date),
        _fetch_rs_ratings(all_codes, target_date),
    )

    # ---------- 2. 打印数据统计 ----------
    print(f"\n📊 数据统计:")
    print(f"  VCP 白名单: {len(vcp_list)} 只")
    print(f"  趋势白名单: {len(trend_list)} 只")
    print(f"  价投观察池: {len(value_list)} 只")
    print(f"  新闻概览:   {len(digests)} 个时段")
    print(f"  行情数据:   {len(quotes)} 只")
    print(f"  RS Rating:  {len(rs_ratings)} 只")
    print(f"  模拟仓:     {'有' if nav else '无'}")

    if vcp_list:
        print(f"\n  VCP 标的: {', '.join(s['name'] + '(' + s['ts_code'] + ')' for s in vcp_list[:10])}")
    if trend_list:
        print(f"  趋势标的: {', '.join(s['name'] + '(' + s['ts_code'] + ')' for s in trend_list[:10])}")
    if value_list:
        print(f"  价投标的: {', '.join(s['name'] + '(' + s['ts_code'] + ')' for s in value_list[:10])}")
    if nav:
        print(f"  模拟仓净值: {nav['nav']:.4f} | 盈亏: {nav['total_pnl']:.2f}%")

    # ---------- 3. 构建 Prompt ----------
    user_prompt = _build_briefing_prompt(
        target_date, vcp_list, trend_list, value_list,
        quotes, rs_ratings, digests, nav,
    )
    prompt_tokens_est = len(user_prompt) // 2

    print(f"\n📝 Prompt 统计:")
    print(f"  字符数: {len(user_prompt)}")
    print(f"  预估 tokens: ~{prompt_tokens_est}")

    # 保存 prompt 到文件
    prompt_file = f"briefing_prompt_{target_date}.md"
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(user_prompt)
    print(f"  Prompt 已保存到: {prompt_file}")

    # 总是打印 prompt 摘要
    print(f"\n{'─'*60}")
    print("📄 Prompt 预览（前 2000 字符）:")
    print(f"{'─'*60}")
    preview = user_prompt[:2000]
    if len(user_prompt) > 2000:
        preview += f"\n\n... (后续 {len(user_prompt) - 2000} 字符已省略，完整内容见 {prompt_file})"
    print(preview)
    print(f"{'─'*60}\n")

    if len(vcp_list) == 0 and len(trend_list) == 0 and len(value_list) == 0 and len(digests) == 0:
        print("⚠️  所有数据都为空，无法生成有意义的报告。")
        print("   可能原因：")
        print("   - 今天不是交易日（周末/假日）")
        print("   - screener 还没有跑过")
        print("   - 数据库连接的是本地空库")
        return

    if dry_run:
        print("🏁 DRY-RUN 模式，跳过 DeepSeek 调用。")
        return

    # ---------- 4. 调用 DeepSeek ----------
    print("🤖 正在调用 DeepSeek 生成报告...")
    import time
    t0 = time.monotonic()
    content = await _call_deepseek_briefing(user_prompt)
    elapsed = time.monotonic() - t0

    if not content:
        print(f"\n❌ DeepSeek 返回空内容（耗时 {elapsed:.1f}s）")
        print("   检查 DEEPSEEK_API_KEY 是否配置正确。")
        return

    print(f"\n✅ 报告生成成功！（{len(content)} 字符，耗时 {elapsed:.1f}s）")

    # 保存报告
    report_file = f"briefing_report_{target_date}.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"📁 报告已保存到: {report_file}")

    # 打印报告
    print(f"\n{'='*60}")
    print(f"  📋 每日分析报告 — {target_date}")
    print(f"{'='*60}\n")
    print(content)
    print(f"\n{'='*60}")
    print(f"  完成！VCP={len(vcp_list)} 趋势={len(trend_list)} "
          f"价投={len(value_list)} 耗时={elapsed:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
