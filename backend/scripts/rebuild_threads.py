#!/usr/bin/env python
"""世界线数据清洗（方案 3）：修掉被泛化实体污染的存量线。

背景
----
8-K 这类 SEC 披露表单编号在早期没有进黑名单，回填后累计 39 次提及冲上
实体库第 2 位。因为它是「文件类型」而非事件主体，所有提交 8-K 的事件都
共享这个实体 → E > 0 恒成立 → 全部被串进同一条线，标题还冻结成
「CECO Environmental 提交 8-K」。

黑名单（entity_writer.GENERIC_ENTITIES / settings.ENTITY_SOURCE_BLOCKLIST）
现在已补齐，但**只对新写入生效**：已落库的 entities.is_generic 仍为 false，
历史污染不会自动消失。本脚本做三件事：

  阶段 1  rescan    重扫 entities，把命中当前黑名单的卡标 is_generic=true
  阶段 2  unbind    把污染线从终态/冻结态释放：清空 thread_events，
                    让事件重新回到「待归线」状态（幂等，可反复跑）
  阶段 3  rebuild   调 backfill_threads 的事件遍历逻辑重新归线，
                    再跑 thread_profile.refresh_all_threads 重建画像

★ 为什么阶段 2 要整线解绑而不是只摘被污染的章节：
  一条被污染的线里，几乎每一章都是靠泛化实体挂进来的，逐章判断成本极高
  且判不准。整线解绑 + 重新归线，让修正后的打分器重新决定每章归属，
  比人工挑章节更符合「算法服从修正后规则」的治理原则。

三个阶段可单独执行，默认全跑。--dry-run 只报告不写库。

用法
----
    python scripts/rebuild_threads.py --dry-run        # 只看会动多少
    python scripts/rebuild_threads.py --stage rescan   # 只重扫黑名单
    python scripts/rebuild_threads.py --only-thread <uuid>   # 只清一条线
    python scripts/rebuild_threads.py                  # 全量重建
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session  # noqa: E402
from app.services.entity_writer import GENERIC_ENTITIES  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("rebuild_threads")


def _blacklist() -> list[str]:
    """合并静态泛化表与信源黑名单，得到本次要标 generic 的实体名集合。"""
    names = {n for n in GENERIC_ENTITIES if n}
    names |= {n for n in (settings.ENTITY_SOURCE_BLOCKLIST or []) if n}
    return sorted(names)


async def stage_rescan(dry_run: bool) -> int:
    """阶段 1：把命中当前黑名单的历史实体标 is_generic=true。

    幂等：已标过的重复执行不产生新变更。
    只标不删——实体层铁律「永不删除实体卡」，删卡会让历史关联失去引用。
    """
    names = _blacklist()
    sql = text("""
        UPDATE entities
        SET is_generic = true
        WHERE canonical_name = ANY(:names)
          AND COALESCE(is_generic, false) = false
    """)
    if dry_run:
        probe = text("""
            SELECT canonical_name, COALESCE(mention_count, 0)
            FROM entities
            WHERE canonical_name = ANY(:names)
              AND COALESCE(is_generic, false) = false
            ORDER BY mention_count DESC
        """)
        async with async_session() as s:
            rows = (await s.execute(probe, {"names": names})).all()
        for n, mc in rows:
            logger.info("  [将标记] %s（mention_count=%s）", n, mc)
        logger.info("DRY RUN：待标记实体 %d 个", len(rows))
        return len(rows)

    async with async_session() as s:
        res = await s.execute(sql, {"names": names})
        await s.commit()
    logger.info("阶段 1 完成：标记 is_generic 实体 %d 个", res.rowcount or 0)
    return int(res.rowcount or 0)


async def stage_unbind(dry_run: bool, only_thread: uuid.UUID | None) -> int:
    """阶段 2：解绑被污染的线，让事件回到待归线状态。

    默认只解绑「审计判定的可疑线」（多章但无跨章共性实体）——
    这是精准清洗，不会误伤正常线。

    解绑前把原线状态置 split 并留痕：直接删 thread_events 而不留痕，
    会让「这条线为什么消失」永久不可追溯，违反治理审计铁律。
    """
    if only_thread:
        targets = [only_thread]
    else:
        from app.services import thread_profile
        rows = await thread_profile.audit_threads(min_chapters=3, limit=1000)
        targets = [uuid.UUID(r["thread_id"]) for r in rows]

    if not targets:
        logger.info("阶段 2：无可疑线，跳过")
        return 0

    for tid in targets:
        async with async_session() as s:
            info = (await s.execute(
                text("SELECT title, chapter_count FROM threads WHERE id = :t"),
                {"t": tid},
            )).mappings().first()
            if not info:
                continue
            if not dry_run:
                logger.info(
                    "  解绑 [chapters=%s] %s",
                    info["chapter_count"], (info["title"] or "")[:50],
                )
            else:
                logger.info(
                    "  [将解绑] [chapters=%s] %s",
                    info["chapter_count"], (info["title"] or "")[:50],
                )

    if dry_run:
        logger.info("DRY RUN：待解绑线 %d 条（章节将回到待归线状态）", len(targets))
        return len(targets)

    for tid in targets:
        async with async_session() as s:
            await s.execute(
                text("DELETE FROM thread_events WHERE thread_id = :t"), {"t": tid}
            )
            await s.execute(
                text("UPDATE threads SET chapter_count = 0 WHERE id = :t"), {"t": tid}
            )
            # 留痕后把线置终态 split：不留痕会让这次清洗不可追溯。
            # 置 split 而非删除，保留重定向指针，符合「合并/拆分是单向不可逆」的语义。
            await s.execute(text("""
                INSERT INTO thread_operations
                    (thread_id, operation, target_type, target_id,
                     operator, reason, payload)
                VALUES (:t, 'split', 'thread', :t, 'auto:rebuild_threads', :why,
                        CAST(:p AS jsonb))
            """), {
                "t": tid,
                "why": "泛化实体污染：多章无跨章共性实体，整线解绑重建",
                "p": '{"auto": true}',
            })
            await s.execute(
                text("UPDATE threads SET status = 'split' WHERE id = :t"), {"t": tid}
            )
            await s.commit()

    logger.info("阶段 2 完成：解绑线 %d 条", len(targets))
    return len(targets)


async def stage_rebuild(dry_run: bool) -> int:
    """阶段 3：重新归线 + 重建线画像。

    复用 backfill_threads 的遍历逻辑（按事件时间升序，避免并发建线竞争），
    保证与增量链路同一口径，不另写一套打分或排序。
    """
    from scripts.backfill_threads import (
        MAX_CONCURRENCY, get_pending_event_ids, process_one,
    )

    if settings.THREAD_ROUTING_SHADOW:
        logger.warning("=" * 60)
        logger.warning("影子模式仍开启：本次只会算分留痕，事件不会真正挂线。")
        logger.warning("请先设置 THREAD_ROUTING_SHADOW=false 并重启 alpha-web。")
        logger.warning("=" * 60)

    items = await get_pending_event_ids("asc")
    logger.info("待重新归线事件：%d", len(items))
    if dry_run:
        logger.info("DRY RUN：不执行归线")
        return len(items)
    if not items:
        logger.info("阶段 3：无待归线事件，跳过")
        return 0

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    ok = fail = 0
    for eid, ts in items:
        good, err = await process_one(sem, eid if isinstance(eid, uuid.UUID)
                                      else uuid.UUID(str(eid)), ts)
        ok += bool(good)
        fail += (not good)
        if err:
            logger.warning("  fail %s: %s", eid, err)

    from app.services import thread_profile
    out = await thread_profile.refresh_all_threads()
    logger.info(
        "阶段 3 完成：归线成功 %d、失败 %d；画像重算 %d 条线（改标题 %d，仍可疑 %d）",
        ok, fail, out["total"], out["changed_title"], len(out["suspicious"]),
    )
    return ok


async def main() -> int:
    ap = argparse.ArgumentParser(description="世界线数据清洗（泛化实体污染）")
    ap.add_argument("--stage", choices=["rescan", "unbind", "rebuild", "all"],
                    default="all")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写库")
    ap.add_argument("--only-thread", type=uuid.UUID, default=None,
                    help="阶段 2 只清洗指定线")
    args = ap.parse_args()

    logger.info("=" * 60)
    logger.info("世界线数据清洗  stage=%s dry_run=%s", args.stage, args.dry_run)
    logger.info("黑名单规模：%d", len(_blacklist()))
    logger.info("=" * 60)

    if args.stage in ("rescan", "all"):
        await stage_rescan(args.dry_run)
    if args.stage in ("unbind", "all"):
        await stage_unbind(args.dry_run, args.only_thread)
    if args.stage in ("rebuild", "all"):
        await stage_rebuild(args.dry_run)

    logger.info("=" * 60)
    logger.info("清洗流程结束")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
