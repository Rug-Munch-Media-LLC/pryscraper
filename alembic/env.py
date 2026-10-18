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
    # disable_existing_loggers=False: fileConfig's default (True) DISABLES
    # every logger not listed in alembic.ini. In-process migration runs
    # (pry.core.db.migrations.run_migrations) would then silently kill
    # application logging for the rest of the process — and blind any
    # caplog-based tests that run after a migration test (found via the
    # 2026-09-11 full-suite bisect: test_db_migrations disabled the
    # pry.payments.x402 logger, breaking offline-guard caplog asserts).
    fileConfig(config.config_file_name, disable_existing_loggers=False)


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

# Tables whose reflected types are intentionally NOT compared.
#
# compare_type=True is required: with it off, a column silently changed from
# Float to Numeric (the money-integrity fix) produced no autogenerate diff and
# the drift stayed invisible. These tables are excluded because their type
# shapes are dialect- or extension-owned and would otherwise emit permanent
# false diffs:
#   - alembic_version : Alembic owns its own bookkeeping table.
#   - spatial_ref_sys : PostGIS extension table (Postgres only).
#   - *_fts           : SQLite FTS5 virtual/shadow tables (untyped to the
#                       inspector, so every compare sees a difference).
_TYPE_NOISY_TABLES = {"alembic_version", "spatial_ref_sys"}
_TYPE_NOISY_SUFFIXES = ("_fts", "_fts_data", "_fts_idx", "_fts_docsize", "_fts_config")


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Keep noise out of autogenerate while leaving type comparison ON."""
    if type_ == "table" and name is not None:
        if name in _TYPE_NOISY_TABLES:
            return False
        if name.endswith(_TYPE_NOISY_SUFFIXES):
            return False
    return True


# compare_type=True: a Float -> Numeric(18,6) change MUST surface as a diff.
# compare_server_default stays off: SQLite reflection normalises defaults
# (e.g. 0 vs '0'), which produced endless modify_default noise unrelated to
# type drift.
_ALEMBIC_CONFIGURE = {
    "compare_type": True,
    "compare_server_default": False,
    "include_object": _include_object,
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
