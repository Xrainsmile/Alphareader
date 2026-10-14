#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""世界线「人工/模型基线」聚合器（Ground-Truth Baseline）。

目的
----
绕过 backend/app/services/thread_router.py 的 S=0.55E+0.30M+0.15R 打分算法，
用 curated 主题规则表把历史事件一次性重组成世界线，写入生产库，作为：
  1) 算法评估的 ground truth；
  2) 算法重建（rebuild_threads.py）的比对基底；
  3) 后续 P0/P1/P2 改造的效果基准。

血缘标记：写入的 thread_events.assigned_by = 'manual'，可与 'auto' 区分。

用法
----
    # 1) 导出事件（生产库）
    #    psql -c "\\copy (SELECT ...) TO STDOUT" > events.tsv
    # 2) 先看报告，不写库
    python curate_threads_baseline.py --events events.tsv --report --report-out report.md
    # 3) 生成 SQL
    python curate_threads_baseline.py --events events.tsv --emit-sql out.sql
    # 4) 上机执行
    psql -f out.sql

事件 TSV 格式（无表头）： event_id | title | date | entities(逗号分隔)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime

# 固定命名空间 → 同一 thread_key 每次生成相同 UUID，脚本可重复执行
THREAD_NS = uuid.UUID("0f9c1a2e-5d3b-4c7a-8e1f-2b6d4a9c7e13")
BASELINE_TAG = "manual-baseline-2026-10-14"

