"""Standardize public league keys without changing opaque event IDs."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

RENAMES = {
    "basketball_nba": "nba_basketball",
    "americanfootball_nfl": "nfl_football",
    "baseball_mlb": "mlb_baseball",
}


def rename(mapping):
    conn = op.get_bind()
    metadata = sa.MetaData()
    metadata.reflect(conn)
    leagues = metadata.tables["leagues"]
    for old, new in mapping.items():
        row = conn.execute(sa.select(leagues).where(leagues.c.key == old)).mappings().first()
        if row is None:
            continue
        if conn.execute(sa.select(leagues.c.key).where(leagues.c.key == new)).first():
            raise RuntimeError("Both old and new league keys exist; resolve before migration")
        conn.execute(sa.update(leagues).where(leagues.c.key == old).values(source_id=None))
        conn.execute(sa.insert(leagues).values(**{**dict(row), "key": new}))
        for name, column in (("events", "league_key"), ("scopes", "league"), ("snapshots", "league")):
            table = metadata.tables[name]
            conn.execute(sa.update(table).where(table.c[column] == old).values({column: new}))
        conn.execute(sa.delete(leagues).where(leagues.c.key == old))


def upgrade():
    rename(RENAMES)


def downgrade():
    rename({new: old for old, new in RENAMES.items()})
