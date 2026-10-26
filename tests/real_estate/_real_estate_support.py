from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from datasets.real_estate import listings, property_records


@pytest.fixture(autouse=True)
def _hermetic_real_estate(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Zero retries/backoff + clear the per-host robots cache.

    respx auto-mocks unregistered URLs with an empty 200, so the only
    retryable failures in tests are the explicitly-registered 4xx/5xx
    responses; a zero-retry config keeps those paths instant.
    """
    from pry.engine.retry import RetryConfig

    zero = RetryConfig(
        max_retries=0,
        base_delay=0.0,
        max_delay=0.0,
        retryable_exceptions=(httpx.HTTPError,),
    )
    monkeypatch.setattr(listings, "_RETRY_CONFIG", zero)
    monkeypatch.setattr(property_records, "_RETRY_CONFIG", zero)
    listings.reset_robots_cache()
    yield
    listings.reset_robots_cache()


def _page_with_next_data(payload: dict[str, Any]) -> str:
    return (
        "<!DOCTYPE html><html><head></head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


def _zillow_listing_html() -> str:
    payload = {
        "props": {
            "pageProps": {
                "initialReduxState": {
                    "gdp": {
                        "homeInfo": {
                            "address": {
                                "streetAddress": "123 Main St",
                                "city": "Austin",
                                "state": "TX",
                                "zipcode": "78701",
                            },
                            "price": 450000,
                            "priceHistory": [
                                {"date": "2024-01-15", "event": "Sold", "price": 425000},
                                {"date": "2025-05-01", "event": "Listing removed", "price": 450000},
                            ],
                            "zestimate": 460123,
                            "bedrooms": 3,
                            "bathrooms": 2.5,
                            "livingArea": 2100,
                            "daysOnZillow": 12,
                            "hoa": 45.0,
                            "homeStatus": "FOR_SALE",
                        }
                    }
                }
            }
        }
    }
    return _page_with_next_data(payload)


def _zillow_search_html() -> str:
    payload = {
        "props": {
            "pageProps": {
                "searchPageState": {
                    "cat1": {
                        "searchResults": {
                            "listResults": [
                                {
                                    "zpid": 2064710001,
                                    "address": {
                                        "streetAddress": "456 Elm St",
                                        "city": "Austin",
                                        "state": "TX",
                                        "zipcode": "78702",
                                    },
                                    "price": 350000,
                                    "bedrooms": 2,
                                    "bathrooms": 1.5,
                                    "livingArea": 1200,
                                    "statusText": "For sale",
                                    "hdpData": {
                                        "homeInfo": {"zestimate": 355000, "daysOnZillow": 5}
                                    },
                                },
                                {
                                    "zpid": 2064710002,
                                    "address": {
                                        "streetAddress": "789 Oak Ave",
                                        "city": "Austin",
                                        "state": "TX",
                                        "zipcode": "78703",
                                    },
                                    "price": 520000,
                                    "bedrooms": 4,
                                    "bathrooms": 3.0,
                                    "livingArea": 2400,
                                    "statusText": "For sale",
                                    "hdpData": {"homeInfo": {"zestimate": 525000}},
                                },
                            ]
                        }
                    }
                }
            }
        }
    }
    return _page_with_next_data(payload)


def _redfin_gis_payload() -> dict[str, Any]:
    return {
        "payload": {
            "homes": [
                {
                    "url": "/WA/Seattle/732-11th-Ave-E-98102/home/52821",
                    "city": "Seattle",
                    "state": "WA",
                    "zip": "98102",
                    "price": 950000,
                    "beds": 3,
                    "baths": 2,
                    "sqFt": 1800,
                    "dom": 8,
                    "mlsStatus": "Active",
                    "hoa": {"value": 250},
                },
                {
                    "url": "/WA/Seattle/123-Pike-St-98101/home/51234",
                    "city": "Seattle",
                    "state": "WA",
                    "zip": "98101",
                    "price": 1200000,
                    "beds": 4,
                    "baths": 3.5,
                    "sqFt": 2500,
                    "dom": 15,
                },
            ]
        }
    }


def _redfin_detail_payload() -> dict[str, Any]:
    return {
        "payload": {
            "homeInfo": {
                "streetAddress": "500 Boren Ave N",
                "city": "Seattle",
                "state": "WA",
                "zip": "98109",
                "price": 1100000,
                "beds": 4,
                "baths": 3,
                "sqFt": 2200,
                "daysOnMarket": 22,
                "zestimate": 1115000,
                "hoa": 175,
                "status": "Active",
            }
        }
    }
