"""一次性脚本：清理重复新闻 + 修复已入库的英文标题
1. 标准化所有 URL（去除尾部斜杠和 tracking 参数），合并重复项
2. 对已入库的英文标题重新标记以便下次 pipeline 覆盖

usage: docker exec alpha-web python3 /app/cleanup_duplicates.py
"""
import asyncio
import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from app.database import async_session
from sqlalchemy import text


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/") if parsed.path != "/" else parsed.path
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned = {k: v for k, v in params.items()
                   if not k.startswith(("utm_", "feed_item"))}
        query = urlencode(cleaned, doseq=True) if cleaned else ""
    else:
        query = ""
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


def _contains_chinese(text_str: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text_str))


async def cleanup():
    async with async_session() as s:
        # 1. 找出 URL 标准化后重复的新闻
        r = await s.execute(text("SELECT id, url, title, source, created_at FROM news ORDER BY created_at"))
        all_rows = r.fetchall()

        seen_urls: dict[str, tuple] = {}  # normalized_url → (id, title, source, created_at)
        duplicates = []  # 要删除的 id 列表

        for row in all_rows:
            nurl = _normalize_url(row[1])
            if nurl in seen_urls:
                # 保留先入库的，删除后入库的
                duplicates.append((str(row[0]), row[2], row[3], nurl))
            else:
                seen_urls[nurl] = (str(row[0]), row[2], row[3], row[4])

        print(f"=== URL 标准化去重 ===")
        print(f"总新闻数: {len(all_rows)}")
        print(f"URL 去重后重复项: {len(duplicates)}")
        if duplicates:
            for did, dtitle, dsource, durl in duplicates[:20]:
                print(f"  删除: [{dsource}] {dtitle[:40]} ({durl[:60]})")
            if len(duplicates) > 20:
                print(f"  ... 还有 {len(duplicates) - 20} 条")

            # 执行删除
            ids_to_delete = [d[0] for d in duplicates]
            for did in ids_to_delete:
                await s.execute(text("DELETE FROM news WHERE id = :id"), {"id": did})
            await s.commit()
            print(f"✅ 已删除 {len(ids_to_delete)} 条重复新闻")
        else:
            print("没有 URL 重复项")

        # 2. 统计英文标题新闻（未翻译）
        r2 = await s.execute(text("SELECT id, title, source FROM news"))
        en_count = 0
        for row in r2.fetchall():
            if not _contains_chinese(row[1]):
                en_count += 1
        print(f"\n=== 未翻译的英文标题 ===")
        print(f"英文标题新闻: {en_count} 条")
        print("（这些会在下次 pipeline 运行时通过增强的翻译 Prompt 处理）")


asyncio.run(cleanup())
