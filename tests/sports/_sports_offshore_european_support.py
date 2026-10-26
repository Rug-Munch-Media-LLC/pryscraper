from __future__ import annotations

import base64
import gzip
import json
from typing import Any

import httpx
import pytest

import datasets.sports_data.european as european
import datasets.sports_data.offshore as offshore
import datasets.sports_data.sources as sources
from pry.engine import webshare_proxy
from pry.engine.retry import RetryConfig

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset caches, kill backoff delays, clear health + proxy pool."""
    sources._clear_cache()
    offshore._BOOK_HEALTH.clear()
    offshore._BOOK_HEALTH.update(
        {
            book: {
                "reachable": True,
                "blocked": False,
                "last_checked": None,
                "latency_ms": None,
                "error": None,
            }
            for book in offshore.OFFSHORE_BOOK_ORDER
        }
    )
    european._BOOK_HEALTH.clear()
    european._BOOK_HEALTH.update(
        {
            book: {
                "reachable": True,
                "blocked": False,
                "last_checked": None,
                "latency_ms": None,
                "error": None,
            }
            for book in european.EUROPEAN_BOOK_ORDER
        }
    )
    monkeypatch.setattr(offshore, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(sources, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("WEBSHARE_PROXY_LIST", raising=False)
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)
    webshare_proxy.clear_cache()
    webshare_proxy.reset_rotation()

def _betonline_family_html() -> str:
    """BookMaker-family listing row (shared markup with BetOnline)."""
    return """<html><body>
<div class="game-row">
  <a class="game-link" href="/sportsbook/basketball/nba/game/49000001">Celtics at Lakers</a>
  <span class="team-name away">Boston Celtics</span>
  <span class="team-name home">Los Angeles Lakers</span>
  <span class="moneyline">-118</span>
  <span class="moneyline">+110</span>
</div>
</body></html>"""

def _betonline_family_embedded_html() -> str:
    """BookMaker-family page with a window.__INITIAL_STATE__ JSON blob."""
    state = {
        "games": [
            {
                "gameId": "49000002",
                "awayTeam": "Boston Celtics",
                "homeTeam": "Los Angeles Lakers",
                "wagerCutOff": "2026-08-17T00:00:00Z",
                "gameData": [
                    {
                        "lineType": "AwayLine",
                        "lineDict": {"MoneyLine": {"decimalLine": "1.85"}},
                    },
                    {
                        "lineType": "HomeLine",
                        "lineDict": {"MoneyLine": {"decimalLine": "2.10"}},
                    },
                ],
            }
        ]
    }
    return f"<html><body><script>window.__INITIAL_STATE__ = {json.dumps(state)};</script></body></html>"

def _decimal_rows_html() -> str:
    """Generic SSR decimal-odds row (MyBookie-style standalone book)."""
    return """<html><body>
<div class="game-row">
  <span class="team-name">Boston Celtics</span>
  <span class="team-name">Los Angeles Lakers</span>
  <span class="odds">2.05</span>
  <span class="odds">1.90</span>
</div>
</body></html>"""

def _pinnacle_fixtures_payload() -> dict[str, Any]:
    return {
        "leagues": [
            {
                "id": 6,
                "events": [
                    {
                        "id": 1001,
                        "home": "Los Angeles Lakers",
                        "away": "Boston Celtics",
                        "starts": "2026-08-17T00:00:00Z",
                    }
                ],
            }
        ]
    }

def _pinnacle_odds_payload() -> dict[str, Any]:
    return {
        "leagues": [
            {
                "id": 6,
                "events": [
                    {
                        "id": 1001,
                        "periods": [
                            {
                                "lineId": 9001,
                                "spread": {"hdp": -5.5, "home": "1.91", "away": "1.91"},
                                "moneyline": {"home": "2.10", "away": "1.85"},
                                "total": {"points": 224.5, "over": "1.90", "under": "1.95"},
                            }
                        ],
                    }
                ],
            }
        ]
    }

def _marathon_coupon_html() -> str:
    """Marathonbet coupon row (decimal odds, team member links)."""
    return """<html><body>
<div class="coupon-row">
  <a class="member-1" href="/en/betting/Basketball/123">Boston Celtics</a>
  <a class="member-2" href="/en/betting/Basketball/123">Los Angeles Lakers</a>
  <a class="selection-link" href="/en/betting/Basketball/123">2.05</a>
  <a class="selection-link" href="/en/betting/Basketball/123">1.90</a>
</div>
</body></html>"""

def _1xbet_payload() -> dict[str, Any]:
    """1xBet LineFeed envelope: base64(gzip(JSON))."""
    inner = {
        "L": [{"id": 100, "I": "NBA"}],
        "E": [
            {
                "id": 2001,
                "L": 100,
                "S": "2026-08-17T00:00:00Z",
                "T": [{"N": "Boston Celtics"}, {"N": "Los Angeles Lakers"}],
                "G": [
                    {
                        "G": "1",
                        "E": [
                            {"T": "1", "P": {"1": "1.85"}},
                            {"T": "X", "P": {"1": "11.0"}},
                            {"T": "2", "P": {"1": "2.10"}},
                        ],
                    }
                ],
            }
        ],
    }
    raw = base64.b64encode(gzip.compress(json.dumps(inner).encode("utf-8"))).decode("ascii")
    return {"Value": raw}

def _betfair_page_html() -> str:
    return '<html><body><script>var x = {"marketId":"1.200123456"};</script></body></html>'
