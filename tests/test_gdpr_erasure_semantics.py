# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Erasure semantics: zero-deletion, completion stamp, HOME regression (split 2 of 3)."""


from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from tests.gdpr_fixtures import (
    OTHER,
    SUBJECT,
    _plant_quality,
)


def test_erasure_leaves_other_subjects_records_intact(data_root: Path) -> None:
    """Kills: over-broad matching -- deleting every record in the root.

    Without a word-boundary/structured check, "no over-deletion" is
    untestable, so a fix that simply removes the directory would pass every
    other test here.
    """
    from pry.compliance.deletion_logic import process_deletion

    mine = _plant_quality(data_root, f"https://example.com/p/{SUBJECT}/page")
    theirs = _plant_quality(data_root, f"https://example.com/p/{OTHER}/page")

    process_deletion(SUBJECT)

    assert not mine.exists()
    assert theirs.exists(), "erasure removed a record belonging to another subject"


def test_zero_deletion_is_not_success(data_root: Path) -> None:
    """Kills: ``return {"success": True, ...}`` with deleted_records==0.

    A subject with no stored records must not receive a success attestation.
    The result carries an explicit status so an operator can distinguish
    "nothing held" from "we scanned the wrong tree".
    """
    from pry.compliance.deletion_logic import process_deletion

    result = process_deletion(SUBJECT)

    assert result["deleted_records"] == 0
    assert result["success"] is False
    assert result["status"] == "no_matching_records"
    assert "note" in result, "a zero-deletion must carry an operator-visible explanation"


def test_zero_deletion_request_is_not_stamped_completed(data_root: Path) -> None:
    """Kills: ``request["status"] = "completed"`` unconditional in execute_deletion.

    Drives the real request -> execute path and reads the request file back
    from disk. This is the actual compliance artefact: a request marked
    completed while the data remains is the false attestation this whole fix
    exists to prevent.
    """
    from pry.compliance.deletion import DELETION_DIR, execute_deletion, request_deletion

    requested = asyncio.run(request_deletion(SUBJECT))
    request_id = requested["id"]
    assert requested["status"] == "pending"

    result = asyncio.run(execute_deletion(request_id))

    on_disk = json.loads((DELETION_DIR / f"{request_id}.json").read_text())
    assert on_disk["status"] != "completed"
    assert on_disk["status"] == "no_matching_records"
    assert on_disk["completed_at"] is None
    assert on_disk["deleted_records"] == 0
    assert result["status"] == "no_matching_records"


def test_fulfilled_deletion_request_is_stamped_completed(data_root: Path) -> None:
    """Kills: an over-eager fix that refuses to stamp completed even on success.

    The companion to the test above. Without it, "never stamp completed"
    would pass while breaking the happy path, and the erasure queue would never
    drain.
    """
    from pry.compliance.deletion import DELETION_DIR, execute_deletion, request_deletion

    _plant_quality(data_root, f"https://example.com/p/{SUBJECT}/page")
    requested = asyncio.run(request_deletion(SUBJECT))

    asyncio.run(execute_deletion(requested["id"]))

    on_disk = json.loads((DELETION_DIR / f"{requested['id']}.json").read_text())
    assert on_disk["status"] == "completed"
    assert on_disk["completed_at"] is not None
    assert on_disk["deleted_records"] == 1


def test_non_existent_home_does_not_change_scan_target(data_root: Path, tmp_path: Path) -> None:
    """Kills: ANY reintroduction of a home-relative data path. THE regression test.

    Points $HOME at a directory that does not exist, exactly as production does
    (container HOME=/app/pry-data/home, PRY_DATA_DIR=/app/pry-data). The planted
    record under PRY_DATA_DIR must still be erased, and a decoy record under
    $HOME/.pry must be left alone. Any expanduser("~/.pry/...") in the scan path
    turns this test red.
    """
    phantom_home = tmp_path / "phantom-home"
    os.environ["HOME"] = str(phantom_home)
    assert not phantom_home.exists(), "fixture precondition: HOME must not exist"

    from pry.compliance.deletion_logic import process_deletion

    real = _plant_quality(data_root, f"https://example.com/p/{SUBJECT}/real")
    decoy = phantom_home / ".pry" / "quality"
    decoy.mkdir(parents=True)
    decoy_record = decoy / "decoy.json"
    decoy_record.write_text(json.dumps({"url": f"https://example.com/p/{SUBJECT}/decoy"}))

    result = process_deletion(SUBJECT)

    assert not real.exists(), "scan target moved away from PRY_DATA_DIR when HOME changed"
    assert decoy_record.exists(), "scan target moved onto $HOME"
    assert result["deleted_records"] == 1


