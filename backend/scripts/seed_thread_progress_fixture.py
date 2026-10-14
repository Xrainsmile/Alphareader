"""世界线进展 · 本地 UI 形态验证假数据（可回滚）。

用途：本机库是空的（news_digests/threads/thread_events 全 0），
无法看到「世界线进展」区块的实际渲染形态。本脚本造一组最小可渲染数据。

★ 全部数据带 _fixture_ 标记，一条 SQL 即可清干净（见文件末尾 CLEANUP）。
★ 不碰任何已有数据（本机 events 有 1 条真实事件，不动它）。

构造意图（覆盖三种展示分支）：
  线1 霍尔木兹供给冲击   9章 / 本期+2  → 验证「第9章 +2」与双标题
  线2 美联储降息路径     5章 / 本期+1  → 验证单条标题
  线3 也门-沙特军事对抗  3章 / 本期+1 / pinned → 验证置顶排序生效
  线4 仅噪声角色          4章 / 全部 noise → 验证被过滤，不应出现在列表
运行：cd backend && ./.venv/bin/python scripts/seed_thread_progress_fixture.py
清理：见文件末尾 CLEANUP_SQL
"""
import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, ".")

from sqlalchemy import text

from app.database import async_session

NOW = datetime.now(timezone.utc)
DIGEST_DATE = date.today()

# 四条线：(标题, 章数, 本期新增章节数, pinned, 是否全 noise)
THREADS = [
    ("_fixture_ 霍尔木兹供给冲击", 9, 2, False, False),
    ("_fixture_ 美联储降息路径", 5, 1, False, False),
    ("_fixture_ 也门-沙特军事对抗", 3, 1, True, False),
    ("_fixture_ 全噪声线（应被过滤）", 4, 1, False, True),
]

SECTIONS = ["must_know", "worth_watching", "ongoing_updates"]


async def main():
    async with async_session() as s:
        # ── 0. 幂等：先清旧的 fixture ──
        await s.execute(text("DELETE FROM digest_event_links WHERE digest_id IN (SELECT id FROM news_digests WHERE period_label LIKE '_fixture_%')"))
        await s.execute(text("DELETE FROM news_digests WHERE period_label LIKE '_fixture_%'"))
        await s.execute(text("DELETE FROM thread_events WHERE thread_id IN (SELECT id FROM threads WHERE title LIKE '_fixture_%')"))
        await s.execute(text("DELETE FROM threads WHERE title LIKE '_fixture_%'"))
        await s.execute(text("DELETE FROM events WHERE title LIKE '_fixture_%'"))
        await s.commit()

        # ── 1. 简报 ──
        did = (await s.execute(text("""
            INSERT INTO news_digests
                (digest_date, period_label, period_start, period_end,
                 news_count, content, schema_version)
            VALUES (:d, :p, :ps, :pe, 0, '', 2)
            RETURNING id
        """), {
            "d": DIGEST_DATE,
            "p": "_fixture_morning",
            "ps": NOW - timedelta(hours=12),
            "pe": NOW,
        })).scalar()

        total_links = 0
        for ti, (title, chapters, new_n, pinned, all_noise) in enumerate(THREADS):
            # ── 2. 线 ──
            tid = uuid.uuid4()
            await s.execute(text("""
                INSERT INTO threads (id, title, status, pinned, chapter_count, last_event_at)
                VALUES (:i, :t, 'active', :p, :c, :le)
            """), {
                "i": tid, "t": title, "p": pinned, "c": chapters,
                "le": NOW - timedelta(hours=1),
            })

            # ── 3. 章节事件 ──
            # 前 (chapters - new_n) 章是历史章（不进本期简报），
            # 后 new_n 章是本期新增（写进 digest_event_links）。
            for n in range(1, chapters + 1):
                eid = uuid.uuid4()
                await s.execute(text("""
                    INSERT INTO events (id, title, summary, status, version,
                                        first_seen_at, last_updated_at)
                    VALUES (:i, :t, :sm, 'active', 1, :fs, :lu)
                """), {
                    "i": eid,
                    "t": f"_fixture_ {title.split('_fixture_ ')[1]} 第{n}章",
                    "sm": f"假数据摘要·第{n}章",
                    "fs": NOW - timedelta(days=(chapters - n + 1)),
                    "lu": NOW - timedelta(days=(chapters - n + 1)),
                })

                role = "noise" if all_noise else "core"
                await s.execute(text("""
                    INSERT INTO thread_events
                        (id, thread_id, event_id, role, chapter_id, chapter_no,
                         chapter_seq, assigned_by, snapshot_title, snapshot_summary,
                         occurred_at)
                    VALUES (:i, :th, :e, :r, :ci, :cn, :cs, 'manual', :st, :ss, :oa)
                """), {
                    "i": uuid.uuid4(), "th": tid, "e": eid, "r": role,
                    "ci": uuid.uuid4(),
                    "cn": n, "cs": n,
                    "st": f"{title.split('_fixture_ ')[1]}·第{n}章",
                    "ss": f"假数据·第{n}章",
                    "oa": NOW - timedelta(days=(chapters - n + 1)),
                })

                # 本期新增章节 → 挂进简报
                if n > chapters - new_n:
                    await s.execute(text("""
                        INSERT INTO digest_event_links (digest_id, event_id, section, rank)
                        VALUES (:d, :e, :sec, :rk)
                    """), {
                        "d": did, "e": eid,
                        "sec": SECTIONS[(n + ti) % len(SECTIONS)],
                        "rk": total_links,
                    })
                    total_links += 1

        await s.execute(text(
            "UPDATE news_digests SET news_count = :n WHERE id = :d"
        ), {"n": total_links, "d": did})
        await s.commit()

        print(f"OK  digest_id = {did}")
        print(f"    简报条目 {total_links} 条，线 {len(THREADS)} 条（1 条全 noise 应被过滤）")
        print(f"\n验证：curl -s -H 'X-API-Key: $KEY' "
              f"http://localhost:8000/api/v1/workbench/digests/{did}/thread-progress")


if __name__ == "__main__":
    asyncio.run(main())

# ══════════════ CLEANUP_SQL（验证完跑一遍即可清干净）══════════════
# DELETE FROM digest_event_links WHERE digest_id IN (SELECT id FROM news_digests WHERE period_label LIKE '_fixture_%');
# DELETE FROM news_digests WHERE period_label LIKE '_fixture_%';
# DELETE FROM thread_events WHERE thread_id IN (SELECT id FROM threads WHERE title LIKE '_fixture_%');
# DELETE FROM threads WHERE title LIKE '_fixture_%';
# DELETE FROM events WHERE title LIKE '_fixture_%';
