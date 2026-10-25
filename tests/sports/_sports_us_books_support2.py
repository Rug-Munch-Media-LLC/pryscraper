from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import datasets.sports_data.us_books as us


def _pointsbet_payload() -> dict[str, Any]:
    """PointsBet featured-events shape: events[] with markets/selections."""
    return {
        "competitionId": 5,
        "events": [
            {
                "id": 111,
                "key": "222",
                "name": "Celtics vs Lakers",
                "markets": [
                    {
                        "id": 1,
                        "name": "Moneyline",
                        "selections": [
                            {"name": "Celtics", "price": 2.5},
                            {"name": "Lakers", "price": 1.56},
                        ],
                    },
                    {
                        "id": 2,
                        "name": "Point Spread",
                        "selections": [
                            {"name": "Celtics", "price": 1.91, "point": 5.5},
                            {"name": "Lakers", "price": 1.91, "point": -5.5},
                        ],
                    },
                ],
            }
        ],
    }

def _generic_events_payload() -> dict[str, Any]:
    """Generic events shape used by the browser-tier books (FanDuel-like)."""
    return {
        "events": [
            {
                "event": {"id": "777", "name": "Heat @ Knicks", "home": "Knicks", "away": "Heat"},
                "markets": [
                    {
                        "name": "Moneyline",
                        "selections": [
                            {"name": "Heat", "odds": {"decimal": 3.0}},
                            {"name": "Knicks", "odds": {"decimal": 1.4}},
                        ],
                    }
                ],
            }
        ]
    }

@pytest.fixture(autouse=True)
def _hermetic_us_books(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset caches/health so mocked transports never leak between tests."""
    us._clear_cache()
    us._HEALTH.clear()
    us._HEALTH.update(
        {
            book_id: {
                "reachable": True,
                "blocked": False,
                "last_checked": None,
                "latency_ms": None,
                "error": None,
            }
            for book_id in us._US_BOOK_IDS
        }
    )
    # No real Webshare pool / Tor in tests.
    monkeypatch.setattr(us, "next_webshare_proxy", lambda: None)
    monkeypatch.setattr(us, "fetch_via_tor", None)

def _fake_aiohttp_session(
    *, status: int = 200, text: str = "{}", raise_error: Exception | None = None
) -> MagicMock:
    """Build a mocked aiohttp.ClientSession class.

    ``session.get(url, ...)`` is an async context manager whose ``__aenter__``
    yields a mocked response with ``status`` / ``text()``. When ``raise_error``
    is set, ``__aenter__`` raises it instead (transport never-raise path).
    """
    resp = AsyncMock()
    resp.status = status
    resp.text.return_value = text

    get_cm = AsyncMock()
    if raise_error is not None:
        get_cm.__aenter__.side_effect = raise_error
    else:
        get_cm.__aenter__.return_value = resp

    session = MagicMock()
    session.get.return_value = get_cm

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    return MagicMock(return_value=session_cm)
