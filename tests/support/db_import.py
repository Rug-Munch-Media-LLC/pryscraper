# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared fixtures/helpers for the ``pry.core.db.import_json`` test modules."""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def temp_data_dir(monkeypatch, tmp_path):
    """Point PRY_DATA_DIR/PRY_DATABASE_URL at a temp dir and reset the engine."""
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import pry.core.db as db

    importlib.reload(paths_module())
    importlib.reload(db)
    db._engine = None
    db._SessionLocal = None
    # get_engine() is deliberately not a schema authority (alembic owns the
    # schema; see db_engine.get_engine), so the fixture must build the schema
    # explicitly for this fresh SQLite file.
    db.Base.metadata.create_all(db.get_engine())
    yield tmp_path
    db._engine = None
    db._SessionLocal = None


def paths_module():
    """Import and return ``pry.core.paths`` (reload target for the fixture)."""
    import pry.core.paths as paths

    return paths


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
