# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Erasure deletes records from the real data root (split 1 of 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from tests.gdpr_fixtures import (
    SUBJECT,
    _plant_quality,
    _plant_session,
)


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
