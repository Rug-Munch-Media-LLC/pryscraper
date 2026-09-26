"""App wiring: middleware stack, MCP mount, error handlers, routers.

Split out of ``app_factory.py`` (structure ratchet, 2026-09-26). Everything
here is APP ASSEMBLY driven by kill switches — the order of the middleware
calls is load-bearing and is documented inline, not abstracted away.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pry.api.exception_handlers import add_error_handlers
from pry.api.kill_switches import MCP_ENABLED, X402_ENABLED
from pry.api.router_registry import register_routers
from pry.core.middleware import PryHttpMiddleware
from pry.payments.x402_middleware import X402Middleware


def _mount_mcp(app: FastAPI) -> None:
    """Mount the MCP agent surface at /mcp when the switch is on.

    PRY_MCP_ENABLED=false leaves /mcp unmounted entirely, so a self-host that
    does not want the agent surface has no route to attack (it is not "mounted
    but unauthorized"). The import is deliberately lazy so a switched-off
    instance never imports the MCP tool registry.
    """
    if not MCP_ENABLED:
        return
    from pry.api.mcp_server import mcp_app

    app.mount("/mcp", mcp_app)


def _add_cors(app: FastAPI) -> None:
    """Add the CORS policy (first-party hosts only, no wildcard)."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://pryscraper.com",
            "https://api.pryscraper.com",
            "https://rugmunch.io",
            # Dev + internal app origins are covered by the regex below — do not
            # enumerate internal hostnames in public source (TOP-100 #11).
            "http://localhost:3000",
            "http://localhost:5173",
        ],
        # Locked to first-party hosts only. No "*" wildcard. Subdomains of the
        # product (pryscraper.com) and the fleet dashboard (rugmunch.io).
        allow_origin_regex=r"https://(?:[a-z0-9-]+\.)*(?:pryscraper\.com|rugmunch\.io)",
        allow_methods=["*"],
        allow_headers=["*"],
    )


def wire_app(app: FastAPI) -> None:
    """Assemble the whole middleware + routing stack onto ``app``.

    ORDER MATTERS: X402Middleware is added AFTER PryHttpMiddleware so it sits
    OUTERMOST — a keyless agent must reach the 402 challenge BEFORE the API-key
    auth layer rejects with 401. Verified payments mark ``scope["x402_verified"]``,
    which request_authorized accepts as the credential.
    """
    _add_cors(app)
    # Auth + rate limiting + timing middleware (see middleware.py).
    app.add_middleware(PryHttpMiddleware)
    # Classification lives in x402_middleware (DEFAULT_FREE_PATHS /
    # PAID_ENDPOINTS) and is audited at startup by the lifespan hook —
    # fail-closed. PRY_X402_ENABLED=false omits the middleware entirely: the
    # paid endpoints are then reachable like any other route, so a
    # self-hoster's own instance serves its own keyless traffic for free
    # (product policy 2026-09-26 — we do not gate first-party/self-hosted
    # traffic against ourselves) and no facilitator, payee wallet or payment
    # ledger is involved. The hosted/priced deployment leaves the switch on.
    if X402_ENABLED:
        app.add_middleware(X402Middleware)
    add_error_handlers(app)
    _mount_mcp(app)
    register_routers(app)
