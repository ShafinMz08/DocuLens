from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings
from app.db.session import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

if os.getenv("USE_TEST_DATABASE") == "1":
    if not settings.TEST_DATABASE_URL:
        raise RuntimeError(
            "USE_TEST_DATABASE=1 but TEST_DATABASE_URL is not configured."
        )

    database_url = settings.TEST_DATABASE_URL.replace("+asyncpg", "")
else:
    database_url = settings.SYNC_DATABASE_URL

config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
