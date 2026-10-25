"""Feeds the registry ingests: bio fixtures, the cross-lane module, watchlists.

The X bio surface is robots-disallowed for us (see ``sources``), so bio input is
either (a) a fixtures file produced by a sanctioned capture, or (b) the
x-social-ops client when it is importable. We never scrape X ourselves.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from .bios import parse_bio
from .models import KolAccount, detect_chain
from .registry import Registry, normalize_watchlist
from .wallets import claim_from_bio


def optional_module(name: str) -> tuple[Any | None, str]:
    """Import a sibling lane's module without adding paths or patching sys.path."""
    try:
        if importlib.util.find_spec(name) is None:
            return None, f"{name} not importable in this environment"
        return importlib.import_module(name), ""
    except (ImportError, ModuleNotFoundError, ValueError) as exc:
        return None, f"{name} import failed: {exc}"


def load_watchlist(*paths: str | Path) -> set[str]:
    """Union of handle lists owned by other lanes; missing files are fine."""
    handles: list[str] = []
    for path in paths:
        candidate = Path(path)
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rows = payload.get("accounts", payload) if isinstance(payload, dict) else payload
        for row in rows or []:
            handles.append(row if isinstance(row, str) else str(row.get("handle", "")))
    return normalize_watchlist(handles)


def account_from_bio_row(row: dict[str, Any]) -> KolAccount:
    """Build an account from one captured public profile row."""
    bio = row.get("bio", "")
    facts = parse_bio(bio)
    account = KolAccount(
        platform=row.get("platform", "x"),
        handle=row.get("handle", ""),
        display_name=row.get("display_name", ""),
        followers=int(row.get("followers") or 0),
        bio=bio,
        bio_links=list(row.get("bio_links") or facts.links),
        telegram=row.get("telegram") or (facts.telegrams[0] if facts.telegrams else ""),
        projects=list(row.get("projects") or []),
        first_seen=row.get("first_seen", ""),
        last_checked=row.get("last_checked", ""),
        sources=list(row.get("sources") or ["bio_capture"]),
        confidence=float(row.get("confidence", 0.6)),
    )
    for address in row.get("declared_wallets") or []:
        try:
            detect_chain(address)
            account.wallets.append(claim_from_bio(bio, address, row.get("evidence_url", "")))
        except ValueError:
            continue  # unstated or malformed -> dropped, never guessed
    return account


def ingest_bio_rows(registry: Registry, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Ingest captured profiles; counts what was added, merged and refused."""
    tally = {"added": 0, "merged": 0, "skipped_watched": 0, "wallets_refused": 0}
    for row in rows:
        account = account_from_bio_row(row)
        if not account.handle:
            continue
        result = registry.add(account)
        tally[result.status] = tally.get(result.status, 0) + 1
        wanted = len(row.get("declared_wallets") or [])
        if wanted > len(account.wallets):
            tally["wallets_refused"] += wanted - len(account.wallets)
    return tally