# ---------------------------------------------------------------------------
# 主题规则表：(key, 标题, 争夺标的, 机制, [正则])
# 数组顺序 = 匹配优先级，越靠前越优先。
# ---------------------------------------------------------------------------
THREADS: list[tuple[str, str, str, str, list[str]]] = [
    ("T01", "霍尔木兹海峡封锁与美伊博弈", "霍尔木兹海峡通航权", "地缘对抗→制裁反制→通航谈判", [
        r"霍尔木兹", r"美伊", r"伊朗", r"革命卫队", r"曼德海峡", r"对伊", r"伊核", r"德黑兰",
    ]),
    ("T03", "胡塞武装袭击沙特能源设施", "沙特能源设施安全", "第三方袭击→设施损毁→供给扰动", [
        r"胡塞", r"吉赞", r"艾卜哈", r"沙特.*(机场|炼油|遇袭|遭袭|袭击|设施|油轮)",
        r"利雅得.*(袭|机场)", r"油轮.*袭", r"袭击.*油轮",
    ]),
    ("T02", "原油供给冲击与价格传导", "国际原油定价", "供给中断→价格→官方售价调整", [
        r"油价", r"原油", r"布伦特", r"WTI", r"OPEC", r"欧佩克", r"EIA", r"IEA",
        r"石油", r"天然气", r"炼油", r"汽油", r"柴油", r"燃油", r"油田", r"油服",
        r"裂解", r"官方售价", r"输油管道", r"ADNOC", r"沙特阿美", r"雪佛龙", r"埃克森",
        r"康菲", r"西方石油", r"挪威国油", r"哈萨克斯坦", r"钻井", r"油气",
    ]),
    ("T13", "Moderna/默沙东mRNA肿瘤疫苗", "mRNA肿瘤疫苗商业化", "III期成功→估值重估→板块扩散", [
        r"Moderna", r"莫德纳", r"默沙东", r"mRNA", r"黑色素瘤", r"疫苗",
    ]),
    ("T12", "SpaceX资本运作与频谱扩张", "SpaceX估值与频谱资源", "融资→频谱/芯片采购→估值重估", [
        r"SpaceX", r"马斯克", r"Starlink", r"星链", r"频谱",
    ]),
    ("T20", "泡泡玛特增长争议", "泡泡玛特增长预期", "高增→下调指引→多空评级战", [
        r"泡泡玛特",
    ]),
    ("T19", "小米业绩与玄戒芯片", "小米自研芯片进展", "业绩→自研芯片→股价重估", [
        r"小米", r"玄戒", r"卢伟冰",
    ]),
    ("T14", "阿里AI云与资本运作", "阿里云AI份额", "财报→配股募资→AI基建投入", [
        r"阿里巴巴", r"淘宝", r"蚂蚁", r"阿里[^巴巴]",
    ]),
    ("T15", "腾讯回购与AI投入", "腾讯AI投入回报", "持续回购→业绩兑现→AI回报论证", [
        r"腾讯",
    ]),
    ("T25", "AI服务器与光通信硬件链", "AI硬件订单", "订单→营收→股价联动", [
        r"鸿海", r"工业富联", r"联想", r"光通信", r"中际旭创", r"PCB", r"Lumentum",
        r"浪潮信息", r"液冷", r"AI服务器",
    ]),
    ("T04", "英伟达AI算力基建版图", "AI算力供给", "资本扩张→算力锁定→生态绑定", [
        r"英伟达", r"\bAMD\b", r"英特尔", r"Lambda", r"Firmus", r"CoreWeave", r"Coreweave",
        r"Databricks", r"Groq", r"Cerebras", r"Rebellions", r"Reflection AI", r"Perplexity",
        r"数据中心", r"AI基建", r"AI融资", r"算力", r"Nebius", r"AI芯片",
    ]),
    ("T05", "存储与HBM超级周期", "存储芯片定价", "供需缺口→涨价→股价与下游成本", [
        r"美光", r"SK海力士", r"海力士", r"三星", r"闪迪", r"存储", r"HBM",
        r"NAND", r"DRAM", r"长江存储",
    ]),
    ("T06", "大模型厂商竞争", "前沿模型能力", "模型迭代→定价下探→订阅变现", [
        r"OpenAI", r"GPT", r"Anthropic", r"Claude", r"Gemini", r"DeepMind", r"Muse",
        r"Hatch", r"大模型", r"智谱", r"MiniMax", r"MINIMAX", r"前沿模型", r"Gemma",
        r"AI部门重组", r"首席科学家", r"AI审核", r"AI代理", r"智能体",
    ]),
    ("T27", "商业航天与卫星互联网", "近地轨道与发射能力", "发射/融资→星座部署→频谱争夺", [
        r"卫星", r"火箭", r"航天", r"发射", r"Rocket Lab", r"朱雀", r"商业航天",
        r"星链部署", r"太空",
    ]),
    ("T28", "全球并购与私有化", "标的公司控制权", "报价→监管审批→交割", [
        r"收购", r"洽购", r"合并", r"并购", r"私有化", r"要约", r"出售.{0,6}业务",
        r"收购.{0,8}股权", r"重组方案", r"分拆",
    ]),
    ("T30", "矿业与工业金属", "工业金属价格", "供给扰动→价格→矿企业绩", [
        r"必和必拓", r"铜", r"铁矿石", r"铝业", r"锂业", r"洛阳钼业", r"五矿",
        r"冶炼", r"矿区", r"钴", r"镍", r"有色金属",
    ]),
    ("T16", "谷歌TPU与定制AI芯片", "定制AI芯片", "自研→外供→生态绑定", [
        r"TPU", r"Marvell", r"迈威尔", r"博通", r"Fractile", r"自研芯片", r"定制芯片",
    ]),
    ("T18", "台积电先进制程与AI代工", "先进制程产能", "营收→产能扩张→股价重估", [
        r"台积电", r"新台币", r"中芯国际", r"华虹", r"晶圆", r"代工", r"阿斯麦", r"先进制程",
    ]),
    ("T17", "Robotaxi与自动驾驶商业化", "自动驾驶商业化", "试点→监管审查→规模扩张", [
        r"Robotaxi", r"robotaxi", r"Cybercab", r"自动驾驶", r"小马智行", r"Apollo",
        r"Waymo", r"Zoox", r"机器人出租", r"无人出租",
    ]),
    ("T10", "比特币与加密资产", "比特币价格", "突破→空头清算→机构持仓", [
        r"比特币", r"加密", r"Circle", r"Coinbase", r"稳定币", r"BTC",
    ]),
    ("T11", "黄金避险行情", "黄金价格", "地缘+实际利率→避险配置", [
        r"黄金", r"金价", r"贵金属", r"铂金", r"紫金", r"招金", r"山金",
    ]),
    ("T09", "美加关税摩擦", "北美汽车与钢铝关税", "加征→反制→豁免谈判", [
        r"美加", r"加拿大.*关税", r"汽车关税", r"钢铝关税", r"Keystone", r"对加拿大",
        r"加征关税", r"反制关税",
    ]),
    ("T23", "稀土与关键矿产", "稀土定价权", "出口管制→产业投资→价格", [
        r"稀土", r"关键矿产", r"北方稀土", r"MP Materials",
    ]),
    ("T24", "波音订单与劳资", "波音交付与劳资", "大订单→劳资谈判→交付风险", [
        r"波音", r"F-15", r"罢工",
    ]),
    ("T07", "美联储政策路径与通胀", "联邦基金利率路径", "数据→预期→政策→资产重定价", [
        r"美联储", r"CPI", r"非农", r"通胀", r"加息", r"降息", r"初请",
        r"库克", r"戴利", r"施密德", r"哈玛克", r"消费者信心", r"核心PCE", r"联邦基金",
    ]),
    ("T08", "全球长端利率与主权债供给", "长端利率定价", "财政供给→期限溢价→全球传导", [
        r"国债收益率", r"美债", r"国债", r"债券", r"收益率", r"赤字", r"主权信用",
    ]),
    ("T26", "AI应用软件与云厂商变现", "AI软件变现", "AI收入→指引修正→股价分化", [
        r"微软", r"Salesforce", r"CrowdStrike", r"Snowflake", r"甲骨文", r"思科",
        r"戴尔", r"Adobe", r"SAP", r"Palantir", r"云厂商", r"金山云", r"网络安全",
    ]),
    ("T21", "海外经济数据与央行政策", "主要经济体政策利率", "数据→通胀→利率决议", [
        r"日本", r"德国", r"法国", r"英国", r"欧元区", r"欧洲央行", r"澳洲", r"澳大利亚",
        r"新西兰", r"韩国", r"印度", r"巴西", r"意大利", r"西班牙", r"加拿大", r"瑞士",
        r"俄罗斯", r"越南", r"IMF", r"欧元",
    ]),
    ("T22", "中国宏观政策与数据", "国内增长与流动性", "数据→增量政策→流动性", [
        r"人民银行", r"央行", r"财政部", r"LPR", r"MLF", r"逆回购", r"发改委",
        r"工信部", r"商务部", r"中汽协", r"外汇局", r"统计局", r"我国", r"国内",
        r"中国\d+月", r"中国上半年", r"金融监管总局", r"证监会", r"国常会",
    ]),
]

