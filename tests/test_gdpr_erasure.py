# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Erasure must actually erase: the Art. 17 path and zero-deletion contract.

Each test names the mutation it kills. A test that survives reverting the fix is
decoration, so the fixture design below exists to make the home-relative
regression reproducible rather than to be tidy.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

import pytest

SUBJECT = "subject@example.com"
OTHER = "other@example.com"


@pytest.fixture
def data_root(tmp_path: Path) -> Iterator[Path]:
    """Rebind ``PRY_DATA_DIR`` to a temp root and re-import the compliance modules.

    ``pry.core.paths`` resolves PRY_DATA_DIR at import time, and the compliance
    modules derive their directories from it at import time too. So the only
    way to point them at a scratch tree is to set the env var and re-import.
    This is module reloading, not attribute patching: no object in the process
    is replaced after the test has begun.
    """
    root = tmp_path / "pry-data"
    root.mkdir()
    # HOME is snapshotted here too because the home-relative regression test
    # redirects it; restoring both keeps the fixture the single owner of
    # process-wide env state in this file.
    saved = {key: os.environ.get(key) for key in ("PRY_DATA_DIR", "HOME")}
    os.environ["PRY_DATA_DIR"] = str(root)
    try:
        import pry.core.paths as paths

        importlib.reload(paths)
        import pry.compliance.deletion as plumbing
        import pry.compliance.deletion_logic as logic
        import pry.compliance.gdpr as gdpr

        importlib.reload(logic)
        importlib.reload(plumbing)
        importlib.reload(gdpr)
        yield root
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import pry.core.paths as paths

        importlib.reload(paths)
        import pry.compliance.deletion as plumbing
        import pry.compliance.deletion_logic as logic
        import pry.compliance.gdpr as gdpr

        importlib.reload(logic)
        importlib.reload(plumbing)
        importlib.reload(gdpr)


def _plant_quality(root: Path, url: str, user_id: str | None = None) -> Path:
    """Write a quality record and return its path."""
    quality = root / "quality"
    quality.mkdir(exist_ok=True)
    record: dict[str, object] = {"url": url}
    if user_id is not None:
        record["user_id"] = user_id
    path = quality / f"{abs(hash(url)) % 10**8}.json"
    path.write_text(json.dumps(record))
    return path


def _plant_session(root: Path, session_id: str, metadata: dict[str, str]) -> Path:
    """Write a session record and return its path."""
    sessions = root / "sessions"
    sessions.mkdir(exist_ok=True)
    path = sessions / f"{session_id}.json"
    path.write_text(json.dumps({"session_id": session_id, "metadata": metadata}))
    return path


def _plant_consent(root: Path, user_id: str) -> Path:
    """Write a consent record via the real API and return its path."""
    import hashlib

    import pry.compliance.gdpr as gdpr

    asyncio.run(gdpr.record_consent(user_id, "data_collection", True))
    user_hash = hashlib.sha256(user_id.lower().encode()).hexdigest()[:16]
    return gdpr.CONSENT_DIR / f"{user_hash}_x.json"


def test_erasure_deletes_planted_quality_record_under_data_root(data_root: Path) -> None:
    """Kills: ``quality_dir = expanduser("~/.pry/quality")`` reverted to a home path.

    Plants a record that matches the subject, calls process_deletion, and
    asserts the file on disk is gone. With the old home-relative path the sweep
    looked under $HOME instead, found nothing, and returned success=True.
    """
    from pry.compliance.deletion_logic import process_deletion

    planted = _plant_quality(data_root, f"https://example.com/p/{SUBJECT}/page")
    assert planted.exists()

    result = process_deletion(SUBJECT)

    assert not planted.exists(), "quality record under PRY_DATA_DIR was not erased"
    assert result["deleted_records"] == 1
    assert result["success"] is True


def test_erasure_deletes_planted_session_record_under_data_root(data_root: Path) -> None:
    """Kills: ``sessions_dir = expanduser("~/.pry/sessions")`` reverted to a home path.

    Same class of regression as the quality case, on the second data root: the
    session record survives if the scan target is $HOME-derived.
    """
    from pry.compliance.deletion_logic import process_deletion

    planted = _plant_session(data_root, "sess-1", {"user_id": SUBJECT})
    assert planted.exists()

    result = process_deletion(SUBJECT)

    assert not planted.exists(), "session record under PRY_DATA_DIR was not erased"
    assert result["deleted_records"] == 1
    assert result["success"] is True


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


def test_sweep_reports_its_coverage(data_root: Path) -> None:
    """Kills: a silent narrowing of the sweep -- dropping or misplacing a data root.

    The result must name every root it swept AND name any root that was absent
    on disk. A root that does not exist is not the same as a root that is empty,
    and conflating the two is how "we scanned the wrong tree" gets reported as
    "there was nothing to delete".
    """
    from pry.compliance.deletion_logic import ERASURE_SCOPE, process_deletion

    # Both roots exist but are empty: coverage is complete, nothing matched.
    (data_root / "quality").mkdir()
    (data_root / "sessions").mkdir()
    complete = process_deletion(SUBJECT)
    assert set(complete["scanned_roots"]) == set(ERASURE_SCOPE)
    assert complete["missing_roots"] == []
    assert complete["success"] is False, "empty roots still mean nothing was erased"

    # Remove one root: the gap must be reported, not silently absorbed.
    (data_root / "sessions").rmdir()
    gapped = process_deletion(SUBJECT)
    assert gapped["missing_roots"] == ["sessions"]
    assert gapped["success"] is False


def test_unreadable_in_scope_record_is_reported_not_treated_as_absent(data_root: Path) -> None:
    """Kills: swallowing a decode error so a corrupt record reads as "not mine".

    A truncated file still exists on disk; it may well hold the subject's data.
    Counting it as unreadable is what stops "we removed 0 files" from being
    read as "there was nothing to remove".
    """
    from pry.compliance.deletion_logic import process_deletion

    corrupt = data_root / "quality" / "corrupt.json"
    corrupt.parent.mkdir(exist_ok=True)
    corrupt.write_text("{not json")

    result = process_deletion(SUBJECT)

    assert result["unreadable_records"] == 1
    assert result["success"] is False
    assert corrupt.exists(), "an unreadable record must not be silently deleted either"


def test_short_user_id_is_rejected_without_scanning(data_root: Path) -> None:
    """Kills: removing the MIN_USER_ID_LENGTH guard to 'simplify' the loop.

    A 1-char id would word-boundary-match across unrelated records. The guard
    must still short-circuit before any scan.
    """
    from pry.compliance.deletion_logic import process_deletion

    result = process_deletion("a")

    assert result["success"] is False
    assert result["status"] == "rejected"
    assert result["deleted_records"] == 0
