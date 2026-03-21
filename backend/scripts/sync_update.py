"""纯同步版行情增量更新脚本 — 绕过 asyncio.to_thread 卡死问题。"""
import json
import logging
import os
import random
import sys
import time
import urllib.request

import pandas as pd

os.chdir("/app")
sys.path.insert(0, "/app")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger()

# ── 复用项目的数据库写入 ──
import asyncio
from app.services.data_fetcher import (
    _sync_fetch_tencent_kline,
    _tencent_code,
    clean_data,
    save_to_db,
    fetch_stock_list_from_db,
    has_today_data,
)


def main():
    # 检查是否已完整
    loop = asyncio.new_event_loop()
    done = loop.run_until_complete(has_today_data())
    if done:
        logger.info("今天数据已完整，跳过")
        return

    # 获取股票列表
    db_list = loop.run_until_complete(fetch_stock_list_from_db())
    if db_list.empty:
        logger.error("数据库无股票列表")
        return

    codes = db_list["代码"].tolist()
    names = dict(zip(db_list["代码"], db_list["名称"]))
    total = len(codes)
    logger.info("开始同步增量更新行情（最近 5 天），共 %d 只股票...", total)

    BATCH_SIZE = 500
    total_records = 0
    batch_dfs = []
    errors = 0

    for idx, code in enumerate(codes, 1):
        if idx % 100 == 0:
            logger.info("进度: %d/%d (%.1f%%), 已写入 %d 条, 错误 %d", idx, total, idx / total * 100, total_records, errors)

        try:
            df = _sync_fetch_tencent_kline(code, 5)
            if df is not None:
                df["名称"] = names.get(code, "")
                batch_dfs.append(df)
        except Exception as e:
            errors += 1
            if errors <= 5:
                logger.warning("拉取 %s 失败: %s", code, e)

        # 分批写入 DB
        if len(batch_dfs) >= BATCH_SIZE:
            batch_combined = pd.concat(batch_dfs, ignore_index=True)
            batch_clean = clean_data(batch_combined)
            if not batch_clean.empty:
                loop.run_until_complete(save_to_db(batch_clean))
                total_records += len(batch_clean)
                logger.info("批次写入 %d 条（累计 %d）", len(batch_clean), total_records)
            batch_dfs = []

        # 限速
        time.sleep(0.12 + random.uniform(0, 0.08))

    # 最后一批
    if batch_dfs:
        batch_combined = pd.concat(batch_dfs, ignore_index=True)
        batch_clean = clean_data(batch_combined)
        if not batch_clean.empty:
            loop.run_until_complete(save_to_db(batch_clean))
            total_records += len(batch_clean)

    loop.close()
    logger.info("同步增量更新完成，共 %d 条记录（%d 只股票，%d 错误）", total_records, total, errors)


if __name__ == "__main__":
    main()
