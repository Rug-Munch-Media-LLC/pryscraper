"""CLI: bounded KOL discovery and reporting.

    python -m kol_discovery discover [--offline] [--max-accounts 50]
    python -m kol_discovery report [--json]

Caps are hard: at most :data:`MAX_ACCOUNTS` rows and at most one leaderboard
request per run (the client caches for 15 minutes). There is no crawl loop.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import sources
from .feeds import ingest_bio_rows, load_watchlist
from .kolscan import KolscanClient
from .registry import Registry
from .report import render_report
from .risk import RiskInputs, score_risk

MAX_ACCOUNTS = 100
MAX_LEADERBOARD_ROWS = 50
DATA_DIR = Path("kol_discovery") / "data"
REGISTRY_PATH = DATA_DIR / "kol_registry.json"
BIO_FIXTURES = DATA_DIR / "bio_fixtures.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _risk_rows() -> dict[str, dict[str, Any]]:
    """Per-handle risk observations captured alongside the bios."""
    payload = _read_json(BIO_FIXTURES, {})
    rows = payload.get("risk_inputs", {}) if isinstance(payload, dict) else {}
    return {str(k).casefold(): v for k, v in rows.items()}


def _enforce_cap(registry: Registry, max_accounts: int) -> int:
    """Hard account cap: newer rows beyond the cap are dropped, not merged."""
    cap = max(0, min(int(max_accounts), MAX_ACCOUNTS))
    dropped = 0
    for key in list(registry.accounts)[cap:]:
        del registry.accounts[key]
        dropped += 1
    return dropped


def _apply_risk(registry: Registry) -> None:
    rows = _risk_rows()
    for account in registry.accounts.values():
        raw = rows.get(account.handle.casefold())
        if not raw:
            continue
        inputs = RiskInputs(
            posts_sampled=int(raw.get("posts_sampled", 0)),
            promo_posts=int(raw.get("promo_posts", 0)),
            posts_with_contract=int(raw.get("posts_with_contract", 0)),
            promos_lowcap=int(raw.get("promos_lowcap", 0)),
            promos_total=int(raw.get("promos_total", 0)),
            promos_flagged_rug=int(raw.get("promos_flagged_rug", 0)),
            posts_deleted=int(raw.get("posts_deleted", 0)),
            followers=account.followers,
            median_engagement=float(raw.get("median_engagement", 0.0)),
            discloses_promos=bool(raw.get("discloses_promos", False)),
        )
        score, signals, reasons = score_risk(inputs)
        account.risk_score = score
        account.risk_signals = signals
        account.risk_signals["_reasons"] = reasons  # type: ignore[assignment]


def _ingest_leaderboard(registry: Registry, limit: int) -> dict[str, Any]:
    try:
        import httpx  # local import: keeps the offline path dependency-free
    except ImportError:
        return {"name": "kolscan_leaderboard", "status": "blocked", "reason": "httpx unavailable"}
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as http:
            accounts, wallet_only = KolscanClient(http=http).fetch(limit=limit)
    except Exception as exc:  # noqa: BLE001 - a source failure must not abort discovery
        return {"name": "kolscan_leaderboard", "status": "blocked", "reason": str(exc)[:200]}
    added = 0
    for account in accounts:
        if registry.add(account).status in {"added", "merged"}:
            added += 1
    return {
        "name": "kolscan_leaderboard",
        "status": sources.REACHABLE,
        "rows_received": len(accounts),
        "accounts_accepted": added,
        "wallet_only_rows": wallet_only,
    }


def cmd_discover(args: argparse.Namespace) -> int:
    rows, tally = sources.source_rows()
    registry = Registry(watchlist=load_watchlist(*args.watchlist), sources=rows)
    report: dict[str, Any] = {"sources": rows, "source_tally": tally}

    if not args.offline:
        report["leaderboard"] = _ingest_leaderboard(registry, min(args.limit, MAX_LEADERBOARD_ROWS))
    fixtures = _read_json(Path(args.fixtures), {})
    report["bio_ingest"] = ingest_bio_rows(registry, list(fixtures.get("accounts", [])))
    report["accounts_dropped_by_cap"] = _enforce_cap(registry, args.max_accounts)
    _apply_risk(registry)

    out = registry.save(Path(args.out))
    report["registry"] = str(out)
    report["stats"] = registry.stats()
    print(json.dumps(report, indent=2))  # noqa: T201 - CLI output
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    data = _read_json(Path(args.registry), None)
    if data is None:
        print(f"no registry at {args.registry} — run discover first", file=sys.stderr)  # noqa: T201
        return 2
    if args.json:
        print(json.dumps(data.get("stats", {}), indent=2))  # noqa: T201 - CLI output
        return 0
    sys.stdout.write(render_report(data, limit=args.limit))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kol_discovery")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="bounded discovery run")
    discover.add_argument("--offline", action="store_true", help="skip network sources")
    discover.add_argument("--limit", type=int, default=MAX_LEADERBOARD_ROWS)
    discover.add_argument("--max-accounts", type=int, default=MAX_ACCOUNTS)
    discover.add_argument("--fixtures", default=str(BIO_FIXTURES))
    discover.add_argument("--out", default=str(REGISTRY_PATH))
    discover.add_argument("--watchlist", action="append", default=[])
    discover.set_defaults(func=cmd_discover)

    report = sub.add_parser("report", help="render the registry")
    report.add_argument("--registry", default=str(REGISTRY_PATH))
    report.add_argument("--limit", type=int, default=10)
    report.add_argument("--json", action="store_true")
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
