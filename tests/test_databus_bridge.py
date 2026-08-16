"""Tests for the DataBus bridge retry-queue lossless delivery guarantees.

Covers the audit fix: retry-queue files are only unlinked on successful
delivery; failures are requeued with an incremented retry_count; payloads
that exceed the retry cap land in a persisted dead-letter JSONL file
instead of being dropped. No payload may be silently lost.

Delivery is mocked (AsyncMock) — no live network in these tests.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

import databus_bridge as db

if TYPE_CHECKING:
    from pathlib import Path

_PAYLOAD = {"data_type": "scraped_intel", "url": "https://example.com/page"}


def _write_queue_file(
    directory: Path,
    payload: dict,
    retry_count: int = 0,
    name: str = "retry_20260101_000000_000001.json",
) -> Path:
    path = directory / name
    path.write_text(
        json.dumps(
            {
                "payload": payload,
                "queued_at": "2026-01-01T00:00:00+00:00",
                "retry_count": retry_count,
            },
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def _read_queue_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dead_letter_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolate the bridge on temp dirs so tests never touch real data paths."""
    monkeypatch.setattr(db, "RETRY_DIR", tmp_path / "retry")
    monkeypatch.setattr(db, "DEAD_LETTER_PATH", tmp_path / "dead_letter.jsonl")
    db.RETRY_DIR.mkdir(parents=True, exist_ok=True)
    return db


class TestProcessRetryQueueSuccess:
    @pytest.mark.asyncio
    async def test_success_removes_queue_file(
        self,
        bridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        queue_file = _write_queue_file(bridge.RETRY_DIR, _PAYLOAD)
        deliver = AsyncMock(return_value=True)
        monkeypatch.setattr(db, "_deliver_once", deliver)

        stats = await db.process_retry_queue()

        assert stats == {"processed": 1, "succeeded": 1, "failed": 0, "remaining": 0}
        assert not queue_file.exists()
        assert not bridge.DEAD_LETTER_PATH.exists()
        deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failure_retains_and_requeues_file(
        self,
        bridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        queue_file = _write_queue_file(bridge.RETRY_DIR, _PAYLOAD, retry_count=0)
        deliver = AsyncMock(return_value=False)
        monkeypatch.setattr(db, "_deliver_once", deliver)

        stats = await db.process_retry_queue()

        assert stats == {"processed": 1, "succeeded": 0, "failed": 0, "remaining": 1}
        assert queue_file.exists()
        requeued = _read_queue_file(queue_file)
        assert requeued["payload"] == _PAYLOAD
        assert requeued["retry_count"] == 1
        deliver.assert_awaited_once()
        assert not bridge.DEAD_LETTER_PATH.exists()


class TestProcessRetryQueueCap:
    @pytest.mark.asyncio
    async def test_cap_exceeded_moves_payload_to_dead_letter(
        self,
        bridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(db, "DATABUS_MAX_RETRIES", 2)
        queue_file = _write_queue_file(bridge.RETRY_DIR, _PAYLOAD, retry_count=2)
        deliver = AsyncMock(return_value=False)
        monkeypatch.setattr(db, "_deliver_once", deliver)

        stats = await db.process_retry_queue()

        assert stats == {"processed": 1, "succeeded": 0, "failed": 1, "remaining": 0}
        assert not queue_file.exists()
        deliver.assert_not_awaited()
        records = _dead_letter_records(bridge.DEAD_LETTER_PATH)
        assert len(records) == 1
        assert records[0]["payload"] == _PAYLOAD
        assert records[0]["retry_count"] == 2

    @pytest.mark.asyncio
    async def test_requeue_then_dead_letter_after_cap(
        self,
        bridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(db, "DATABUS_MAX_RETRIES", 2)
        queue_file = _write_queue_file(bridge.RETRY_DIR, _PAYLOAD, retry_count=1)
        deliver = AsyncMock(return_value=False)
        monkeypatch.setattr(db, "_deliver_once", deliver)

        # First pass: delivery fails, retry_count bumps to the cap.
        stats = await db.process_retry_queue()
        assert stats["processed"] == 1
        assert stats["succeeded"] == 0
        assert stats["failed"] == 0
        assert queue_file.exists()
        assert _read_queue_file(queue_file)["retry_count"] == 2

        # Second pass: cap reached -> dead-lettered, no more delivery attempts.
        stats2 = await db.process_retry_queue()
        assert stats2 == {"processed": 1, "succeeded": 0, "failed": 1, "remaining": 0}
        assert not queue_file.exists()
        records = _dead_letter_records(bridge.DEAD_LETTER_PATH)
        assert len(records) == 1
        assert records[0]["payload"] == _PAYLOAD
        deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dead_letter_write_failure_retains_queue_file(
        self,
        bridge,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(db, "DATABUS_MAX_RETRIES", 1)
        queue_file = _write_queue_file(bridge.RETRY_DIR, _PAYLOAD, retry_count=1)
        deliver = AsyncMock(return_value=False)
        monkeypatch.setattr(db, "_deliver_once", deliver)
        # Force the dead-letter append to fail: parent is a regular file.
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(db, "DEAD_LETTER_PATH", blocker / "dead_letter.jsonl")

        stats = await db.process_retry_queue()

        # Payload is retained in the retry queue, never dropped.
        assert stats == {"processed": 1, "succeeded": 0, "failed": 0, "remaining": 1}
        assert queue_file.exists()
        assert _read_queue_file(queue_file)["retry_count"] == 1
        deliver.assert_not_awaited()


class TestProcessRetryQueueEdgeCases:
    @pytest.mark.asyncio
    async def test_corrupt_queue_file_is_retained(
        self,
        bridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        queue_file = bridge.RETRY_DIR / "retry_20260101_000000_000002.json"
        queue_file.write_text("{not json", encoding="utf-8")
        deliver = AsyncMock(return_value=True)
        monkeypatch.setattr(db, "_deliver_once", deliver)

        stats = await db.process_retry_queue()

        assert stats == {"processed": 1, "succeeded": 0, "failed": 1, "remaining": 1}
        assert queue_file.exists()
        deliver.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_queue_returns_zero_stats(self, bridge) -> None:
        stats = await db.process_retry_queue()
        assert stats == {"processed": 0, "succeeded": 0, "failed": 0, "remaining": 0}


class TestDeliverWithRetry:
    @pytest.mark.asyncio
    async def test_success_does_not_queue(
        self,
        bridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(db, "DATABUS_MAX_RETRIES", 1)
        deliver = AsyncMock(return_value=True)
        monkeypatch.setattr(db, "_deliver_once", deliver)

        ok = await db._deliver_with_retry(_PAYLOAD)

        assert ok is True
        assert list(bridge.RETRY_DIR.glob("retry_*.json")) == []
        deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exhaustion_queues_with_retry_count_zero(
        self,
        bridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(db, "DATABUS_MAX_RETRIES", 1)
        deliver = AsyncMock(return_value=False)
        monkeypatch.setattr(db, "_deliver_once", deliver)

        ok = await db._deliver_with_retry(_PAYLOAD)

        assert ok is False
        queued = list(bridge.RETRY_DIR.glob("retry_*.json"))
        assert len(queued) == 1
        record = _read_queue_file(queued[0])
        assert record["payload"] == _PAYLOAD
        assert record["retry_count"] == 0
        deliver.assert_awaited_once()
