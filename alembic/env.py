import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make `pry` importable regardless of how alembic is invoked (installed
# package, bare checkout, CI subprocess). src-layout means a plain
# `python -m alembic` from the repo root cannot see the package otherwise.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pry.core.db import Base, _resolve_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# Always use the same URL resolution logic as the application, then force a
# SYNC driver: Alembic runs synchronous engine_from_config; an asyncpg URL
# crashes with MissingGreenlet (the reason entrypoint migrations were
# disabled in docker-compose). psycopg2 is present in requirements.lock.
def _to_sync_url(url: str) -> str:
    """Convert async driver URLs to sync equivalents for Alembic."""
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://").replace(
        "sqlite+aiosqlite://", "sqlite"
    )


config.set_main_option(
    "sqlalchemy.url", _to_sync_url(os.getenv("PRY_DATABASE_URL") or _resolve_database_url())
)

target_metadata = Base.metadata
exclude_tables = {"spatial_ref_sys"}


# compare_type=False: SQLite round-trips lose NOT NULL/server-default
# fidelity, producing endless modify_nullable noise. Structural drift
# (tables/columns/indexes) is still detected.
_ALEMBIC_CONFIGURE = {
    "compare_type": False,
}


def run_migrations_offline() -> None:
    """Run migrations in offline mode (SQL emitted, no DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_exclude_tables=exclude_tables,
        **_ALEMBIC_CONFIGURE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_exclude_tables=exclude_tables,
            **_ALEMBIC_CONFIGURE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
