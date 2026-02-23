"""refactor sandbox_analyses: replace old fields with new multi-dimension analysis

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-02-24

Remove: title, direction, summary, content, target_price, stop_loss
Add: score, trend, pattern, volume_price, discipline_action,
     risk_type, risk_price, risk_note, pnl_thinking, verdict
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c2d3e4f5g6h7"
down_revision = "b1c2d3e4f5g6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old columns
    op.drop_column("sandbox_analyses", "title")
    op.drop_column("sandbox_analyses", "direction")
    op.drop_column("sandbox_analyses", "summary")
    op.drop_column("sandbox_analyses", "content")
    op.drop_column("sandbox_analyses", "target_price")
    op.drop_column("sandbox_analyses", "stop_loss")

    # Add new columns
    op.add_column("sandbox_analyses", sa.Column("score", sa.Float(), nullable=False, server_default="0"))
    op.add_column("sandbox_analyses", sa.Column("trend", sa.String(200), nullable=False, server_default=""))
    op.add_column("sandbox_analyses", sa.Column("pattern", sa.String(200), nullable=False, server_default=""))
    op.add_column("sandbox_analyses", sa.Column("volume_price", sa.String(200), nullable=False, server_default=""))
    op.add_column("sandbox_analyses", sa.Column("discipline_action", sa.String(16), nullable=False, server_default="retain"))
    op.add_column("sandbox_analyses", sa.Column("risk_type", sa.String(8), nullable=True))
    op.add_column("sandbox_analyses", sa.Column("risk_price", sa.Float(), nullable=True))
    op.add_column("sandbox_analyses", sa.Column("risk_note", sa.String(200), nullable=True))
    op.add_column("sandbox_analyses", sa.Column("pnl_thinking", sa.String(200), nullable=False, server_default=""))
    op.add_column("sandbox_analyses", sa.Column("verdict", sa.String(200), nullable=False, server_default=""))


def downgrade() -> None:
    # Drop new columns
    op.drop_column("sandbox_analyses", "verdict")
    op.drop_column("sandbox_analyses", "pnl_thinking")
    op.drop_column("sandbox_analyses", "risk_note")
    op.drop_column("sandbox_analyses", "risk_price")
    op.drop_column("sandbox_analyses", "risk_type")
    op.drop_column("sandbox_analyses", "discipline_action")
    op.drop_column("sandbox_analyses", "volume_price")
    op.drop_column("sandbox_analyses", "pattern")
    op.drop_column("sandbox_analyses", "trend")
    op.drop_column("sandbox_analyses", "score")

    # Restore old columns
    op.add_column("sandbox_analyses", sa.Column("title", sa.String(128), nullable=False, server_default=""))
    op.add_column("sandbox_analyses", sa.Column("direction", sa.String(16), nullable=False, server_default="neutral"))
    op.add_column("sandbox_analyses", sa.Column("summary", sa.Text(), nullable=False, server_default=""))
    op.add_column("sandbox_analyses", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("sandbox_analyses", sa.Column("target_price", sa.Float(), nullable=True))
    op.add_column("sandbox_analyses", sa.Column("stop_loss", sa.Float(), nullable=True))
