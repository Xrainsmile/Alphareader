"""数据补充器 — 为白名单股票补充行业、题材、主营业务、资金流向等维度。

数据来源：
  - 行业/主营业务：akshare stock_individual_info_em（同花顺个股基本信息）
  - 题材概念：akshare stock_board_concept_name_ths（同花顺概念板块成分股反查）
  - 资金流向：akshare stock_individual_fund_flow（个股资金流向）

降级策略：
  - akshare 接口失败时返回空数据，不影响 pipeline 主流程
  - 所有补充字段均为 nullable，允许部分缺失
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("alphareader.screener.enricher")


async def enrich_watchlist(watchlist: list[dict]) -> list[dict]:
    """为白名单补充行业、题材、主营业务、资金流向。

    Args:
        watchlist: pipeline 产出的白名单 list[dict]，每项至少含 ticker 字段

    Returns:
        补充后的 watchlist（原地修改并返回）
    """
    if not watchlist:
        return watchlist

    codes = [item["ticker"] for item in watchlist]
    logger.info("开始数据补充: %d 只股票", len(codes))

    # 并发拉取三类数据
    info_map, concept_map, flow_map = {}, {}, {}
    try:
        info_map, concept_map, flow_map = await asyncio.gather(
            _fetch_stock_info_batch(codes),
            _fetch_concept_batch(codes),
            _fetch_fund_flow_batch(codes),
        )
    except Exception as e:
        logger.warning("数据补充并发执行异常: %s", e)

    # 合并到每只股票
    for item in watchlist:
        code = item["ticker"]
        info = info_map.get(code, {})
        item["name"] = info.get("name", "")
        item["industry"] = info.get("industry", "")
        item["main_business"] = info.get("main_business", "")
        item["concepts"] = concept_map.get(code, "")
        item["fund_flow_net"] = flow_map.get(code)

    logger.info("数据补充完成: info=%d, concept=%d, flow=%d",
                len(info_map), len(concept_map), len(flow_map))
    return watchlist


async def _fetch_stock_info_batch(codes: list[str]) -> dict[str, dict]:
    """批量获取个股基本信息（名称、行业、主营业务）。

    使用 akshare stock_individual_info_em 接口，逐只查询。
    返回 {code: {"name": ..., "industry": ..., "main_business": ...}}
    """
    result: dict[str, dict] = {}

    def _fetch_all():
        """同步批量拉取（在线程池中执行）。"""
        try:
            import akshare as ak
        except ImportError:
            logger.warning("akshare 未安装，跳过个股信息拉取")
            return result

        for code in codes:
            try:
                # akshare 需要带市场前缀的代码，但 stock_individual_info_em 接受纯数字
                df = ak.stock_individual_info_em(symbol=code)
                if df is None or df.empty:
                    continue
                # 返回的是 key-value 两列的 DataFrame
                info_dict = dict(zip(df["item"], df["value"]))
                result[code] = {
                    "name": info_dict.get("股票简称", ""),
                    "industry": info_dict.get("行业", ""),
                    "main_business": info_dict.get("经营范围", ""),
                }
            except Exception as e:
                logger.debug("获取 %s 基本信息失败: %s", code, e)
                continue

        return result

    try:
        return await asyncio.to_thread(_fetch_all)
    except Exception as e:
        logger.warning("个股信息批量拉取异常: %s", e)
        return result


async def _fetch_concept_batch(codes: list[str]) -> dict[str, str]:
    """批量获取个股所属概念板块标签。

    使用 akshare stock_board_concept_name_ths 反查每只股票的概念标签。
    返回 {code: "低空经济, 碳纤维, ..."}
    """
    result: dict[str, str] = {}

    def _fetch_all():
        try:
            import akshare as ak
        except ImportError:
            logger.warning("akshare 未安装，跳过题材概念拉取")
            return result

        for code in codes:
            try:
                df = ak.stock_board_concept_name_ths(symbol=code)
                if df is not None and not df.empty:
                    # 取前 5 个概念，避免过长
                    concepts = df["概念名称"].tolist()[:5]
                    result[code] = ", ".join(concepts)
            except Exception as e:
                logger.debug("获取 %s 概念板块失败: %s", code, e)
                continue

        return result

    try:
        return await asyncio.to_thread(_fetch_all)
    except Exception as e:
        logger.warning("概念板块批量拉取异常: %s", e)
        return result


async def _fetch_fund_flow_batch(codes: list[str]) -> dict[str, float | None]:
    """批量获取个股资金流向（当日主力净流入，万元）。

    使用 akshare stock_individual_fund_flow 接口。
    返回 {code: 主力净流入金额(万元)}
    """
    result: dict[str, float | None] = {}

    def _fetch_all():
        try:
            import akshare as ak
        except ImportError:
            logger.warning("akshare 未安装，跳过资金流向拉取")
            return result

        for code in codes:
            try:
                df = ak.stock_individual_fund_flow(stock=code, market="")
                if df is not None and not df.empty:
                    # 取最新一天的主力净流入
                    latest = df.iloc[-1]
                    net_val = latest.get("主力净流入-净额")
                    if net_val is not None:
                        # akshare 返回的单位可能是元，转为万元
                        result[code] = round(float(net_val) / 10000, 2)
            except Exception as e:
                logger.debug("获取 %s 资金流向失败: %s", code, e)
                continue

        return result

    try:
        return await asyncio.to_thread(_fetch_all)
    except Exception as e:
        logger.warning("资金流向批量拉取异常: %s", e)
        return result
