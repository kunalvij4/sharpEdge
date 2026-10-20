from alembic import context
from sqlalchemy import create_engine, pool

from odds_api.infrastructure.config import Settings

config = context.config
url = config.attributes.get("database_url") or Settings().database_url
if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
