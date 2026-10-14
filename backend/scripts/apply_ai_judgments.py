#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用 AI 助手（对话内）逐条判定结果，生成清洗清单。

★ 关键：本脚本**不调用任何 LLM**。判定全部来自 AI 助手在对话中
  逐条阅读标题+摘要后的人工（模型）裁决，写死在 JUDGMENTS 里。
  这样结果可复现、可追溯、可人工复核。

判定口径
--------
event（保留）：有明确主体做成了某件具体的事
    - 财报/业绩/指引发布
    - 产品发布、技术突破、发射回收成功
    - 政策/制裁/军事行动
    - 资本运作（配股、融资、回购）
    - 重大市场结构纪录（创史上最大…）
snapshot（剔除）：只是价格在动，没有原因事件
    - 纯盘面涨跌、板块联动、指数点位
    - 开盘/收盘/盘中播报
    - 个股跟随大盘且摘要明示无驱动
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/app")

SRC = "/tmp/baseline_candidates.json"
OUT = "/tmp/baseline_exclusions.json"

# AI 助手逐条判定：event_id -> (verdict, reason)
JUDGMENTS = {
    # ── event：有明确主体动作 ────────────────────────────────
    "2b6c2ca3-3772-4ae3-8250-f021a7d21abe": ("event", "微软部署自研AI芯片+苹果将发新品"),
    "cdbf6b35-ea0e-49bf-80a3-32a3eceeb851": ("event", "朱雀三号火箭陆地回收成功"),
    "131bdc65-40dc-4a45-bc68-1a5df22c1609": ("event", "创史上最大空头清算潮（市场结构纪录）"),
    "59afdc3d-9362-4974-bfd8-b685f2f07d6d": ("event", "洛阳钼业中期业绩净利增86%"),
    "573f98fd-cc9d-4730-8700-d821d7d32248": ("event", "特朗普宣布暂停对加关税"),
    "81a3f8bc-39c9-401e-b78f-7b71757a924e": ("event", "美财政部国债回购计划驱动金价"),
    "67ebff98-f9a7-4337-b7e9-ef4f7191438b": ("event", "胡塞武装再袭沙特机场"),
    "4aa0b7e7-50e6-459a-9421-d5cd85d57d9e": ("event", "胡塞袭击沙特油轮"),
    "1c51ec9c-7fb4-40fe-86c8-51f1a3c12228": ("event", "英伟达推出开源AI模型Nemotron"),
    "f8fecd4f-6da6-4383-aac9-c7b1dab9bc8b": ("event", "英伟达警告AI服务器涨价超15%"),
    "ea19649d-cd40-4c4d-821c-ddc3c0841120": ("event", "摩根士丹利上调霍尼韦尔评级"),
    "d2d68919-6979-4f3c-9544-8dc7c19b39d2": ("event", "Cerebras二季度财报不及预期"),
    "d133ffd9-68a4-4671-aea5-4d5abfe1f9fb": ("event", "CoreWeave财报营收翻倍超预期"),
    "20d953ce-da93-40af-97a9-d346457039e2": ("event", "疫苗试验结果积极驱动Moderna"),
    "94b01f30-3546-44cb-b8cf-261bfd5eb072": ("event", "SpaceX上市后首份财报营收增92%"),
    "7f098413-7587-4bb8-b874-7ca4d69a86ee": ("event", "戴尔宣布扩展AI数据平台"),
    "91d11396-3e9f-4075-8621-2c217a2ab97b": ("event", "沙特机场与油轮遇袭"),
    "e147d7e7-aae7-4f82-9358-56e1066c3c15": ("event", "Moderna mRNA肿瘤疫苗重大突破"),
    "5bbddc59-504d-41ea-8058-6133f67fc7e3": ("event", "腾讯公布业绩后下跌"),
    "9632cc3b-916c-4807-a1a9-08fc105224a7": ("event", "腾讯音乐发布业绩后跌超12%"),
    "e99702eb-1088-4ba7-9556-cbfe1e6647a0": ("event", "紫金黄金国际中期溢利增178%"),
    "5bb006b6-ba8b-4e6e-95c5-d2427beeecc2": ("event", "Lumentum业绩超预期提振板块"),
    "48b6d3a8-050c-4ba4-afda-b1436028de66": ("event", "美光CEO称需求超供给50%"),
    "fda64660-4fc5-4d29-82d0-4151e75c3570": ("event", "闪迪下季度指引不及预期"),
    "be12cf54-f06d-4029-8344-336bc65dcab8": ("event", "阿里配股募资约100亿美元"),
    "6cca2796-d883-45d0-9ecc-d69173bffa19": ("event", "Moderna早期皮肤癌疫苗达主要终点，RBC上调目标价45→130美元"),

    # ── snapshot：只是价格在动 ──────────────────────────────
    "f5b87e4d-da6e-49e3-97d8-d3c9a7955f4a": ("snapshot", "三市场板块联动走强，无主体动作"),
    "69eb31ec-449b-4eef-8b9c-5c905a7d4254": ("snapshot", "币价突破+概念股拉升，纯价格"),
    "18d0843b-780c-4cbe-bd7b-ea8ad1ce396c": ("snapshot", "博通股价跌幅，无原因事件"),
    "d5aba3de-d791-4343-a7d0-3614b7df66eb": ("snapshot", "股价创单日跌幅，驱动为市场担忧"),
    "a729c3f9-47b7-49ce-9837-31dfa6b5b28e": ("snapshot", "油价日内波动，摘要明示无原因"),
    "7921638a-78ff-43d1-8748-6cad45dba442": ("snapshot", "智谱股价大跌，原因未披露"),
    "78fd1ee7-0061-44c5-b3b3-43044c585757": ("snapshot", "标普破7800点+存储概念领涨"),
    "010bbf00-754b-4614-af67-2dda4bd2a9de": ("snapshot", "比特币破7.1万+概念股普涨"),
    "c293ef69-bdeb-405e-9d64-1196489de298": ("snapshot", "比特币破7.5万，利好未明确"),
    "0d4373b7-d637-48cd-b5fb-6943fff0dce6": ("snapshot", "有色锂业股逆市走强，无驱动"),
    "6909e06f-7d14-406b-986c-be9cf5443f58": ("snapshot", "港股科技指数走强，无基本面信息"),
    "c23ac5e1-f080-4706-be8a-c179a3619956": ("snapshot", "港股科技多线走强，驱动未明"),
    "f5a86617-1e8b-4709-9354-114ff9999232": ("snapshot", "股价新高，驱动为试乘预期未发生"),
    "a7ecbfdc-eb0c-4541-9157-a74b4ffe05af": ("snapshot", "金价突破4300+黄金股走强"),
    "b1933df6-7a7b-45c2-83ea-fbbd1919878a": ("snapshot", "加密概念股全线走强"),
    "7a0ccdb5-1a1d-4d46-afac-9da968862d41": ("snapshot", "存储板块普跌"),
    "bd880ac3-d999-495c-a13a-6ff187bf5c5a": ("snapshot", "两板块创新高，驱动未披露"),
    "baba00a4-b03f-42bc-aad5-701dd64179e7": ("snapshot", "英伟达戴尔股价齐创新高"),
    "c2421f0e-c7c0-4d41-8eb4-a1bd9dd9fdf3": ("snapshot", "A股三大指数全线翻红"),
    "98dbd6bb-308f-4110-9e77-2f02ab2d5d4e": ("snapshot", "A股翻红+存储MLCC领涨"),
    "fe5d1e01-31d7-4923-8acf-3bcb336b09d6": ("snapshot", "A股港股开盘走强"),
    "8f488c86-1e24-4054-812f-1d0cf56507a0": ("snapshot", "A股港股收涨，无政策数据变化"),
    "6b49a1cc-4168-4dd9-b02a-5f021f5e24c7": ("snapshot", "中概光通信盘前普跌"),
    "7f42abfc-de40-482e-9ea7-51d073e9770d": ("snapshot", "创业板跌逾2%，原因未说明"),
    "3faeac9a-5e21-45c1-b802-0ff6d79908e2": ("snapshot", "台积电纳指同步创新高"),
    "b2a397e4-1ea3-4725-83cc-19ed55afe21e": ("snapshot", "港股PCB有色集体走强，触发为或然"),
    "2a905c4d-2904-405b-8836-dbe0badd6161": ("snapshot", "港股两板块早盘走强，无触发因素"),
    "8f37332b-8bed-4adf-88b6-74c90a2bbc8a": ("snapshot", "港股光通信PCB盘中走强，无驱动"),
    "ad7c19e9-65a7-48e2-9afb-6a691572b89e": ("snapshot", "港股光通信芯片大模型集体大跌"),
    "4253a56a-892c-41bf-893a-a41f2a5aad3f": ("snapshot", "港股开盘恒指科指齐涨"),
    "c1d4f531-928f-4d05-9bc7-0906f864ed2c": ("snapshot", "港股开盘齐涨+科技黄金领涨"),
    "ab02f11f-ee93-4de8-8881-3e64f89c5e32": ("snapshot", "港股开盘科技领涨有色跟涨"),
    "11af6919-7de5-428c-803a-f19a65e7ef88": ("snapshot", "恒指低开高走+小米逆市领涨"),
    "d09aa6dc-722e-4b39-b2be-2bce21ccd185": ("snapshot", "港股收涨+AI概念股领涨"),
    "c7abfbf4-33fa-454f-b68c-4315d9f269e1": ("snapshot", "港股有色走弱黄金股领跌"),
    "61283017-9936-409d-b9a4-276254b512f7": ("snapshot", "港股生物医药存储PCB集体走强"),
    "5420a2cf-f691-445b-9aa6-240edf8c7dea": ("snapshot", "港股科技铝业集体走强，无驱动"),
    "b8b5da36-eed2-4635-9a54-4fdc0392df53": ("snapshot", "港股黄金石油走强+金价4400"),
    "5bbe2f31-42e8-4b22-96be-cdd771c0edb1": ("snapshot", "美股开盘分化+存储概念上涨"),
    "95ef1b3b-f887-4bcc-af65-85be48d9b003": ("snapshot", "美股收跌+AI存储逆势走强"),
    "fbb91282-5902-4c9e-8e6d-a9f6b8367294": ("snapshot", "美股收涨+SpaceX大涨，驱动未明"),
    "34bc7ee9-59c9-43e4-bc3e-61b4bef76c25": ("snapshot", "美股收涨+银行黄金股走强"),
    "12ab84e8-314b-4820-830d-09b3593305b5": ("snapshot", "美股光通信存储集体走强，无触发"),
    "3f25f7f5-4c58-4f12-b99b-54a68b4e52e2": ("snapshot", "加密概念股盘中集体走高"),
    "288683e2-74bc-4e27-bbdf-3da04d7c38db": ("snapshot", "加密概念股集体走强"),
    "b6cfe5ca-3463-450c-9003-61bbb1d2a63d": ("snapshot", "美股半导体存储集体下挫"),
    "dd7d76c1-a3c8-4c60-92a6-d7d246694473": ("snapshot", "半导体盘中反转+英伟达新高"),
    "169e2378-d3c4-4416-84d1-48fd9fc8f300": ("snapshot", "美股科技板块普跌"),
    "4a2c7528-a0a5-47ba-be55-804ccc1442a6": ("snapshot", "美股稀土有色普涨，无触发因素"),
    "1296ea43-ca9a-4b51-ab37-af8e0a8e4e05": ("snapshot", "腾讯尾盘急跌，原因未明确"),
    "ece349ac-9ec3-4945-9075-275c5f228b6e": ("snapshot", "韩国KOSPI盘中跌3%，无原因"),
    "abf4e6fc-7709-48b8-88ec-469038d3981c": ("snapshot", "黄金异动，核心数据均未披露"),
}