# ---------------------------------------------------------------------------
# 噪声池：不构成世界线，不建线
# ---------------------------------------------------------------------------
NOISE: list[tuple[str, str, list[str]]] = [
    ("N1", "信息披露（8-K/监管文件）", [r"8-K", r"8-k", r"8K\b", r"8-K/A"]),
    ("N3", "投行评级与目标价调整", [r"目标价", r"评级", r"跑赢行业", r"上调至", r"下调至"]),
    ("N2", "市场快照（指数/板块/开盘收盘）", [
        r"开盘", r"收盘", r"收涨", r"收跌", r"领涨", r"领跌", r"走强", r"走弱",
        r"下挫", r"翻红", r"低开", r"高开", r"异动", r"盘中", r"夜盘", r"盘初",
        r"盘前", r"盘后", r"指数", r"板块", r"ETF", r"成交额", r"涨超", r"跌超",
        r"大涨", r"大跌", r"港股", r"A股", r"美股",
    ]),
    ("N4", "个股杂讯（一过性，不构成叙事线）", [
        r"业绩", r"财报", r"半年报", r"中报", r"净利", r"营收", r"盈利", r"亏损",
        r"派息", r"股息", r"回购", r"预增", r"预减", r"盈喜", r"盈警", r"定增",
        r"招股", r"IPO", r"复牌", r"停牌", r"董事.{0,4}离任", r"退市", r"股价",
        r"个股", r"同日", r"创.{0,4}新高", r"创新高", r"创纪录", r"诉讼", r"起诉",
        r"裁员", r"获准", r"受理", r"批件", r"定点", r"中标", r"合同.{0,4}亿",
        r"减持", r"增持", r"持仓", r"评级", r"预测", r"预告", r"预计",
        r"生物类似药", r"授权合作", r"合作协议", r"谅解",
    ]),
]

THREAD_BY_KEY = {t[0]: t for t in THREADS}


def thread_uuid(key: str) -> str:
    return str(uuid.uuid5(THREAD_NS, "alphareader:thread:" + key))


