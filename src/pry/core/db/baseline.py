"""Adopting a schema that create_all built but alembic never stamped.

``get_engine()`` runs ``Base.metadata.create_all`` unless
``PRY_ALEMBIC_AUTO=0``, which builds the full schema WITHOUT recording an
alembic revision. The first ``run_migrations()`` after that replays 0001
against tables that already exist and dies on the first ``create_table``. This
is not a test artefact — it is the default path for every self-hosted
instance, whose SQLite DB is created on first engine init.

The rule is narrow on purpose: a collision is adopted by stamping head ONLY
when every table head would create is already present. A partial schema still
raises, so a genuinely broken database is never quietly marked as healthy.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from contextlib import suppress

from sqlalchemy import create_engine, inspect, text

from pry.core.db.session import _resolve_database_url

logger = logging.getLogger(__name__)

ALEMBIC_VERSION_TABLE = "alembic_version"

# "already exists" in each backend's wording, matched case-insensitively.
_ALREADY_EXISTS_MARKERS = (
    "already exists",
    "duplicate table",
    "duplicate key value",
)


def _already_exists(exc: BaseException) -> bool:
    """True when a DDL error is the 'that table is already there' kind.

    Deliberately narrow: any OTHER failure must still raise, or a genuine
    schema error would be swallowed by the baseline path.
    """
    text_ = str(exc).lower()
    return any(marker in text_ for marker in _ALREADY_EXISTS_MARKERS)


def _schema_is_at_head() -> bool:
    """Whether a stamped database already records the head revision.

    A database with no ``alembic_version`` table at all is a create_all schema,
    not a stamped one, and correctly reports False.
    """
    with suppress(Exception):
        engine = create_engine(_sync_url())
        with engine.connect() as conn:
            if "alembic_version" not in set(inspect(conn).get_table_names()):
                engine.dispose()
                return False
            version = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        engine.dispose()
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        return bool(version) and version == head
    return False


def _stamp_head_after_existing_schema() -> bool:
    """Adopt a create_all-made schema by stamping it at head.

    ``get_engine()`` runs ``Base.metadata.create_all`` by default
    (``PRY_ALEMBIC_AUTO=1``), building the full schema WITHOUT recording an
    alembic revision. A later ``run_migrations()`` replays 0001 against
    tables that already exist and dies on the first ``create_table``. That is
    the default path for every self-hosted instance, whose SQLite DB is created
    on first engine init.

    Stamping is only safe when the existing schema really is complete, so we
    verify the tables alembic's head would have created are all present BEFORE
    recording anything. A partial schema re-raises and is left for a human.
    """
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    with suppress(Exception):
        engine = create_engine(_sync_url())
        present = set(inspect(engine).get_table_names())
    expected = _tables_at_head()
    missing = expected - present
    if missing:
        logger.error(
            "alembic_baseline_incomplete",
            extra={"missing": sorted(missing)[:8], "missing_count": len(missing)},
        )
        return False
    command.stamp(cfg, "head")
    logger.info("alembic_baseline_stamped", extra={"tables": len(expected)})
    return True


def _sync_url() -> str:
    """Resolved URL with async drivers swapped for sync, as alembic's env.py
    needs. Reusing the same substitution keeps inspection and migration on one
    database."""
    return (
        _resolve_database_url()
        .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
        .replace("sqlite+aiosqlite://", "sqlite")
    )


def _tables_at_head() -> set[str]:
    """Table names head would create, from model metadata rather than by
    replaying the chain — so it is safe against the DB being rescued."""
    from pry.core.db.models import Base

    return {t for t in Base.metadata.tables if not t.startswith("alembic_")}
