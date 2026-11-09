"""Preserve native app handoffs alongside sportsbook web links."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("odds", sa.Column("app_link", sa.Text, nullable=True))


def downgrade():
    op.drop_column("odds", "app_link")
