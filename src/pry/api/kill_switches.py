"""Master feature kill-switches for the Pry API app assembly.

Two env-driven switches let a self-hoster turn a whole subsystem off with one
variable instead of un-plugging code:

* ``PRY_X402_ENABLED`` (default **on**) — when off, ``app_factory`` never adds
  ``X402Middleware``, so no request can ever be met with a 402 challenge and
  the pay-per-call gate does not exist on that instance. ``config_validation``
  also skips the payee-wallet/facilitator checks when it is off, which is what
  lets a self-host boot with no wallet at all.
* ``PRY_MCP_ENABLED`` (default **on**) — when off, ``/mcp`` is never mounted,
  so the agent surface is absent (not merely unauthorized).

Both default ON. That is the security-correct direction: hosted/priced
deployments keep paying traffic by default, and a self-hoster opts OUT
explicitly. Opting *in* to a payment gate by default would silently make a
fresh install free-to-abuse.

Values are read ONCE at import and cached, because the app object is built at
import time. Reading them per-request would make the attack surface of a
switched-off instance depend on timing.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os

_FALSEY = frozenset({"0", "false", "no", "off"})


def is_enabled(name: str, *, default: bool = True) -> bool:
    """Return whether kill-switch ``name`` is on.

    ``default=True`` (subsystem on when the variable is unset) is deliberate:
    a missing variable must not silently widen the free surface. Only an
    explicit falsy value — ``0``/``false``/``no``/``off``, case-insensitive —
    switches the subsystem off.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSEY


# Cached at import: app assembly reads them exactly once (see module docstring).
X402_ENABLED = is_enabled("PRY_X402_ENABLED")
MCP_ENABLED = is_enabled("PRY_MCP_ENABLED")


def auth_mode() -> str:
    """Which authentication mode this process is actually running in.

    There are exactly three, and they are NOT interchangeable. Conflating them
    is the single most expensive mistake a self-hoster can make here, because
    two of the three fail closed with an HTTP 402 that reads exactly like a dead
    service:

    ``owner``    PRY_API_KEY is set. Callers presenting it as a bearer token
                 skip payment entirely (payments/x402_middleware/owner.py).
                 External callers WITHOUT the key still receive the 402
                 challenge, so the revenue path is unchanged. This is the
                 correct mode for a fleet-internal scraper: it needs no config
                 beyond the key, and it cannot be used by anyone who lacks it.

    ``internal`` PRY_X402_ENABLED=true and PRY_INTERNAL_TOKEN is set.
                 First-party services skip payment by presenting a
                 token + HMAC + timestamp bound to the ASGI socket peer. Hard
                 to drive from curl, because the caller identity is derived
                 from the connection rather than chosen by the caller.

    ``paywalled`` PRY_X402_ENABLED=true and no owner/internal credential
                 configured. Every caller is charged. This is the mode an
                 internet-facing deployment wants.

    ``free``     PRY_X402_ENABLED=false. Charging is disabled for EVERY caller
                 including external ones. CORRECT ONLY IF THIS HOST IS NEVER
                 REACHABLE FROM THE INTERNET — otherwise it turns a paywalled
                 API into an open one. Do not reach for this to "fix" a 402 on
                 a self-hosted fleet; use ``owner``.
    """
    if not X402_ENABLED:
        return "free"
    if os.getenv("PRY_API_KEY", "").strip():
        return "owner"
    if os.getenv("PRY_INTERNAL_TOKEN", "").strip():
        return "internal"
    return "paywalled"


# Logged once at import so the mode is visible in `docker logs` without having
# to infer it from a 402. Before this, "is Pry charging me or not?" was only
# answerable by triggering an error, which is a bad way to learn a config.
_AUTH_MODE = auth_mode()
logger = logging.getLogger(__name__)
if _AUTH_MODE == "free":
    logger.warning(
        "pry_auth_mode=free PRY_X402_ENABLED=false: NO caller will be charged, "
        "including external ones. Correct only if this host is not "
        "internet-reachable."
    )
elif _AUTH_MODE == "paywalled":
    logger.warning(
        "pry_auth_mode=paywalled no PRY_API_KEY or PRY_INTERNAL_TOKEN set: every "
        "caller is charged and unauthenticated calls get HTTP 402. If this is a "
        "self-hosted fleet, set PRY_API_KEY to use owner mode instead."
    )
else:
    logger.info(
        "pry_auth_mode=%s internal callers bypass payment via the owner key or "
        "internal HMAC; external callers still receive 402.",
        _AUTH_MODE,
    )
