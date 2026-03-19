"""一次性脚本：清理 published_at 过旧的新闻（如 OpenAI Blog 历史全量文章）

usage: docker exec alpha-web python3 /app/cleanup_stale_news.py
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.database import async_session
from sqlalchemy import text


async def cleanup():
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    print(f"Cutoff: {cutoff.isoformat()}")
    print(f"Will delete news with published_at < {cutoff.isoformat()}")
    print()

    async with async_session() as s:
        # 先统计
        r = await s.execute(text(
            "SELECT source, COUNT(*) FROM news "
            "WHERE published_at < :cutoff "
            "GROUP BY source ORDER BY COUNT(*) DESC"
        ), {"cutoff": cutoff})
        rows = r.fetchall()
        total = sum(row[1] for row in rows)
        print(f"=== 将要删除的过时新闻 ({total} 条) ===")
        for row in rows:
            print(f"  {row[0]}: {row[1]} 条")

        if total == 0:
            print("\n没有需要清理的过时新闻。")
            return

        # 执行删除
        print(f"\n正在删除 {total} 条过时新闻...")
        result = await s.execute(text(
            "DELETE FROM news WHERE published_at < :cutoff"
        ), {"cutoff": cutoff})
        await s.commit()
        print(f"✅ 已删除 {result.rowcount} 条过时新闻")


asyncio.run(cleanup())
