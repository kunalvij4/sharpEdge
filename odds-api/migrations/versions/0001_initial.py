"""Initial normalized odds store."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "leagues",
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("route", sa.String, nullable=False),
        sa.Column("source_id", sa.String, unique=True),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("source_id", sa.String, nullable=False),
        sa.Column("league_key", sa.String, sa.ForeignKey("leagues.key"), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("home", sa.String, nullable=False),
        sa.Column("away", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.UniqueConstraint("league_key", "source_id", name="uq_event_source"),
    )
    op.create_index("ix_events_league_start", "events", ["league_key", "start"])
    op.create_table(
        "books",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("source_id", sa.String, unique=True, nullable=False),
        sa.Column("key", sa.String, unique=True, nullable=False),
        sa.Column("title", sa.String, nullable=False),
    )
    op.create_table(
        "markets",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("event_id", sa.String, sa.ForeignKey("events.id"), nullable=False),
        sa.Column("book_id", sa.String, sa.ForeignKey("books.id"), nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("period", sa.String, nullable=False),
        sa.Column("player_id", sa.String),
        sa.Column("point", sa.Numeric(18, 6)),
        sa.Column("alternate", sa.Boolean, nullable=False),
        sa.Column("source_id", sa.String, nullable=False),
    )
    op.create_index("ix_markets_event_kind", "markets", ["event_id", "kind"])
    op.create_table(
        "selections",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("market_id", sa.String, sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.String),
        sa.Column("source_id", sa.String, nullable=False),
        sa.Column("source_market_id", sa.String, nullable=False),
        sa.UniqueConstraint("market_id", "name", name="uq_selection_identity"),
    )
    op.create_table(
        "odds",
        sa.Column("selection_id", sa.String, sa.ForeignKey("selections.id"), primary_key=True),
        sa.Column("price", sa.Integer),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("deep_link", sa.Text),
        sa.CheckConstraint("price IS NULL OR price >= 100 OR price <= -100", name="ck_valid_price"),
        sa.CheckConstraint("state IN ('available','suspended','removed','stale')", name="ck_state"),
    )
    op.create_table(
        "scopes",
        sa.Column("league", sa.String, sa.ForeignKey("leagues.key"), primary_key=True),
        sa.Column("kind", sa.String, primary_key=True),
        sa.Column("last_success", sa.DateTime(timezone=True)),
        sa.Column("last_attempt", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String, nullable=False, server_default="never"),
        sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("missed_deadlines", sa.Integer, nullable=False, server_default="0"),
        sa.Column("scheduling_lag", sa.Float, nullable=False, server_default="0"),
        sa.Column("selection_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("warnings", sa.JSON, nullable=False),
    )
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("league", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_snapshots_collected", "snapshots", ["collected_at"])
    op.create_table(
        "collector",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("heartbeat", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", sa.JSON, nullable=False),
    )


def downgrade():
    for name in (
        "collector",
        "snapshots",
        "scopes",
        "odds",
        "selections",
        "markets",
        "books",
        "events",
        "leagues",
    ):
        op.drop_table(name)