def main():
    with open(SRC, encoding="utf-8") as f:
        data = json.load(f)
    cands = data["candidates"]
    n_gt = data["ground_truth_total"]

    print("=" * 74)
    print("应用 AI 助手逐条判定（未调用任何 LLM）")
    print("=" * 74)
    print(f"人工基线 {n_gt} 条｜候选 {len(cands)} 条")
    print()

    missing = [c["event_id"] for c in cands if c["event_id"] not in JUDGMENTS]
    if missing:
        print(f"⚠ {len(missing)} 条候选缺判定，默认按规则执行：")
        for m in missing:
            print(f"    {m}")
        print()

    excluded, kept = [], []
    both, rule_strict, rule_loose, agree_keep = 0, 0, 0, 0
    for c in cands:
        eid = c["event_id"]
        if eid in JUDGMENTS:
            v, reason = JUDGMENTS[eid]
        else:
            v, reason = c["rule_says"], "（缺判定，按规则）"
        c["ai"] = v
        c["ai_reason"] = reason

        r = c["rule_says"]
        if r == "snapshot" and v == "snapshot":
            both += 1
        elif r == "snapshot" and v == "event":
            rule_strict += 1          # 规则要删，AI 说该留
        elif r == "event" and v == "snapshot":
            rule_loose += 1           # 规则要留，AI 说该删
        else:
            agree_keep += 1

        rec = {"event_id": eid, "title": c["title"],
               "thread_title": c["thread_title"],
               "rule": r, "ai": v, "reason": reason}
        (excluded if v == "snapshot" else kept).append(rec)

    print("─" * 74)
    print("AI 判定 vs 规则 交叉表")
    print("─" * 74)
    print(f"  规则=快照 且 AI=快照  → 剔除         {both:>3} 条  ✅ 一致")
    print(f"  规则=快照 但 AI=事件  → 保留(规则过严) {rule_strict:>3} 条  ⚠")
    print(f"  规则=事件 但 AI=快照  → 剔除(规则过松) {rule_loose:>3} 条  ⚠")
    print(f"  规则=事件 且 AI=事件  → 保留         {agree_keep:>3} 条  ✅ 一致")
    print()
    print(f"  → 剔除 {len(excluded)} 条｜保留 {len(kept)} 条")
    print(f"  → 干净基线 {n_gt - len(excluded)} 条（原 {n_gt}）")
    print()

    if rule_strict:
        print("─" * 74)
        print("规则过严被 AI 救回的条目（这些是真事件，差点误删）")
        print("─" * 74)
        for r in [k for k in kept if k["rule"] == "snapshot"]:
            print(f"  {r['title'][:46]}")
            print(f"      → {r['reason']}")
        print()

    payload = {
        "generated_at": "2026-10-14",
        "generated_by": "AI 助手对话内逐条判定（未调用 LLM，可复现）",
        "ground_truth_total": n_gt,
        "candidates": len(cands),
        "excluded_count": len(excluded),
        "excluded": excluded,
        "kept_disagreement": [k for k in kept if k["rule"] == "snapshot"],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"清单已写入 {OUT}")


if __name__ == "__main__":
    main()
