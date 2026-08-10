from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from riftlens.adapters.db.engine import apply_sqlite_pragmas, sqlite_url
from riftlens.adapters.db.models import Base
from riftlens.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    override = os.environ.get("RIFTLENS_DATABASE_URL")
    if override:
        return override
    configured = config.get_main_option("sqlalchemy.url")
    if configured and ".alembic-default.db" not in configured:
        return configured
    return sqlite_url(get_settings().db_path)


def run_migrations_offline() -> None:
    """Run migrations against a URL only. Assumes no live DBAPI connection is needed."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations on a live connection. Assumes SQLite unless a connection is injected."""
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    config.set_main_option("sqlalchemy.url", _database_url())
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    apply_sqlite_pragmas(connectable)
    with connectable.connect() as live:
        context.configure(connection=live, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
