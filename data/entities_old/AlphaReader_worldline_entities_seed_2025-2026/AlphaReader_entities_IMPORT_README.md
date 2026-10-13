# AlphaReader 世界线实体库（离线种子）

## 生成范围与边界
- 观察窗口：2025-10-13 至 2026-10-13；以该时间段内公开报道所聚焦的国际议题选取**长生命周期主体及可交易链条锚点**。
- 252 个实体、27 个新闻主题，实体不表示“首次在这一年诞生”，部分是持续存在的国家机构、海峡、资产和商品。
- 工作簿【entities_导入】及 CSV **严格按当前代码 `app/models/entity.py` 的 11 个数据库列**编排；【研究说明】是人工审查辅助数据（包括 200 字以内描述、机制、新闻主题、来源），不在当前数据库表内。
- 新闻链接属于**主题相关性的来源**，不保证每个实体在对应报道中逐字出现；不是事实关联表 `event_entities` 的证据。
- 首次/末次观察时间、提及次数是 AlphaReader 生产观测值，离线历史新闻抽样无法推算；故种子 `mention_count=0`，`first_seen_at`、`last_seen_at`、`embedding`、`embedding_model` 留空。
- `created_at` 留空，让导入器使用数据库时间 `now()`；重复导入不覆盖生产统计或向量。

## 导入
1. 备份线上数据库，并先用测试库验证。
2. 把 `AlphaReader_entities_seed_2025-2026.csv` 放到服务器可读路径。
3. 把 `import_entities_seed.py` 放到 `backend/scripts/`（或把它放在后端工作目录下运行）。
4. 在正确的 Python 环境/项目后端根目录运行：
   `python scripts/import_entities_seed.py /path/to/AlphaReader_entities_seed_2025-2026.csv`
   验证无误后再加 `--apply`。
5. 导入器以 `canonical_name` UPSERT：已有行 **不覆盖** `id`、`mention_count`、`first_seen_at`、`last_seen_at`、`created_at`、`embedding`、`embedding_model`、`is_generic`；合并别名，填补缺失类型。
6. 导入器仅灌 `entities`；缺少真实 `events.id`，不能伪造 `event_entities` 外键。后续实际事件由原有 writer 负责绑定。

## 必须同步处理别名映射
**注意：当前 `entity_writer.canonicalize()` 仅查硬编码 `ALIAS_MAP`，并不会读取数据库 `entities.aliases`。** 单独灌入别名不会让 LLM 后续抽取的英文名自动归到种子实体。

附带 `entity_aliases_seed.py` / `AlphaReader_entities_alias_map.json`（840 个经当前 `_normalize` 规则处理的 alias-key）。建议把 `.py` 放到 `backend/app/services/entity_aliases_seed.py`，然后在 `backend/app/services/entity_writer.py` 中，原 `ALIAS_MAP` 定义**之后**加入：

```python
from app.services.entity_aliases_seed import SEED_ALIAS_MAP
ALIAS_MAP.update(SEED_ALIAS_MAP)
```

为保护 `is_generic`，`canonicalize()` 中两处 `ALIAS_MAP` 命中应统一改成：

```python
canonical = ALIAS_MAP[key]           # 或 ALIAS_MAP[raw.lower()]
return canonical, canonical in GENERIC_ENTITIES
```

此补丁对本次种子有效；长期应将 DB 的 aliases 作为权威来源，并对别名建立唯一性冲突审核流程。

## 重要诊断
- 当前 `entity_writer._normalize` 会去空格与部分中文公司后缀。种子规范名已按它预处理，原始自然写法全部保留在 aliases 里。工作簿【研究说明】仍显示常用别名。
- `GENERIC_ENTITIES` 中已有“美国/中国/欧洲/日本/全球/市场”，本种子保留 6 个供审计，`is_generic=true`，归线时应排除。
- 当前 `THREAD_MIN_MENTION_COUNT=1`。预置实体 `mention_count=0`，只有后续被真实事件提及时才计入建线门槛。这是刻意避免虚构提及频次。
- 当前实体 ORM **没有** `description` 列；研究简介单独在工作簿【研究说明】，如果想在 App 的实体卡长期展示，需要新增数据库字段与迁移。
- 导入器不创建世界线，不解决旧有孤岛线/章节归属问题。

## 验证 SQL
```sql
SELECT COUNT(*) FROM entities;
SELECT entity_type, count(*) FROM entities GROUP BY 1 ORDER BY 2 DESC;
SELECT canonical_name, aliases, mention_count, is_generic FROM entities WHERE canonical_name IN ('胡塞武装', '曼德海峡', '沙特阿美', '台积电');
SELECT canonical_name FROM entities WHERE embedding IS NULL AND mention_count = 0 LIMIT 20;
```
