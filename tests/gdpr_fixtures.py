"""Shared fixtures and helpers for the GDPR erasure tests (split from test_gdpr_erasure.py).

The erasure suite was 311 lines in one file, over the 200-line structure cap.
The fixture and its record-planting helpers live here so the three split files
share one definition instead of triplicating the module-reload dance.
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
