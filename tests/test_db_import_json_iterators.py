"""Iterator-helper tests for ``pry.core.db.import_json``.

Covers ``_iter_jsonl`` and ``_iter_json_files`` directly, including the
swallowed-read-failure guards: a read error that yields nothing instead of
raising becomes a ``counts[store] = 0`` entry, which reads as "nothing to
import" rather than "this store's data was lost".

Sibling of ``test_db_import_json.py`` (the store-level import tests).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import json

import pytest

import pry.core.paths as paths


@pytest.fixture
def temp_data_dir(monkeypatch, tmp_path):
    """Point PRY_DATA_DIR/PRY_DATABASE_URL at a temp dir and reset the engine."""
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import pry.core.db as db

    importlib.reload(paths)
    importlib.reload(db)
    db._engine = None
    db._SessionLocal = None
    yield tmp_path
    db._engine = None
    db._SessionLocal = None


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ── _iter_jsonl helper ────────────────────────────────────────────


def test_iter_jsonl_missing_path_yields_nothing(temp_data_dir):
    from pry.core.db.import_json import _iter_jsonl

    assert list(_iter_jsonl(temp_data_dir / "nope" / "x.jsonl")) == []


def test_iter_jsonl_skips_empty_lines_and_raises_on_invalid_ones(temp_data_dir):
    from pry.core.db.import_json import _iter_jsonl

    path = temp_data_dir / "quality" / "checks.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n" + "   \n" + json.dumps({"id": "a"}) + "\n" + json.dumps({"id": "b"}) + "\n",
        encoding="utf-8",
    )

    records = list(_iter_jsonl(path))
    expected = ["a", "b"]
    assert [r["id"] for r in records] == expected


# ── _iter_json_files helper ──────────────────────────────────────


def test_iter_json_files_missing_path_yields_nothing(temp_data_dir):
    from pry.core.db.import_json import _iter_json_files

    assert list(_iter_json_files(temp_data_dir / "nope")) == []


def test_iter_json_files_single_file_with_list(temp_data_dir):
    from pry.core.db.import_json import _iter_json_files

    path = temp_data_dir / "monitors" / "m1.json"
    _write_json(path, [{"id": "a"}, {"id": "b"}])

    records = list(_iter_json_files(path))
    expected = ["a", "b"]
    assert [r["id"] for r in records] == expected


def test_iter_json_files_single_file_with_dict(temp_data_dir):
    from pry.core.db.import_json import _iter_json_files

    path = temp_data_dir / "monitors" / "m1.json"
    _write_json(path, {"id": "a"})

    records = list(_iter_json_files(path))
    expected = ["a"]
    assert [r["id"] for r in records] == expected


def test_iter_json_files_directory_globs_json(temp_data_dir):
    from pry.core.db.import_json import _iter_json_files

    d = temp_data_dir / "monitors"
    d.mkdir(parents=True, exist_ok=True)
    _write_json(d / "m1.json", {"id": "a"})
    _write_json(d / "m2.json", {"id": "b"})
    (d / "ignore.txt").write_text("not json", encoding="utf-8")

    records = list(_iter_json_files(d))
    expected = ["a", "b"]
    assert sorted(r["id"] for r in records) == expected


def test_iter_json_files_skips_non_dict_list_entries(temp_data_dir):
    from pry.core.db.import_json import _iter_json_files

    path = temp_data_dir / "monitors" / "m1.json"
    _write_json(path, [{"id": "a"}, "not-a-dict", 42, None])

    records = list(_iter_json_files(path))
    expected = ["a"]
    assert [r["id"] for r in records] == expected


# ── _iter_jsonl / _iter_json_files: swallowed-read failures raise ──────
#
# A read error that yields nothing instead of raising becomes a
# ``counts[store] = 0`` entry, which reads as "nothing to import" rather
# than "this store's data was lost". Both helpers must surface it.


def test_iter_jsonl_raises_on_malformed_line(temp_data_dir):
    from pry.core.db.import_json import _iter_jsonl

    path = temp_data_dir / "quality" / "checks.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"url": "https://ok.example"}\n{not json}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="malformed JSONL"):
        list(_iter_jsonl(path))


def test_iter_jsonl_raises_when_store_path_is_a_directory(temp_data_dir):
    """read_text() on a directory raises OSError — it must reach the caller."""
    from pry.core.db.import_json import _iter_jsonl

    path = temp_data_dir / "quality" / "checks.jsonl"
    path.mkdir(parents=True, exist_ok=True)

    with pytest.raises((OSError, ValueError)):
        list(_iter_jsonl(path))


def test_iter_json_files_raises_on_malformed_json(temp_data_dir):
    from pry.core.db.import_json import _iter_json_files

    path = temp_data_dir / "monitors" / "m1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable JSON store"):
        list(_iter_json_files(path))


def test_iter_json_files_raises_on_unreadable_file(tmp_path, monkeypatch):
    """A read error on a store file must surface, not yield an empty import."""
    from pry.core.db import import_json as import_json_mod

    path = tmp_path / "monitors.json"
    path.write_text(json.dumps({"id": "a"}), encoding="utf-8")

    def _boom(self: object, *args: object, **kwargs: object) -> str:
        raise OSError("simulated read failure")

    monkeypatch.setattr("pathlib.Path.read_text", _boom)

    with pytest.raises(ValueError, match="unreadable JSON store"):
        list(import_json_mod._iter_json_files(path))
