"""Branch coverage for erasure status derivation and short-ID rejection."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import TYPE_CHECKING

from pry.compliance import deletion as plumbing, deletion_logic as dl

if TYPE_CHECKING:
    import pytest


def test_result_partial_when_any_store_is_unreadable() -> None:
    manifest = [
        dl._entry("quality", "deleted", 2),
        dl._entry("sessions", "deleted", 0, state="error"),
    ]
    out = dl._result(manifest, [], "hash")

    assert out["status"] == "partial"
    assert out["success"] is True
    assert out["deleted_records"] == 2
    assert out["note"].startswith("Erasure is PARTIAL")


def test_result_partial_counts_unreadable_records() -> None:
    out = dl._result([dl._entry("quality", "deleted", 0, unreadable=2)], [], "hash")
    assert out["status"] == "partial"
    assert out["unreadable_records"] == 2
    assert out["success"] is False


def test_result_zero_affected_is_not_fulfilled() -> None:
    out = dl._result([dl._entry("quality", "deleted", 0, state="absent")], [], "hash")
    assert out["status"] == "no_matching_records"
    assert out["success"] is False
    assert "NOT fulfilled" in out["note"]


def test_short_user_id_rejected_before_any_sweep() -> None:
    out = dl.process_deletion("ab")
    assert out["status"] == "rejected"
    assert out["success"] is False
    assert out["error"] == "user_id must be at least 3 characters"
    assert out["missing_roots"] == list(dl.ERASURE_SCOPE)
    assert out["stores"] == []


def test_process_deletion_partial_when_db_sweep_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dl, "_purge_consent", lambda _h: (0, 0))
    monkeypatch.setattr(dl, "_purge_matching_json", lambda _d, _p: (0, 0, True))
    monkeypatch.setattr(
        plumbing,
        "sweep_database",
        lambda _u: [dl._entry("usage", "deleted", 0, state="error")],
    )
    monkeypatch.setattr(
        plumbing, "sweep_x402_jsonl", lambda _u: dl._entry("x402/jsonl", "deleted", 0)
    )

    out = dl.process_deletion("subject@example.com")

    assert out["status"] == "partial"
    assert out["success"] is False
    assert [entry["store"] for entry in out["stores"]] == [
        "gdpr/consent",
        "quality",
        "sessions",
        "usage",
        "x402/jsonl",
    ]
