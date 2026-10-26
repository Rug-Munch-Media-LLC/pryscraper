#!/usr/bin/env python3
"""Scrape success-rate matrix: turn "we can scrape site X" into a number.

One row per site: {site, method, http_status, bytes, parsed_fields,
latency_ms, verdict}. Verdicts are honest -- ok | wall | empty | error. A
challenge page is `wall`, a 200 with nothing extractable is `empty`; neither
is ever reported as `ok`.

Method is the cheapest tier on purpose: plain HTTP GET, no browser, no bypass,
no credentials. That is the tier the unlock ledger must keep green; escalation
tiers are separate evals.

Live calls are opt-in (--live or SCRAPE_MATRIX_LIVE=1) so CI stays offline.

    python evals/scrape_matrix.py --live
    python evals/scrape_matrix.py --live --baseline evals/scrape_matrix.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

if __package__ in (None, ""):  # run as `python evals/scrape_matrix.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from wall_detect import is_wall

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
TIMEOUT = 20.0
MAX_BODY = 4_000_000
MIN_BYTES = 512
RANK = {"ok": 3, "empty": 2, "wall": 1, "error": 0}
BLOCK_STATUS = frozenset({401, 403, 405, 429, 451, 503})
# Wall signals are a head signal: see evals/wall_detect.py (bounded prefix).
FIELD_MARKERS = ("<title", "og:title", 'name="description"', "<h1", "<article", "<main")
DEFAULT_SITES = {
    "syndication.twitter.com": "https://syndication.twitter.com/srv/timeline-profile/screen-name/AnthropicAI",
    "dexscreener.com": "https://dexscreener.com/",
    "coingecko.com": "https://www.coingecko.com/",
    "rugcheck.xyz": "https://rugcheck.xyz/",
    "docs.anthropic.com": "https://docs.anthropic.com/en/docs/overview",
    "github.com": "https://github.com/",
}
DEFAULT_OUT = Path("evals/scrape_matrix.json")


def count_fields(body: str) -> int:
    """Extractable fields: JSON keys/items, or HTML landmark markers."""
    text = body.lstrip()
    if text[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except ValueError:
            return 0
        return len(data) if isinstance(data, (dict, list)) else 0
    low = body.lower()
    return sum(1 for marker in FIELD_MARKERS if marker in low)


def classify(http_status: int, nbytes: int, parsed_fields: int, body: str,
             error: str | None = None) -> str:
    """Map one attempt to ok | wall | empty | error. Never optimistic."""
    if error:
        return "error"
    if http_status in BLOCK_STATUS:
        return "wall"
    if http_status == 0 or http_status >= 500:
        return "error"
    if is_wall(body):
        return "wall"
    if http_status != 200 or nbytes < MIN_BYTES or parsed_fields <= 0:
        return "empty"
    return "ok"


def fetch(url: str, timeout: float = TIMEOUT) -> tuple[int, str, str | None]:
    req = urllib.request.Request(  # noqa: S310 - fixed https URL
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310 - fixed https URL
            return resp.status, resp.read(MAX_BODY).decode("utf-8", "replace"), None
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_BODY).decode("utf-8", "replace") if exc.fp else ""
        return exc.code, body, None
    except Exception as exc:  # noqa: BLE001 - network/TLS/timeout all become `error`
        return 0, "", f"{type(exc).__name__}: {exc}"


def measure(site: str, url: str, timeout: float = TIMEOUT) -> dict:
    started = time.monotonic()
    status, body, error = fetch(url, timeout)
    latency_ms = round((time.monotonic() - started) * 1000)
    parsed = count_fields(body)
    nbytes = len(body.encode("utf-8"))
    row = {
        "site": site,
        "method": "http",
        "http_status": status,
        "bytes": nbytes,
        "parsed_fields": parsed,
        "latency_ms": latency_ms,
        "verdict": classify(status, nbytes, parsed, body, error),
        "url": url,
    }
    if error:
        row["error"] = error
    return row


def regressions(rows: list[dict], baseline: dict[str, str]) -> list[dict]:
    """Sites whose verdict got worse than the saved run. New sites are not regressions."""
    out = []
    for row in rows:
        was = baseline.get(row["site"])
        if was and RANK[row["verdict"]] < RANK.get(was, 0):
            out.append({"site": row["site"], "was": was, "now": row["verdict"]})
    return out


def load_baseline(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text())
    rows = data.get("rows", []) if isinstance(data, dict) else data
    return {row["site"]: row["verdict"] for row in rows if row.get("site")}


def line(row: dict) -> str:
    return (
        f"{row['verdict']:<5} {row['site']:<24} {row['http_status']:>3} "
        f"{row['bytes']:>8}B {row['parsed_fields']:>2}f {row['latency_ms']:>5}ms"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scrape success-rate matrix")
    ap.add_argument("--live", action="store_true",
                    default=os.environ.get("SCRAPE_MATRIX_LIVE") == "1")
    ap.add_argument("--sites", type=Path, help="JSON {site: url} override")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--baseline", nargs="?", const=str(DEFAULT_OUT), default=None,
                    help="compare with a saved run; exit 1 when a verdict regressed")
    ap.add_argument("--timeout", type=float, default=TIMEOUT)
    args = ap.parse_args(argv)

    sites = json.loads(args.sites.read_text()) if args.sites else DEFAULT_SITES
    if not args.live:
        for _site, _url in sites.items():
            pass
        return 0

    rows = [measure(site, url, args.timeout) for site, url in sites.items()]
    counts = Counter(row["verdict"] for row in rows)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "method": "http",
        "counts": {v: counts.get(v, 0) for v in ("ok", "wall", "empty", "error")},
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")

    for _row in rows:
        pass

    if args.baseline:
        base = load_baseline(Path(args.baseline))
        broke = regressions(rows, base)
        for _item in broke:
            pass
        return 1 if broke else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
