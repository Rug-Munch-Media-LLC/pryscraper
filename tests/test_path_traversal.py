"""Tests for path-traversal rejection in user-supplied filesystem identifiers.

CWE-22. Every test names the mutation it kills. A test that still passes with
the fix reverted is dead weight and gets deleted - see test_mutation_kills_fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pry.core.errors import InvalidRequestError, PryError
from pry.engine import sessions

if TYPE_CHECKING:
    from pathlib import Path

# Traversal payloads that must never resolve to a writable/readable path.
TRAVERSAL_IDS = [
    "../../etc/passwd",
    "..%2F..%2Fetc%2Fpasswd",
    "../sessions_evil/x",
    "/etc/passwd",
    "..",
    ".",
    "a/../../b",
    "x\x00y",
]

# Ids already present in the repo's own suite and on disk. If this list starts
# failing, existing sessions became unloadable.
LEGACY_IDS = ["s3", "s4", "s5", "s_a", "s_b", "old", "new", "fresh", "session-abc", "ioerror"]


@pytest.fixture
def sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the sessions module at an isolated directory."""
    target = tmp_path / "sessions"
    target.mkdir()
    monkeypatch.setattr(sessions, "SESSIONS_DIR", target)
    return target


# --- Choke point: _session_path ---------------------------------------------


@pytest.mark.parametrize("bad", TRAVERSAL_IDS)
def test_session_path_rejects_traversal(bad: str) -> None:
    """Kills: deletion of the validate_id call from safe_join."""
    with pytest.raises(InvalidRequestError):
        sessions._session_path(bad)


def test_session_path_rejects_sibling_prefix(sessions_dir: Path) -> None:
    """Kills: swapping is_relative_to for a naive str.startswith prefix check.

    ``../sessions_evil`` shares a leading string with ``sessions`` but is a
    different directory, so ``str().startswith(base)`` returns True and the
    escape succeeds.
    """
    evil = sessions_dir.parent / "sessions_evil"
    evil.mkdir()
    with pytest.raises(InvalidRequestError):
        sessions._session_path("../sessions_evil/x")


def test_session_path_accepts_valid_id(sessions_dir: Path) -> None:
    """Kills: an over-tight rule (e.g. requiring exactly session_<12 hex>)."""
    path = sessions._session_path("session_0123456789ab")
    assert path == (sessions_dir / "session_0123456789ab.json").resolve()


@pytest.mark.parametrize("legacy", LEGACY_IDS)
def test_session_path_accepts_existing_ids(legacy: str) -> None:
    """Kills: any character-class tightening that invalidates stored sessions."""
    assert sessions._session_path(legacy).name == f"{legacy}.json"


# --- Public API: all three operations must reject ---------------------------


@pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", "../sessions_evil/x"])
async def test_load_rejects_traversal(bad: str, sessions_dir: Path) -> None:
    """Kills: a load_session that bypasses the choke point."""
    with pytest.raises(InvalidRequestError):
        await sessions.load_session(bad)


@pytest.mark.parametrize("bad", ["../../etc/evil.json", "/etc/evil.json"])
async def test_save_rejects_traversal(bad: str, sessions_dir: Path, tmp_path: Path) -> None:
    """Kills: a save_session that builds its own path.

    Also asserts no file escaped, so the test fails on the write, not just
    on the raise.
    """
    with pytest.raises(InvalidRequestError):
        await sessions.save_session(bad, [])
    assert not (tmp_path.parent / "etc").exists()


async def test_delete_rejects_traversal_and_does_not_unlink(
    sessions_dir: Path, tmp_path: Path
) -> None:
    """Kills: the arbitrary-file unlink. The victim file must survive.

    This is the exploit itself: unauthenticated DELETE /v1/session/destroy
    with session_id="../../<victim>" calling Path.unlink() on it.
    """
    victim = tmp_path / "victim.txt"
    victim.write_text("must survive")
    rel = "../victim.txt"
    with pytest.raises(InvalidRequestError):
        await sessions.delete_session(rel)
    assert victim.exists(), "traversal delete destroyed a file outside SESSIONS_DIR"


async def test_delete_valid_id_round_trips(sessions_dir: Path) -> None:
    """Kills: a rule so strict that legitimate deletes stop working."""
    await sessions.save_session("session_0123456789ab", [{"name": "a"}])
    assert await sessions.delete_session("session_0123456789ab") is True
    assert not (sessions_dir / "session_0123456789ab.json").exists()
    assert await sessions.delete_session("session_0123456789ab") is False


async def test_save_load_round_trip(sessions_dir: Path) -> None:
    """Kills: a fix that resolves the path but breaks reading it back."""
    await sessions.save_session("session_abcdef012345", [{"name": "x", "value": "y"}])
    data = await sessions.load_session("session_abcdef012345")
    assert data is not None
    assert data["cookies"] == [{"name": "x", "value": "y"}]


# --- Defence in depth: containment check independent of the id rule ----------


def test_safe_join_containment_catches_bypass_of_id_rule(
    sessions_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kills: deleting the is_relative_to check from safe_join.

    Stubs validate_id to a no-op so only the containment check remains. If
    containment were removed, traversal would resolve and return a path
    instead of raising - proving the two checks are independent.
    """
    from pry.core import pathsafe

    monkeypatch.setattr(pathsafe, "validate_id", lambda value, **kw: value)
    with pytest.raises(InvalidRequestError):
        pathsafe.safe_join(sessions_dir, "../../etc/passwd", ".json")


# --- Sibling instances -------------------------------------------------------


def test_template_id_rejects_traversal() -> None:
    """Kills: reverting the template_engine fix."""
    from pry.commerce.template_engine import get_template

    with pytest.raises(InvalidRequestError):
        get_template("../../../../etc/passwd")


def test_credential_id_rejects_traversal() -> None:
    """Kills: reverting the auth_connector fix."""
    from pry.api import auth_connector

    with pytest.raises(InvalidRequestError):
        auth_connector._vault_path("../../etc/passwd")


# --- Error contract ----------------------------------------------------------


def test_traversal_yields_4xx_not_500() -> None:
    """Kills: raising a bare ValueError, which FastAPI maps to 500.

    Wired through the real app-level PryError handler, so this covers the
    full route path rather than just the exception type.
    """
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from pry.api.routers.core.sessions import router

    app = FastAPI()

    @app.exception_handler(PryError)
    async def _handler(request, exc):  # type: ignore[no-untyped-def]
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    with patch("pry.api.routers.core.sessions.automator") as auto:
        auto.destroy_session = AsyncMock(return_value=True)
        r = client.post(
            "/v1/session/destroy",
            json={"session_id": "../../../etc/passwd", "save_state": False},
        )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_request"


def test_valid_session_id_still_works_through_route() -> None:
    """Kills: an over-tight rule turning legitimate destroys into 400s."""
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from pry.api.routers.core.sessions import router

    app = FastAPI()

    @app.exception_handler(PryError)
    async def _handler(request, exc):  # type: ignore[no-untyped-def]
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    with patch("pry.api.routers.core.sessions.automator") as auto:
        auto.destroy_session = AsyncMock(return_value=True)
        r = client.post(
            "/v1/session/destroy",
            json={"session_id": "session_0123456789ab", "save_state": False},
        )
    assert r.status_code == 200


def test_rejected_value_is_not_logged_verbatim(sessions_dir: Path, caplog) -> None:
    """Kills: logging the raw attacker string into the log stream."""
    with caplog.at_level("WARNING"), pytest.raises(InvalidRequestError):
        sessions._session_path("../../etc/passwd")
    assert "../../etc/passwd" not in caplog.text
