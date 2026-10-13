"""P0 实体层补：news.entity_types 列（与 entities 逐位对齐的实体类型）

背景：
e6c8748529e8 已建 entities / event_entities 表并加了 news.entities 列，
但只存实体名、无类型，导致 entities.entity_type 恒为 NULL。P1 聚类时
缺少「同名不同实体」的判据（如「苹果」是 org 还是 commodity）。

本次改动（配套代码改动）：
- llm_news_filter：4 处 prompt 改为输出 [{"name":..., "type":...}]
- 新增 _ensure_entity_pairs 解析器，兼容新旧两种格式
- pipeline 落库 news.entity_types；event_synthesizer 聚合成 name→type 映射
- entity_writer 写入 entities.entity_type（已存在的不覆盖，首次判定优先）

迁移内容：仅加一列，无其他变更。

设计：
- 与 entities 逐位对齐，无法判定的位置为 NULL（规格 3.2：未知就是 None）
- 不建索引：该列只随 news 行读取，无数组检索场景
- 不回填：旧数据类型未知，按规格不强行填

回滚：DROP COLUMN，无数据依赖。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7b1e9f4a2c33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'news',
        sa.Column('entity_types', postgresql.ARRAY(sa.String(length=24)), nullable=True),
    )
    # 列注释：与 entities 逐位对齐，类型枚举见 VALID_ENTITY_TYPES
    op.execute("""
        COMMENT ON COLUMN news.entity_types IS
        '与 entities 逐位对齐的实体类型 org/person/place/asset/commodity/concept；未判定为 NULL'
    """)


def downgrade() -> None:
    op.drop_column('news', 'entity_types')
