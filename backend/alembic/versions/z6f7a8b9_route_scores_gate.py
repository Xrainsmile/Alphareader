"""P1c-3: thread_route_scores 增加 gate 列（实体门控否决原因）

★ 为什么必须落库：
  归线门控（E 下限 + 最少共现实体数）上线后，最需要的观测是「否决率」——
  否决率过高说明收得过紧、误杀正常归线；过低说明没起效。
  但 gate 此前只存在于 route_event() 的返回 dict 里，用完即丢，
  上线后根本无法统计，两个门限值（0.15 / 2）就永远无法标定。

★ 为什么加列而不是复用 joined：
  joined=False 有两类成因，必须能区分：
    1. S < T_JOIN（分数不够，调阈值）
    2. 被实体门控否决（调 E 下限或共现数）
  混在一起就无法判断该动哪个参数，等于白观测。

取值约定：空串 '' = 未否决（通过门控），非空 = 否决原因（如 "shared=1 < 2"）。
用空串而非 NULL：NULL 在统计时会被 COUNT 天然跳过，容易把「通过」误算成「无数据」。

幂等：IF NOT EXISTS，重跑安全。
"""

import sqlalchemy as sa
from alembic import op

revision = "z6f7a8b9_route_scores_gate"
down_revision = "z5e6f7a8_unmerge_operation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "thread_route_scores",
        sa.Column("gate", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("thread_route_scores", "gate")
