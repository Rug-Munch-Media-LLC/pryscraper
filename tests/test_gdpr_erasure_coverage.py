# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Erasure sweep coverage and reporting (split 3 of 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from tests.gdpr_fixtures import (
    SUBJECT,
)


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
