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
