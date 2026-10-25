from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from pry.api.routers.data.real_estate import router as real_estate_router
from pry.core.errors import PryError


def _apartments_search_html() -> str:
    """An Apartments.com SRP page with a ``__PRELOADED_STATE__`` blob."""
    payload = {
        "place": {
            "listings": [
                {
                    "id": "apt-1",
                    "name": "The Aster Apartments",
                    "address": {
                        "streetAddress": "100 Congress Ave",
                        "city": "Austin",
                        "state": "TX",
                        "postalCode": "78701",
                    },
                    "price": {"min": 1450, "max": 2200},
                    "beds": {"min": 1, "max": 2},
                    "baths": {"min": 1, "max": 2},
                    "sqft": {"min": 650, "max": 1100},
                    "detailUrl": "/austin-tx/the-aster-apartments/apt-1/",
                },
                {
                    "id": "apt-2",
                    "name": "Domain Lofts",
                    "address": {
                        "streetAddress": "500 Domain Dr",
                        "city": "Austin",
                        "state": "TX",
                        "postalCode": "78758",
                    },
                    "price": {"min": 1800},
                    "beds": {"min": 2},
                    "baths": {"min": 2},
                    "sqft": {"min": 900},
                    "detailUrl": "/austin-tx/domain-lofts/apt-2/",
                },
            ]
        }
    }
    return (
        "<!DOCTYPE html><html><head></head><body>"
        '<script type="application/json" id="__PRELOADED_STATE__">'
        + json.dumps(payload)
        + "</script></body></html>"
    )

def _zumper_search_html() -> str:
    """A Zumper rent-search page with a ``window.__NUXT__`` state blob."""
    payload = {
        "data": {
            "rentals": [
                {
                    "id": "z-1",
                    "title": "Charming Bungalow",
                    "address": "701 Rainey St",
                    "city": "Austin",
                    "state": "TX",
                    "price": {"min": 2100, "max": 2400},
                    "bedrooms": 2,
                    "bathrooms": 1.5,
                    "sqft": 950,
                    "url": "https://www.zumper.com/austin-tx/charming-bungalow/z-1",
                },
                {
                    "id": "z-2",
                    "title": "Skyline Condo",
                    "address": "300 E 6th St",
                    "city": "Austin",
                    "state": "TX",
                    "price": {"min": 2600},
                    "bedrooms": 1,
                    "bathrooms": 1,
                    "sqft": 700,
                    "url": "https://www.zumper.com/austin-tx/skyline-condo/z-2",
                },
            ]
        }
    }
    return (
        "<!DOCTYPE html><html><head></head><body>"
        "<script>window.__NUXT__ = " + json.dumps(payload) + ";</script>"
        "</body></html>"
    )

def _arcgis_payload() -> dict[str, Any]:
    return {
        "features": [
            {
                "attributes": {
                    "PIN_NUM": "0695327712",
                    "OWNER": "GURRAM, ANANDA PAPIREDDY, MURALIDHAR REDDY",
                    "TOTAL_VALUE_ASSD": 619967,
                    "TOTSALPRICE": 795000,
                    "SALE_DATE": 1734307200000,
                    "DEED_BOOK": "2024",
                    "DEED_PAGE": "12345",
                    "SITE_ADDRESS": "123 Main St",
                    "CITY": "Raleigh",
                    "YEAR_BUILT": 2005,
                    "HEATEDAREA": 2400,
                }
            }
        ]
    }

@pytest.fixture
def real_estate_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(real_estate_router)
    return app

def _client(app: FastAPI) -> TestClient:
    return TestClient(app)