def load_events(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            rows.append({
                "id": parts[0].strip(),
                "title": parts[1].strip(),
                "date": parts[2].strip(),
                "entities": [e.strip() for e in parts[3].split(",") if e.strip()] if len(parts) > 3 else [],
            })
    # 去掉 psql \copy 可能带的表头
    if rows and rows[0]["id"] == "id":
        rows = rows[1:]
    return rows


def classify(title: str):
    """返回 (kind, key)；kind ∈ {'thread','noise','unclassified'}"""
    for key, _label, pats in NOISE[:1]:          # N1 最高优先：8-K 恒为噪声
        for p in pats:
            if re.search(p, title):
                return "noise", key
    for key, _t, _a, _m, pats in THREADS:
        for p in pats:
            if re.search(p, title, re.I):
                return "thread", key
    for key, _label, pats in NOISE[1:]:
        for p in pats:
            if re.search(p, title):
                return "noise", key
    return "unclassified", "-"


def build(events: list[dict]):
    assign = defaultdict(list)     # thread_key -> [event]
    noise = defaultdict(list)
    uncl = []
    for ev in events:
        kind, key = classify(ev["title"])
        if kind == "thread":
            assign[key].append(ev)
        elif kind == "noise":
            noise[key].append(ev)
        else:
            uncl.append(ev)
    for k in assign:
        assign[k].sort(key=lambda e: (e["date"], e["id"]))
    for k in noise:
        noise[k].sort(key=lambda e: (e["date"], e["id"]))
    return assign, noise, uncl


def q(s: str) -> str:
    return "'" + (s or "").replace("'", "''") + "'"


def emit_sql(assign, path: str):
    out = []
    w = out.append
    w("-- 世界线人工基线重建 %s" % BASELINE_TAG)
    w("-- 生成时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    w("BEGIN;")
    w("")
    w("-- 0) 备份（保留旧线，可回滚）")
    for tbl in ("threads", "thread_events", "thread_operations",
                "thread_transmissions", "thread_watchpoints", "thread_route_scores"):
        bak = "%s_bak_20261014" % tbl
        w("DROP TABLE IF EXISTS public.%s;" % bak)
        w("CREATE TABLE public.%s AS SELECT * FROM public.%s;" % (bak, tbl))
    w("")
    w("-- 1) 清空旧线（子表 ON DELETE CASCADE）")
    w("DELETE FROM public.thread_route_scores;")
    w("DELETE FROM public.thread_operations;")
    w("DELETE FROM public.thread_transmissions;")
    w("DELETE FROM public.thread_watchpoints;")
    w("DELETE FROM public.thread_events;")
    w("DELETE FROM public.threads;")
    w("")
    w("-- 2) 写入世界线")
    for key, title, asset, mech, _p in THREADS:
        evs = assign.get(key) or []
        if not evs:
            continue
        w("INSERT INTO public.threads (id,title,contested_asset,mechanism_key,status,"
          "chapter_count,core_entities,last_event_at,created_at,updated_at) VALUES (")
        w("  %s, %s, %s, %s, 'embryo', 0, NULL, NULL, now(), now()" % (
            q(thread_uuid(key)), q(title), q(asset), q(mech)))
        w(") ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, "
          "contested_asset=EXCLUDED.contested_asset, mechanism_key=EXCLUDED.mechanism_key;")
    w("")
    w("-- 3) 写入章节（assigned_by='manual' 标记血缘）")
    for key, _t, _a, _m, _p in THREADS:
        evs = assign.get(key) or []
        for i, ev in enumerate(evs, start=1):
            w("INSERT INTO public.thread_events "
              "(thread_id,event_id,role,chapter_no,chapter_seq,assigned_by,match_score,"
              "snapshot_title,occurred_at) VALUES (")
            w("  %s, %s, 'core', %d, %d, 'manual', 1.0, %s, %s::date" % (
                q(thread_uuid(key)), q(ev["id"]), i, i,
                q(ev["title"][:200]), q(ev["date"])))
            w(") ON CONFLICT (thread_id, event_id) DO NOTHING;")
    w("")
    w("-- 4) 回写统计与状态")
    w("UPDATE public.threads t SET")
    w("  chapter_count = c.n,")
    w("  last_event_at = c.mx,")
    w("  core_entities = c.ce,")
    w("  status = CASE WHEN c.n >= 3 THEN 'active' ELSE 'embryo' END,")
    w("  updated_at = now()")
    w("FROM (")
    w("  SELECT te.thread_id, COUNT(*) AS n, MAX(te.occurred_at) AS mx,")
    w("         (SELECT jsonb_object_agg(k, v) FROM (")
    w("            SELECT en.canonical_name AS k, COUNT(*) AS v")
    w("            FROM public.thread_events te2")
    w("            JOIN public.event_entities ee ON ee.event_id = te2.event_id")
    w("            JOIN public.entities en ON en.id = ee.entity_id")
    w("            WHERE te2.thread_id = te.thread_id")
    w("            GROUP BY en.canonical_name ORDER BY v DESC LIMIT 5")
    w("         ) s) AS ce")
    w("  FROM public.thread_events te GROUP BY te.thread_id")
    w(") c WHERE c.thread_id = t.id;")
    w("")
    w("COMMIT;")
    w("")
    w("-- 校验")
    w("-- SELECT status, COUNT(*) FROM public.threads GROUP BY status;")
    w("-- SELECT COUNT(*) FROM public.thread_events WHERE assigned_by='manual';")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return path


def report(assign, noise, uncl, total, out_path: str):
    NOISE_LABEL = {k: lab for k, lab, _ in NOISE}
    L = []
    w = L.append
    routed = sum(len(v) for v in assign.values())
    w("# 世界线人工基线报告（%s）" % BASELINE_TAG)
    w("")
    w("生成时间：%s　事件总数：**%d**" % (datetime.now().strftime("%Y-%m-%d %H:%M"), total))
    w("")
    w("## 一、总览")
    w("")
    w("| 项 | 数值 |")
    w("|---|---|")
    w("| 事件总数 | %d |" % total)
    w("| 建线数 | %d |" % len(assign))
    w("| 入线事件 | %d（%.1f%%） |" % (routed, 100.0 * routed / max(total, 1)))
    for k in ("N1", "N3", "N2", "N4"):
        w("| 噪声池 %s %s | %d（%.1f%%） |" % (k, NOISE_LABEL[k], len(noise.get(k, [])),
                                              100.0 * len(noise.get(k, [])) / max(total, 1)))
    w("| 未分类 | %d（%.1f%%） |" % (len(uncl), 100.0 * len(uncl) / max(total, 1)))
    w("")
    w("## 二、世界线清单")
    w("")
    w("| 编号 | 世界线 | 争夺标的 | 机制 | 章数 | 起 | 止 | 核心实体 |")
    w("|---|---|---|---|---|---|---|---|")
    for key, title, asset, mech, _p in THREADS:
        evs = assign.get(key) or []
        if not evs:
            continue
        ent = Counter()
        for e in evs:
            ent.update(e["entities"])
        top = "、".join(n for n, _ in ent.most_common(5)) or "—"
        w("| %s | %s | %s | %s | %d | %s | %s | %s |" % (
            key, title, asset, mech, len(evs), evs[0]["date"], evs[-1]["date"], top))
    w("")
    w("## 三、各线章节抽样")
    w("")
    for key, title, asset, mech, _p in THREADS:
        evs = assign.get(key) or []
        if not evs:
            continue
        w("### %s %s（%d 章）" % (key, title, len(evs)))
        w("")
        w("争夺标的：%s　机制：%s" % (asset, mech))
        w("")
        step = max(1, len(evs) // 8)
        for e in evs[::step][:8]:
            w("- `%s` %s" % (e["date"], e["title"]))
        w("")
    w("## 四、未分类事件（需补规则）")
    w("")
    for e in uncl[:60]:
        w("- `%s` %s" % (e["date"], e["title"]))
    if len(uncl) > 60:
        w("- …… 另有 %d 条" % (len(uncl) - 60))
    w("")
    text = "\n".join(L)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--emit-sql")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--report-out")
    a = ap.parse_args()

    events = load_events(a.events)
    assign, noise, uncl = build(events)
    print("事件 %d → 线 %d，入线 %d，噪声 %d，未分类 %d" % (
        len(events), len(assign), sum(len(v) for v in assign.values()),
        sum(len(v) for v in noise.values()), len(uncl)), file=sys.stderr)

    if a.report:
        text = report(assign, noise, uncl, len(events), a.report_out)
        if not a.report_out:
            print(text)
        else:
            print("报告已写入 %s" % a.report_out, file=sys.stderr)
    if a.emit_sql:
        p = emit_sql(assign, a.emit_sql)
        print("SQL 已写入 %s" % p, file=sys.stderr)


if __name__ == "__main__":
    main()
