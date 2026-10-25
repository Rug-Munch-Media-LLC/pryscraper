"""Tests for the legal_docs package (CourtListener / SEC EDGAR / OFAC SDN).

Covers docket search + lookup, SEC filing search / filing lookup / Form 4
insider trades, OFAC SDN name screening (JSON source, XML fallback, disk
cache), the never-raise contract (HTTP errors and malformed payloads all
degrade to empty output), and the /v1/legal/* router (200 + 502-degradation
+ 422 validation).

All HTTP is mocked with respx — no live network.
"""
from tests.legal._legal_docs_support import _hermetic_legal  # noqa: F401

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import datasets.legal_docs as legal_docs
import datasets.legal_docs.dockets as dockets
import pry.api.routers.data.legal_docs as legal_router_mod
from pry.engine.retry import RetryConfig
from tests.legal._legal_docs_support2 import _client

_CL_BASE = "https://www.courtlistener.com/api/rest/v4"
_PACER_FETCH = f"{_CL_BASE}/pacer-fetch/"
_JUSTIA = "https://dockets.justia.com"
_NY_ECOURTS = "https://iapps.courts.state.ny.us/webcivil/FCASSearch"
_FTS = "https://efts.sec.gov/LATEST/search-index"
_TICKERS = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS = "https://data.sec.gov/submissions/CIK0000320193.json"
_INDEX = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000005/"
_OFAC_JSON = "https://www.treasury.gov/ofac/downloads/sdn.json"
_OFAC_XML = "https://www.treasury.gov/ofac/downloads/sdn.xml"
_OFAC_CSV = "https://www.treasury.gov/ofac/downloads/sdn.csv"
_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


def test_router_importable() -> None:
    assert hasattr(legal_docs, "search_dockets")
    assert hasattr(legal_docs, "get_docket")
    assert hasattr(legal_docs, "search_filings")
    assert hasattr(legal_docs, "get_filing")
    assert hasattr(legal_docs, "insider_trades")
    assert hasattr(legal_docs, "screen_name")
    assert hasattr(legal_router_mod, "router")


def test_router_dockets_search_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": 42, "case_name": f"match for {query}", "source": "courtlistener"}]

    monkeypatch.setattr(dockets, "search_dockets", fake)
    resp = _client(legal_app).get(
        "/v1/legal/dockets/search", params={"query": "example fraud", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["query"] == "example fraud"
    assert body["data"][0]["id"] == 42


def test_router_dockets_get_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(docket_id: int) -> dict[str, Any]:
        return {"id": docket_id, "case_name": "SEC v. Example Corp.", "source": "courtlistener"}

    monkeypatch.setattr(dockets, "get_docket", fake)
    resp = _client(legal_app).get("/v1/legal/dockets/42")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == 42
