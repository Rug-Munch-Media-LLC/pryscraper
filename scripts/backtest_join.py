"""Join odds snapshots to settled outcomes — refuse, never silently drop.

The exporter used to accept only an already-settled CSV, so a real series could
not be produced from the two honest inputs the repo has: prices (bet time and
closing) and results. This module performs that join and makes the failure modes
loud:

* every odds row must provide ``event_id``, ``ts``, ``odds`` and ``closing_odds``
  with prices > 1.0 — a missing price is not a zero;
* every odds row must match exactly one outcome, by ``event_id`` first and by
  ``(date, home, away)`` second — **any unmatched row aborts the whole export**
  (exit 2) instead of shrinking the sample and inflating the result;
* a duplicate ``event_id`` on either side is ambiguous and aborts;
* a tie (push) has no winner: it is skipped **and counted**, and a series that is
  all pushes is unmeasurable.

Outcomes may carry an explicit ``won``/``winner`` or ``home_score`` /
``away_score`` plus a ``side``; scores are resolved by
``datasets/sports_data/results.derive_won`` so the rule lives in one place.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from backtest_core import Event

REPO_ROOT = Path(__file__).resolve().parents[1]


class JoinError(ValueError):
    """The join cannot be performed without inventing or dropping data."""


def results_module():
    """Load datasets/sports_data/results.py without importing the heavy package."""
    path = REPO_ROOT / "datasets" / "sports_data" / "results.py"
    spec = importlib.util.spec_from_file_location("pry_sports_results", path)
    if spec is None or spec.loader is None:  # pragma: no cover - pathological
        raise JoinError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("pry_sports_results", module)
    spec.loader.exec_module(module)
    return module


def _ts(raw: object) -> float:
    """Parse epoch seconds or ISO-8601 (a numeric string is epoch)."""
    text = str(raw or "").strip()
    numeric = text.replace(".", "", 1).lstrip("+-")
    if numeric.isdigit():
        return float(text)
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()


def _price(row: dict, key: str) -> float:
    """Parse a decimal price, refusing anything that is not a real quote > 1.0."""
    text = str(row.get(key, "")).strip().replace(".", "", 1).lstrip("+-")
    raw = row.get(key)
    if not text.isdigit() or str(raw).strip() in {"", "0", "0.0"}:
        raise JoinError(f"{row.get('event_id')!r}: missing/invalid {key}: {raw!r}")
    value = float(str(raw))
    if value <= 1.0:
        raise JoinError(f"{row.get('event_id')!r}: {key} must be > 1.0, got {value}")
    return value


def read_rows(path: str | Path) -> list[dict]:
    """Read a CSV or JSON row list (JSON may be a list or ``{"items": [...]}``)."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        data = json.loads(text)
        rows = data.get("items", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise JoinError(f"{p}: JSON must be a list of objects")
        return [dict(r) for r in rows]
    return [dict(r) for r in csv.DictReader(text.splitlines())]


def load_outcomes(path: str | Path) -> dict[str, dict]:
    """Index outcomes by ``event_id``; duplicates abort."""
    by_id: dict[str, dict] = {}
    for row in read_rows(path):
        eid = str(row.get("event_id") or "").strip()
        if not eid:
            raise JoinError(f"{path}: outcome row without event_id: {row!r}")
        if eid in by_id:
            raise JoinError(f"{path}: duplicate outcome event_id {eid!r}")
        by_id[eid] = row
    if not by_id:
        raise JoinError(f"{path}: no outcomes")
    return by_id


def _won(row: dict, side: str) -> bool | None:
    explicit = row.get("won", row.get("winner", row.get("home_winner")))
    if explicit not in (None, ""):
        text = str(explicit).strip().lower()
        if text in {"1", "true", "win", "won", "yes", "home"}:
            return True
        if text in {"0", "false", "loss", "lost", "no", "away"}:
            return False
        raise JoinError(f"{row.get('event_id')!r}: not an outcome: {explicit!r}")
    home, away = row.get("home_score"), row.get("away_score")
    if home in (None, "") or away in (None, ""):
        raise JoinError(f"{row.get('event_id')!r}: no won/winner and no scores")
    return results_module().derive_won(int(home), int(away), side)


def _key(row: dict) -> tuple[str, str, str]:
    day = str(row.get("date") or row.get("ts") or "")[:10]
    norm = lambda v: " ".join(str(v or "").lower().split())  # noqa: E731
    return day, norm(row.get("home")), norm(row.get("away"))


def _row_id(row: dict, seen: set[str]) -> str:
    eid = str(row.get("event_id") or "").strip()
    if not eid:
        raise JoinError("odds row without event_id")
    if eid in seen:
        raise JoinError(f"duplicate odds event_id {eid!r}")
    seen.add(eid)
    return eid


def _side(row: dict, outcome: dict, default: str) -> str:
    side = str(row.get("side") or outcome.get("side") or default).strip().lower()
    if side not in {"home", "away"}:
        raise JoinError(f"{row.get('event_id')!r}: side must be home/away, got {side!r}")
    return side


def _event(row: dict, outcome: dict, side: str) -> Event:
    return Event(
        event_id=str(row.get("event_id")),
        ts=_ts(row.get("ts") or outcome.get("date")),
        odds=_price(row, "odds"),
        closing_odds=_price(row, "closing_odds"),
        won=bool(_won(outcome, side)),
    )


def join(
    odds_rows: list[dict], outcomes: dict[str, dict], default_side: str = "home"
) -> tuple[list[Event], int]:
    """Join and return ``(events, pushes)``; raise :class:`JoinError` on any gap."""
    by_key = {_key(o): o for o in outcomes.values()}
    events: list[Event] = []
    seen: set[str] = set()
    pushes = 0
    unmatched: list[str] = []
    for row in odds_rows:
        eid = _row_id(row, seen)
        outcome = outcomes.get(eid) or by_key.get(_key(row))
        if outcome is None:
            unmatched.append(eid)
            continue
        side = _side(row, outcome, default_side)
        if _won(outcome, side) is None:
            pushes += 1
            continue
        events.append(_event(row, outcome, side))
    if unmatched:
        raise JoinError(
            f"{len(unmatched)} odds row(s) have no settled outcome: {', '.join(unmatched[:8])}"
            + (" ..." if len(unmatched) > 8 else "")
        )
    if not events:
        raise JoinError(f"no usable settled bets ({pushes} push(es), {len(odds_rows)} row(s))")
    events.sort(key=lambda e: e.ts)
    return events, pushes

def load_series(
    odds_path: str | Path, outcomes_path: str | Path, side: str = "home"
) -> tuple[list[Event], int]:
    """Convenience: read both files and join them."""
    return join(read_rows(odds_path), load_outcomes(outcomes_path), default_side=side)

