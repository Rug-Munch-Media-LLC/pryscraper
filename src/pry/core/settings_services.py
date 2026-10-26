"""Pry — service endpoint settings (split from settings.py).

Mixin holding the settings that name an EXTERNAL SERVICE Pry talks to. The
rationale on each default records which compose service it must point at, which
is the thing that actually breaks when the two drift apart.

Combined into `PrySettings` in `pry.core.settings` via plain mixin
inheritance, exactly like `settings_payments.py` / `settings_limits.py` /
`settings_flags.py`. Because the mixin is a plain class, `flaresolverr_url` is
still collected as a field of `PrySettings` and still resolves through
`model_config`'s `env_prefix="PRY_"` — `PRY_FLARESOLVERR_URL` overrides it
exactly as before.

Pure code move — no config values or logic changed.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations


class ServicesSettings:
    """Endpoints of the sidecar services Pry calls, and their signing secret."""

    # ONE canonical solver (retired 2026-10-26): fleet-infra owns the single
    # FlareSolverr container and attaches it to every consumer network under
    # the alias `flaresolverr`. The old `-pry` sidecar is gone; this default
    # is the same string docker-compose.yml passes, so config and code cannot
    # disagree about the name again.
    flaresolverr_url: str = "http://flaresolverr:8191/v1"
    # SECURITY (2026-08-20 audit, P0-4): the original hardcoded default was a
    # published static secret — anyone reading this OSS repo could forge
    # webhook signatures. Now fail-closed with NO static default: if neither
    # PRY_WEBHOOK_SECRET env nor the secrets backend (gopass
    # pry/webhook_secret) provides a value, _ensure_webhook_secret()
    # generates a random 32-byte hex secret at boot and logs a warning that
    # it is EPHEMERAL (does not survive restarts). Operators MUST set
    # PRY_WEBHOOK_SECRET in production.
    webhook_secret: str = ""
