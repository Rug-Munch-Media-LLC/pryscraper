"""Tests for the real_estate package (listings + property records).

Covers Zillow ``__NEXT_DATA__`` listing-page parsing, Zillow SRP search
parsing, the Redfin GIS search fallback and Redfin home-detail fallback,
county ArcGIS property-record queries, the never-raise contract (HTTP
errors / rate limits / bad HTML / bad JSON all degrade to ``{}`` / ``[]``),
robots.txt policy (advisory vs ``PRY_REAL_ESTATE_ENFORCE_ROBOTS=1``), and
the /v1/realestate/* router (200 + 502-degradation + query validation).

All HTTP is mocked with respx (local-router ``respx_mock`` — the version
of this venv attaches routes to the local router only) — no live network.
"""
from datasets.real_estate import listings
from tests.real_estate._real_estate_support import _hermetic_real_estate  # noqa: F401
from tests.real_estate._real_estate_support2 import real_estate_app  # noqa: F401


def test_is_bot_page_detects_walls() -> None:
    assert listings._is_bot_page("<html>Just a moment... checking your browser</html>") is True
    assert (
        listings._is_bot_page('<html><div id="captcha">Verify you are human</div></html>') is True
    )
    assert listings._is_bot_page("<html><body>normal listings page</body></html>") is False
    assert listings._is_bot_page("") is False
