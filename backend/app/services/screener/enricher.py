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


def _clean_code(ts_code: str) -> str:
    """将 ts_code 统一为纯 6 位数字（akshare 接口要求）。

    兼容以下输入格式：
      - '000001'    → '000001'
      - '000001.SZ' → '000001'
      - '600519.SH' → '600519'
    """
    return ts_code.split(".")[0].strip()


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
    # 建立 ticker → 纯数字代码 的映射
    code_map = {ticker: _clean_code(ticker) for ticker in codes}
    clean_codes = list(code_map.values())
    logger.info("开始数据补充: %d 只股票", len(codes))

    # 并发拉取三类数据（使用纯数字代码）
    info_map, concept_map, flow_map = {}, {}, {}
    try:
        info_map, concept_map, flow_map = await asyncio.gather(
            _fetch_stock_info_batch(clean_codes),
            _fetch_concept_batch(clean_codes),
            _fetch_fund_flow_batch(clean_codes),
        )
    except Exception as e:
        logger.warning("数据补充并发执行异常: %s", e)

    # 合并到每只股票（通过 clean_code 查找）
    for item in watchlist:
        ticker = item["ticker"]
        clean = code_map[ticker]
        info = info_map.get(clean, {})
        # name 已由 pipeline 从本地 DB 填充，仅在为空时用 akshare 兜底
        if not item.get("name"):
            item["name"] = info.get("name", "")
        item["industry"] = info.get("industry", "")
        item["main_business"] = info.get("main_business", "")
        item["concepts"] = concept_map.get(clean, "")
        item["fund_flow_net"] = flow_map.get(clean)

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

    使用东方财富 F10 核心题材接口反查每只股票的概念标签。
    过滤掉地域板块、指数成分等非题材标签，只保留有意义的概念。
    返回 {code: "低空经济, 碳纤维, ..."}
    """
    # 过滤掉的板块关键词（地域、指数、杂项）
    _SKIP_KEYWORDS = {
        "板块", "沪股通", "深股通", "融资融券", "上证", "中证", "深证",
        "创业板", "科创板", "东方财富", "昨日", "今日", "振幅",
    }

    result: dict[str, str] = {}

    def _is_useful_concept(name: str) -> bool:
        """判断概念名称是否有实际意义（过滤地域/指数/杂项）。"""
        return not any(kw in name for kw in _SKIP_KEYWORDS)

    def _fetch_all():
        import time
        import requests

        url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        for code in codes:
            try:
                params = {
                    "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
                    "columns": "BOARD_NAME",
                    "filter": f'(SECURITY_CODE="{code}")',
                    "pageSize": 50,
                    "source": "HSF10",
                    "client": "PC",
                }
                r = requests.get(url, params=params, timeout=10)
                data = r.json()
                if data.get("result") and data["result"].get("data"):
                    concepts = [
                        item["BOARD_NAME"]
                        for item in data["result"]["data"]
                        if _is_useful_concept(item.get("BOARD_NAME", ""))
                    ]
                    if concepts:
                        result[code] = ", ".join(concepts[:8])
                time.sleep(0.1)  # 控制请求频率
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
                # 根据代码判断市场：6开头=沪市(sh)，其他=深市(sz)
                market = "sh" if code.startswith("6") else "sz"
                df = ak.stock_individual_fund_flow(stock=code, market=market)
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
