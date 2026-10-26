"""Pry — CAPTCHA ladder doctor.

Prints the ladder order, which token providers are unavailable for lack of a
key, the file-first provisioning path, and whether FlareSolverr answers.
``--keys-only`` prints just the provisioning instructions (``make captcha-keys``).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import json
import sys

KEYS_BLOCK = """CAPTCHA solver keys — file first, env last
  file : $PRY_CAPTCHA_ENV_FILE  (chmod 600, KEY=VALUE lines; default /etc/pry/captcha.env)
  env  : PRY_CAPTCHA_CAPSOLVER_API_KEY / PRY_CAPTCHA_2CAPTCHA_API_KEY

  PRY_CAPTCHA_CAPSOLVER_API_KEY=<capsolver key>
  PRY_CAPTCHA_2CAPTCHA_API_KEY=<2captcha key>

The free lanes (flaresolverr, image OCR) need no key and run today.
A key added to the file is used on the next process start — no code change.
"""


async def _flaresolverr_ok() -> bool:
    from pry.engine.captcha.flaresolverr import flaresolverr_fetch

    solution = await flaresolverr_fetch("https://example.com", 15)
    return solution.ok


async def main(argv: list[str]) -> int:
    if "--keys-only" in argv:
        print(KEYS_BLOCK)
        return 0
    from pry.engine.captcha.diagnostics import captcha_diagnostics

    report = captcha_diagnostics()
    report["flaresolverr_reachable"] = await _flaresolverr_ok()
    print(json.dumps(report, indent=2))
    if report["token_providers_unavailable"]:
        print(
            "\nLOUD: token providers unavailable -> "
            + ", ".join(report["token_providers_unavailable"])
            + f"\n  provision in {report['keys_file']} (see `make captcha-keys`)",
            file=sys.stderr,
        )
    if not report["flaresolverr_reachable"]:
        print("WARN: FlareSolverr is not answering; free JS lane is down", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
