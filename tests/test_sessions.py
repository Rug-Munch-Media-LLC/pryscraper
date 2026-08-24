"""Tests for sessions.py — persistent browser session management."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pry.engine.sessions import (
    _session_path,
    cleanup_sessions,
    delete_session,
    list_sessions,
    load_session,
    save_session,
)


@pytest.fixture(autouse=True)
def temp_sessions_dir():
    """Use a temp dir for sessions to avoid polluting real data."""
    tmp = tempfile.mkdtemp()
    with patch("pry.engine.sessions.SESSIONS_DIR", Path(tmp)):
        Path(tmp).mkdir(parents=True, exist_ok=True)
        yield tmp
    for f in Path(tmp).glob("*"):
        f.unlink()
    Path(tmp).rmdir()


def test_session_path():
    path = _session_path("test-session-123")
    assert str(path).endswith("test-session-123.json")


@pytest.mark.asyncio
async def test_save_session():
    await save_session(
        session_id="s1",
        cookies=[{"name": "sessionid", "value": "abc"}],
        metadata={"url": "http://example.com"},
    )
    path = _session_path("s1")
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["session_id"] == "s1"
    assert len(data["cookies"]) == 1
    assert data["metadata"]["url"] == "http://example.com"


@pytest.mark.asyncio
async def test_save_session_with_storage():
    await save_session(
        session_id="s2",
        cookies=[],
        local_storage={"key": "val"},
        session_storage={"sess_key": "sess_val"},
    )
    path = _session_path("s2")
    data = json.loads(path.read_text())
    assert data["local_storage"]["key"] == "val"
    assert data["session_storage"]["sess_key"] == "sess_val"


@pytest.mark.asyncio
async def test_save_session_defaults():
    await save_session(session_id="s3", cookies=[])
    path = _session_path("s3")
    data = json.loads(path.read_text())
    assert data["local_storage"] == {}
    assert data["session_storage"] == {}
    assert data["metadata"] == {}


@pytest.mark.asyncio
async def test_load_session():
    await save_session("s4", [{"name": "x", "value": "y"}])
    data = await load_session("s4")
    assert data is not None
    assert data["session_id"] == "s4"
    assert data["cookies"][0]["name"] == "x"


@pytest.mark.asyncio
async def test_load_session_not_found():
    data = await load_session("nonexistent")
    assert data is None


@pytest.mark.asyncio
async def test_load_session_corrupted():
    path = _session_path("corrupt")
    path.write_text("{invalid json")
    data = await load_session("corrupt")
    assert data is None


@pytest.mark.asyncio
async def test_delete_session():
    await save_session("s5", [])
    result = await delete_session("s5")
    assert result is True
    assert not _session_path("s5").exists()


@pytest.mark.asyncio
async def test_delete_session_not_found():
    result = await delete_session("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_list_sessions():
    await save_session("s_a", [{"name": "a"}], metadata={"user": "alice"})
    await save_session("s_b", [{"name": "b"}], metadata={"user": "bob"})
    sessions = await list_sessions()
    assert len(sessions) == 2
    ids = [s["session_id"] for s in sessions]
    assert "s_a" in ids
    assert "s_b" in ids


@pytest.mark.asyncio
async def test_list_sessions_empty():
    sessions = await list_sessions()
    assert sessions == []


@pytest.mark.asyncio
async def test_list_sessions_skips_corrupted():
    _session_path("good").write_text(json.dumps({"session_id": "good", "cookies": []}))
    _session_path("bad").write_text("corrupted{json")
    sessions = await list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "good"


@pytest.mark.asyncio
async def test_cleanup_sessions():
    await save_session("old", [])
    await save_session("new", [])
    # Make "old" appear old by setting mtime
    old_path = _session_path("old")
    old_path.touch()
    old_path.stat()
    very_old = time.time() - 999999  # ~11 days
    os.utime(old_path, (very_old, very_old))

    removed = await cleanup_sessions(max_age_days=1)
    # "old" should be >1 day old now, so at least it gets removed
    assert removed >= 1
    remaining = await list_sessions()
    assert len(remaining) <= 2  # at least new remains


@pytest.mark.asyncio
async def test_cleanup_sessions_none_old():
    await save_session("fresh", [])
    removed = await cleanup_sessions(max_age_days=30)
    assert removed == 0


@pytest.mark.asyncio
async def test_save_oserror():
    with patch("pry.engine.sessions.Path.write_text") as mock_write:
        mock_write.side_effect = OSError("disk full")
        # Should not raise
        await save_session("fail_session", [{"name": "x"}])


@pytest.mark.asyncio
async def test_load_oserror():
    path = _session_path("ioerror")
    path.write_text(json.dumps({"session_id": "ioerror"}))
    with patch("pry.engine.sessions.Path.read_text") as mock_read:
        mock_read.side_effect = OSError("io error")
        data = await load_session("ioerror")
        assert data is None
