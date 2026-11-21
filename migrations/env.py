"""Alembic environment.

URL precedence: config.attributes["url"], then -x url=..., then Settings.from_env()
(LANGPIPE_DATABASE_URL, else the Settings default).
"""

from logging.config import fileConfig

from alembic import context

from langpipe.config.settings import Settings
from langpipe.storage.db.engine import make_engine
from langpipe.storage.db.tables import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    attribute_url = config.attributes.get("url")
    if attribute_url:
        return str(attribute_url)
    x_url = context.get_x_argument(as_dictionary=True).get("url")
    if x_url:
        return x_url
    return Settings.from_env().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_database_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
