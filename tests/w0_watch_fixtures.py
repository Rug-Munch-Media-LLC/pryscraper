"""Shared constants and the DNS stub for the /v1/watch webhook SSRF tests.

Split out of ``test_w0_watch_webhook_ssrf.py``, which crossed the 200-line
structure cap. The stub lives here so the two split halves share ONE definition
of "resolve only this hostname" — if it were duplicated, a fix applied to one
copy would leave the other asserting against a different validator seam.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import patch

# A routable-looking public IP used as the stubbed DNS answer. Nothing ever
# connects to it — respx intercepts at the transport layer.
PUBLIC_IP = "93.184.216.34"
PUBLIC_WEBHOOK = "https://hooks.example.com/services/T00/B00/XXXX"

DIFF: dict[str, Any] = {"status": "registered", "url": "https://target.example", "version": 1}


def _stub_dns(mapping: dict[str, str]) -> Any:
    """Resolve ONLY the given hostnames; anything else fails to resolve.

    Uses a real ``socket.getaddrinfo`` seam (the same call the validator makes)
    rather than patching the validator, so the DNS-pinning logic under test
    stays real.
    """

    def fake_getaddrinfo(host: str, port: object, *args: object, **kwargs: object) -> list[Any]:
        try:
            ip = mapping[host]
        except KeyError:
            raise socket.gaierror(f"stub: refusing to resolve {host!r}") from None
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]  # type: ignore[misc]

    return patch("socket.getaddrinfo", side_effect=fake_getaddrinfo)
