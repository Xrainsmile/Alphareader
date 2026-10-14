"""merge: b7c3d4e5f6a8 + z6f7a8b9_route_scores_gate

Revision ID: e376a9bd0804
Revises: b7c3d4e5f6a8, z6f7a8b9_route_scores_gate
Create Date: 2026-10-14 10:01:08.923734

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e376a9bd0804'
down_revision: Union[str, Sequence[str], None] = ('b7c3d4e5f6a8', 'z6f7a8b9_route_scores_gate')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
