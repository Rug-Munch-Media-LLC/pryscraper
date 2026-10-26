from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.travel.flights as flights
import datasets.travel.hotels as hotels
from pry.api.routers.data.travel import router as travel_router
from pry.core.errors import PryError


@pytest.fixture(autouse=True)
def _hermetic_travel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff sleeps so tests are hermetic and fast."""
    monkeypatch.setattr(flights, "RETRY_BASE", 0.0)
    monkeypatch.setattr(flights, "MAX_BACKOFF", 0.0)
    monkeypatch.setattr(hotels, "RETRY_BASE", 0.0)
    monkeypatch.setattr(hotels, "MAX_BACKOFF", 0.0)


def _flights_html() -> str:
    """A Google-Flights-style page with embedded AF_initDataCallback data."""
    data = [
        "search-id",
        [
            [
                ["F:JFK", "F:CDG", 1726416000000, "2026-09-15"],
                [
                    {
                        "price": 612,
                        "airline": "Delta",
                        "duration": 445,
                        "stops": 0,
                        "currency": "USD",
                    },
                    {
                        "price": 540,
                        "airline": "Air France",
                        "duration": 470,
                        "stops": 1,
                        "currency": "USD",
                    },
                ],
            ]
        ],
        "trailing-noise",
    ]
    return (
        "<!DOCTYPE html><html><body>"
        "<script nonce=\"abc\">AF_initDataCallback({key: 'ds:1', hash: 'h1', data: "
        + json.dumps(data)
        + ", sideChannel: {}});</script>"
        "</body></html>"
    )


def _flights_html_parent_child() -> str:
    """Google layout variant: price on parent, airline/duration on child."""
    data = [
        [
            {
                "price": 799,
                "currency": "USD",
                "leg": {"airline": "United", "duration": 380, "stops": 0},
            },
            {
                "price": 855,
                "currency": "USD",
                "leg": {"airline": "Lufthansa", "duration": 495, "stops": 1},
            },
        ]
    ]
    return (
        "<script>AF_initDataCallback({key: 'ds:3', hash: 'h3', data: "
        + json.dumps(data)
        + "});</script>"
    )


def _hotels_google_html() -> str:
    """A Google-Hotels-style page with embedded hotel-rate records."""
    data = [
        "hotel-search",
        [
            {
                "name": "Marriott Marquis New York",
                "price": 189,
                "currency": "USD",
                "total": 378,
                "starRating": 4.0,
            },
            {
                "name": "Hilton Midtown",
                "price": 172,
                "currency": "USD",
                "total": 344,
            },
        ],
    ]
    return (
        "<!DOCTYPE html><html><body>"
        "<script nonce=\"xyz\">AF_initDataCallback({key: 'ds:2', hash: 'h2', data: "
        + json.dumps(data)
        + ", sideChannel: {}});</script>"
        "</body></html>"
    )


def _booking_html() -> str:
    """A Booking.com searchresults page with a data-capla-trace JSON block."""
    payload = {
        "trace": "searchresults",
        "results": [
            {
                "hotel_name": "The Ritz London",
                "price": 420,
                "currency": "GBP",
                "total": 840,
            }
        ],
    }
    block = json.dumps(payload)
    return (
        "<html><body>"
        f'<script type="application/json" data-capla-trace="trace-id">{block}</script>'
        "</body></html>"
    )


def _booking_regex_html() -> str:
    """Booking.com page with no JSON blocks — regex price fallback path."""
    return '<html><body><div data-price="210">Some hotel</div><span>\u20ac180</span></body></html>'


def _kayak_html() -> str:
    """A Kayak hotel page with an embedded ``window.__INITIAL_STATE__``."""
    payload = {
        "data": {
            "hotels": [
                {"name": "The Chelsea Hotel", "price": {"price": 245, "currency": "USD"}},
                {"name": "The Bowery Hotel", "price": {"price": 312, "currency": "USD"}},
            ]
        }
    }
    return (
        "<!DOCTYPE html><html><body>"
        "<script>window.__INITIAL_STATE__ = " + json.dumps(payload) + ";</script>"
        "</body></html>"
    )


def _expedia_html() -> str:
    """An Expedia hotel page with JSON-LD structured data."""
    ld = {
        "@type": "Hotel",
        "name": "Grand Hyatt New York",
        "offers": {"@type": "Offer", "price": 289, "priceCurrency": "USD"},
    }
    return (
        "<!DOCTYPE html><html><head>"
        '<script type="application/ld+json">' + json.dumps(ld) + "</script>"
        "</head><body></body></html>"
    )


@pytest.fixture
def travel_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(travel_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)
