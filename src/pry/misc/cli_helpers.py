# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

"""Shared CLI helpers: colors, API client, spinner."""

from __future__ import annotations

import os
import sys

# Color support
NC = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"

API_DEFAULT = os.getenv("PRY_URL", "http://localhost:8005")
VERSION = "3.0.0"


def _api():
    return os.getenv("PRY_URL", API_DEFAULT)


def _req(method: str, path: str, data: dict | None = None, timeout=30):
    import httpx

    url = f"{_api()}{path}"
    # Credentialed requests bypass the x402 payment gate (the gate exists to
    # monetize KEYLESS agent traffic). When PRY_API_KEY is set we send it as a
    # Bearer token so self-hosted/operator use is free and metered instead of
    # payment-challenged.
    headers = {}
    api_key = os.getenv("PRY_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        if method == "GET":
            resp = httpx.get(url, headers=headers, timeout=timeout)
        else:
            resp = httpx.post(url, json=data or {}, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        print(f"{RED}✖ Cannot connect to Pry at {_api()}{NC}")
        print(f"  Start it: {CYAN}pry serve{NC}")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            print(f"{YELLOW}⚠ Rate limited. Slow down.{NC}")
        else:
            print(f"{RED}✖ API error ({e.response.status_code}): {e.response.text[:200]}{NC}")
        sys.exit(1)


def _spinner(label: str):
    import itertools
    import threading
    import time

    stop = False

    def _spin():
        nonlocal stop
        for c in itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]):
            if stop:
                break
            # Status output goes to stderr so stdout carries ONLY the payload
            # (markdown or JSON) — `--json` output must be clean for piping.
            print(f"  {CYAN}{c}{NC} {label}...  ", end="\r", file=sys.stderr, flush=True)
            # CLI spinner runs in a daemon thread; sync sleep is acceptable here.
            time.sleep(0.1)

    t = threading.Thread(target=_spin, daemon=True)
    t.start()

    def _done():
        nonlocal stop
        stop = True

    return _done
