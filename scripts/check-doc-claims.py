#!/usr/bin/env python3
"""Gate: documentation claims must match the code they describe.

Pry's docs are read by customers and by LLM clients that then call the API,
so a stale count or a non-existent route is a real defect, not a typo. This
gate fails when a doc states a tool/actor count that disagrees with
``pry_mcp.tools.PRY_TOOLS`` / ``actor_factory.presets.ALL_PRESETS``, names a
tool that does not exist, has an ``llms.txt`` entry whose body is not that
tool's own description (copy-paste), or advertises a paid x402 endpoint /
web-search REST path that no route serves. It never edits docs.

Usage: python3 scripts/check-doc-claims.py    Exit: 0 clean, 1 drift found.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_llms_txt import check_category_counts, check_llms_txt

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

# Docs that are allowed to state counts. Each is scanned for the count
# patterns below. Keep in sync with tests/test_doc_claims_gate.py.
COUNT_DOCS = (
    "README.md",
    "SKILL.md",
    "AGENTS.md",
    "llms.txt",
    "docs/ops/TOOLS-CATALOG.md",
    "docs/ops/ARCHITECTURE.md",
    "docs/ops/API-REFERENCE.md",
    "docs/FAQ.md",
    "website/docs/intro.md",
    "website/docs/mcp/overview.md",
    "website/docs/mcp/tools.md",
    "website/docs/mcp/discovery.md",
    "website/docs/quickstart.md",
    "smithery.yaml",
)

# "N tools", "N MCP tools", "Tools (N total)", "N tools across M categories"
_COUNT_RE = re.compile(
    r"(?<![\w.])(\d{2,3})\s+(?:MCP\s+)?tools\b|"
    r"tools\s*\|\s*\*\*(\d{2,3})\*\*|"
    r"Tools \((\d{2,3})\s+total",
    re.I,
)
# A category subtotal ("- sports_betting: 13 tools") is a per-category count,
# not the surface total. It is validated against the real per-category
# histogram by check_category_counts() instead of against PRY_TOOLS.
_CATEGORY_SUBTOTAL_RE = re.compile(r"^\s*-\s*\w+:\s*\d+\s+tools?\b")
# "N actors" / "N Apify actors" / "N+ catalog" style
_ACTOR_RE = re.compile(r"(?<![\w.])(\d{2,3})\s+(?:Apify\s+)?[Aa]ctors?\b")
_TOOL_REF_RE = re.compile(r"`(pry_[a-z0-9_]+)`")


def fail(problems: list[str], msg: str) -> None:
    problems.append(msg)


def check_counts(problems: list[str], facts: dict[str, int]) -> None:
    """Every stated tool/actor count must equal the live count."""
    for rel in COUNT_DOCS:
        path = REPO / rel
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if _CATEGORY_SUBTOTAL_RE.match(line):
                continue
            for m in _COUNT_RE.finditer(line):
                n = int(next(g for g in m.groups() if g))
                if n != facts["tools"]:
                    fail(
                        problems,
                        f"{rel}:{lineno}: states {n} tools, PRY_TOOLS has "
                        f"{facts['tools']} — run: python3 scripts/docs_sync.py",
                    )
            for m in _ACTOR_RE.finditer(line):
                n = int(next(g for g in m.groups() if g))
                if n not in (facts["actors"], facts["actors"] + 1):
                    fail(
                        problems,
                        f"{rel}:{lineno}: states {n} actors, ALL_PRESETS has "
                        f"{facts['actors']} — verify with "
                        f"`len(ALL_PRESETS)`",
                    )


def check_tool_refs(problems: list[str], real: set[str]) -> None:
    """A backticked pry_* name in a doc must be a real MCP tool."""
    for rel in (*COUNT_DOCS, "docs/ops/METHODS.md"):
        path = REPO / rel
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for name in _TOOL_REF_RE.findall(line):
                if name not in real:
                    fail(problems, f"{rel}:{lineno}: names unknown tool `{name}`")


def check_x402_manifest(problems: list[str], paths: set[str]) -> None:
    """Every paid endpoint the x402 manifest advertises must be a real route."""
    from pry.api.routers.core.well_known import x402_manifest

    manifest = asyncio.run(x402_manifest())
    for endpoint in manifest.get("endpoints", {}):
        if endpoint not in paths and endpoint.rstrip("/") + "/" not in paths:
            fail(
                problems,
                f"x402 manifest advertises paid endpoint `{endpoint}` but no "
                f"route serves it — remove it or add the route",
            )


def main() -> int:
    from actor_factory.presets import ALL_PRESETS
    from pry.api.api import app
    from pry.api.registry_metadata import _categorize
    from pry_mcp.tools import PRY_TOOLS

    descs = {t["name"]: t["description"] for t in PRY_TOOLS}
    real = set(descs)
    paths = set(app.openapi()["paths"])
    by_cat: dict[str, int] = {}
    for name in real:
        cat = _categorize(name)
        by_cat[cat] = by_cat.get(cat, 0) + 1
    facts = {"tools": len(PRY_TOOLS), "actors": len(ALL_PRESETS), "categories": len(by_cat)}
    print("facts: tools={tools} actors={actors} categories={categories}".format(**facts))

    problems: list[str] = []
    check_counts(problems, facts)
    check_tool_refs(problems, real)
    check_llms_txt(problems, descs, fail)
    check_category_counts(problems, by_cat, fail)
    check_x402_manifest(problems, paths)

    if problems:
        print(f"\nFAIL (doc claims): {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("docs match the code ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
