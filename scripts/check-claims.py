#!/usr/bin/env python3
"""Fail when public copy drifts from the code it describes.

Truth is read from the code, never hard-coded here:
  * PRY_TOOLS          pry_mcp/tools/__init__.py
  * X402_PRICING       src/pry/payments/x402/scheme/pricing/catalog.py
  * SUPPORTED_NETWORKS src/pry/payments/x402/scheme/networks.py

Stdlib only. Exit 0 when every scanned file is consistent, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB_REPO = REPO.parent / "pry-web"

SCAN_SUFFIXES = {".md", ".mdx", ".txt", ".json", ".yaml", ".yml", ".astro", ".ts", ".tsx", ".html"}
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".hypothesis",
    "dist",
    "build",
    ".docusaurus",
}
# Source trees are not public copy; they are excluded by top-level path only,
# so landing/src (pry-web) is still scanned.
SKIP_TOP_DIRS = {
    "pryscraper": {"src", "pry_mcp", "tests", "scripts"},
    "pry-web": {"tests", "scripts"},
}
SKIP_FILES = {
    "uv.lock",
    "requirements.lock",
    "requirements.docker.lock",
    "package-lock.json",
    # Historical records: they quote the old copy on purpose.
    "CHANGELOG.md",
    "ENTERPRISE-AUDIT-2026-10-17.md",
}

CHECK_LABELS = (
    "stale tool count 76",
    "stale price $0.005",
    "stale chain count 6",
    "guaranteed profit",
    "risk-free bets",
    "aggregateRating",
    "comparative claim",
)


def load_truth() -> tuple[int, dict[str, float], int]:
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "src"))
    from pry.payments.x402.scheme.networks import SUPPORTED_NETWORKS
    from pry.payments.x402.scheme.pricing.catalog import X402_PRICING
    from pry_mcp.tools import PRY_TOOLS

    prices = {name: float(info["price_usd"]) for name, info in X402_PRICING.items()}
    return len(PRY_TOOLS), prices, len(SUPPORTED_NETWORKS)


def compile_checks(tool_count: int, chain_count: int) -> list[tuple[str, re.Pattern[str]]]:
    if tool_count == 76 or chain_count == 6:
        sys.exit("truth equals a stale literal; the check could not distinguish drift")
    patterns = {
        "stale tool count 76": r"\b76\s*(?:\+\s*)?(?:MCP\s+)?tools?\b"
        r"|['\"]76['\"][^\n]{0,30}MCP tools",
        # Only the headline scrape price is stale. extract/ocr really do cost
        # $0.005, so a blanket match would flag the truth.
        "stale price $0.005": (
            r"\$0\.005\s*(?:per\s+)?(?:scrape|request|call|page|url)\b"
            r"|scrape[^|\n]{0,40}\$0\.005"
            r"|\$0\.005[^|\n]{0,40}scrape"
            r"|(?:from|starting at|only)\s*\$0\.005"
        ),
        "stale chain count 6": r"\b6\s*(?:payment\s+)?(?:chains|networks)\b"
        r"|['\"]6['\"][^\n]{0,30}payment chains",
        "guaranteed profit": r"guaranteed[\s-]?profit",
        "risk-free bets": r"risk[\s-]?free\s+bets?",
        "aggregateRating": r"aggregateRating|ratingValue",
        "comparative claim": r"more MCP tools than any competitor|no competitor has this",
    }
    return [(label, re.compile(patterns[label], re.IGNORECASE)) for label in CHECK_LABELS]


def iter_files() -> list[Path]:
    found: set[Path] = set()
    for root in (REPO, WEB_REPO):
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            rel = path.relative_to(root)
            if path.name in SKIP_FILES or SKIP_DIR_NAMES.intersection(rel.parts):
                continue
            if rel.parts and rel.parts[0] in SKIP_TOP_DIRS.get(root.name, set()):
                continue
            found.add(path)
    return sorted(found)


def display(path: Path) -> str:
    for root in (REPO, WEB_REPO):
        try:
            return f"{root.name}/{path.relative_to(root)}"
        except ValueError:
            continue
    return str(path)


def main() -> int:
    tool_count, prices, chain_count = load_truth()
    checks = compile_checks(tool_count, chain_count)
    files = iter_files()

    hits: list[tuple[Path, int, str, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, regex in checks:
                if regex.search(line):
                    hits.append((path, lineno, label, line.strip()[:160]))

    print(
        f"truth: {tool_count} MCP tools | {chain_count} payment chains "
        f"| scrape ${prices['scrape']:.3f} | crawl ${prices['crawl']:.3f}"
    )
    if not hits:
        print(f"OK: {len(files)} scanned files carry no stale claim")
        return 0

    print(f"FAIL: {len(hits)} stale claim(s) across {len({h[0] for h in hits})} file(s)")
    for path, lineno, label, snippet in hits:
        print(f"  {display(path)}:{lineno}: [{label}] {snippet}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
