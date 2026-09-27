"""Regression: run_migrations() must survive a create_all-made schema.

This is the default path, not an edge case. ``get_engine()`` runs
``Base.metadata.create_all`` unless ``PRY_ALEMBIC_AUTO=0``, which builds the
full schema WITHOUT recording an alembic revision. The first
``run_migrations()`` after that replays 0001 against tables that already exist
and dies on the first ``create_table`` — so every self-hosted instance (SQLite,
no alembic run at deploy) crashes the first time anything asks it to migrate.

Found on the shipped default database, which had 40 tables and an EMPTY
``alembic_version`` row.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
import sqlalchemy as sa

from pry.core.db.baseline import _already_exists, _schema_is_at_head, _tables_at_head
from pry.core.db.migrations import run_migrations

pytestmark = pytest.mark.usefixtures("temp_data_dir")


def test_already_exists_predicate_is_narrow() -> None:
    """Only the collision may be adopted; a real error must still surface."""
    assert _already_exists(Exception("table quality_checks already exists"))
    assert _already_exists(Exception('relation "users" already exists'))
    assert _already_exists(Exception("Duplicate table name 'users'"))
    assert not _already_exists(Exception("no such column: wiped_at"))
    assert not _already_exists(Exception("disk I/O error"))


def test_clean_database_migrates_normally() -> None:
    """The ordinary path must still work — no adoption needed."""
    from pry.core.db import get_engine

    run_migrations()
    present = set(sa.inspect(get_engine()).get_table_names())
    assert "quality_checks" in present
    assert "domain_method_stats" in present
    assert _schema_is_at_head() is True


def test_create_all_schema_is_adopted_not_replayed() -> None:
    """The exact bug: create_all built it, alembic has no stamp."""
    from sqlalchemy import create_engine

    from pry.core.db import _resolve_database_url
    from pry.core.db.models import Base

    url = _resolve_database_url().replace("sqlite+aiosqlite://", "sqlite")
    engine = create_engine(url)
    # What get_engine() does on first init, and what a self-hoster gets.
    Base.metadata.create_all(engine)
    engine.dispose()

    con = sqlite3.connect(url.replace("sqlite:///", "").replace("sqlite://", ""))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "quality_checks" in tables, "precondition: create_all made the schema"
    assert "alembic_version" not in tables, "precondition: alembic has NOT stamped"

    run_migrations()  # used to raise OperationalError: table quality_checks already exists

    from pry.core.db import get_engine

    assert _schema_is_at_head() is True


def test_partial_schema_still_raises(monkeypatch) -> None:
    """A schema missing tables must NOT be silently adopted."""
    from sqlalchemy import create_engine

    from pry.core.db import _resolve_database_url

    url = _resolve_database_url().replace("sqlite+aiosqlite://", "sqlite")
    engine = create_engine(url)
    con = engine.connect()
    con.execute(sa.text("CREATE TABLE quality_checks (id INTEGER PRIMARY KEY)"))
    con.commit()
    con.close()
    engine.dispose()

    # PRY_ALEMBIC_AUTO=0 so the rescue path cannot manufacture the tables it
    # is about to validate — that would make "partial" unobservable.
    monkeypatch.setenv("PRY_ALEMBIC_AUTO", "0")
    with pytest.raises(sa.exc.OperationalError):
        run_migrations()


def test_tables_at_head_excludes_alembic_bookkeeping() -> None:
    names = _tables_at_head()
    assert "quality_checks" in names
    assert not any(n.startswith("alembic_") for n in names)


def test_health_reports_still_works() -> None:
    """The rescue path must not have broken the health probe."""
    from pry.core.db import db_health

    health: dict[str, Any] = db_health()
    assert health.get("available") is True
