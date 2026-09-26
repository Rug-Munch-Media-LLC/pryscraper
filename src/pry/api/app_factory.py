"""App factory — builds the Pry FastAPI application.

Split out of api.py (god-file split, 2026-09). Exposes the assembled ``app``
plus the x402 V2 spec endpoints (``/supported``, ``/readyz``, ``/metrics``).
Static description metadata lives in ``app_metadata``; middleware, kill
switches and router registration live in ``app_wiring``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from pry.api.app_metadata import (
    APP_DESCRIPTION,
    CONTACT,
    LICENSE_INFO,
    OPENAPI_TAGS,
    SERVERS,
    TERMS_OF_SERVICE,
)
from pry.api.app_wiring import wire_app
from pry.api.lifecycle import lifespan
from pry.core.settings import settings

app = FastAPI(
    title="PryScraper API",
    version="3.0.0",
    description=APP_DESCRIPTION,
    contact=CONTACT,
    license_info=LICENSE_INFO,
    terms_of_service=TERMS_OF_SERVICE,
    openapi_tags=OPENAPI_TAGS,
    servers=SERVERS,
    lifespan=lifespan,
)

wire_app(app)


# ── x402 V2 spec endpoints ──
# GET /supported — payment kinds this server accepts (x402 V2 discovery).
# GET /readyz    — readiness probe (503 until the x402 facilitator is usable).
# (GET /healthz liveness already lives in pry.api.routers.core.health.)


@app.get(
    "/supported",
    tags=["x402"],
    summary="Supported x402 payment kinds",
    description="x402 V2 discovery: the payment schemes and networks this "
    "server accepts. Clients use this to build a valid PaymentRequired flow.",
)
async def supported_payment_kinds() -> dict[str, Any]:
    return {
        "kinds": [
            {"scheme": "exact", "network": "eip155:8453"},
            {"scheme": "exact", "network": "solana:mainnet"},
            {"scheme": "exact", "network": "tron:mainnet"},
        ]
    }


@app.get(
    "/readyz",
    tags=["Health"],
    summary="Readiness probe",
    description="Returns 200 when the x402 facilitator is configured and able "
    "to verify/settle payments; 503 otherwise. Load balancers should gate "
    "traffic on this endpoint.",
)
async def readyz() -> JSONResponse:
    from pry.payments.x402 import get_facilitator_router

    ready = bool(get_facilitator_router().readiness().get("ready"))
    if not ready:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "kinds": 3},
        )
    return JSONResponse(content={"status": "ready", "kinds": 3})


@app.get("/metrics", tags=["Ops"], include_in_schema=False)
async def get_metrics() -> str:
    """Prometheus text format metrics (real registry + x402 fallbacks)."""
    try:
        from prometheus_client import generate_latest

        return generate_latest().decode("utf-8")
    except Exception:  # noqa: BLE001 — fall back to static stubs
        lines = [
            "# TYPE x402_verify_total counter",
            "x402_verify_total 0",
            "# TYPE x402_settle_total counter",
            "x402_settle_total 0",
            "# TYPE x402_verify_failures_total counter",
            "x402_verify_failures_total 0",
            "# TYPE x402_facilitator_healthy gauge",
            "x402_facilitator_healthy 1",
        ]
        return "\n".join(lines) + "\n"


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
