"""Generic prose sweep: rewrite any stale count to the real one.

``docs_sync.py`` patches a hand-listed set of phrases per file, which
drifts the moment a count is written in a new phrasing ("76 tools",
"112-tool", "110+ templates"). This module applies one pattern per
countable noun across every prose doc, so a count typed anywhere is
corrected from the source of truth on the next run.

Two rules make the sweep safe to re-run:

*Patterns match only STALE literals*, never an arbitrary number. A
``\\d{2,3}`` pattern also matches the correct value on the second run and
compounds it ("**113 MCP tools**" -> "****113 MCP tools** MCP tools**").
Enumerating the stale values is what makes the rewrite idempotent.

*Per-category subtotals are skipped.* llms.txt's "- sports_betting: 13
tools" histogram must not become the surface total.

Imported by ``docs_sync.py``; not run standalone.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# llms.txt's per-category histogram lines are subtotals, not the surface
# total; a blanket "N tools" rewrite would turn "13 tools" into "113 tools".
CATEGORY_SUBTOTAL_RE = re.compile(r"^\s*-\s*\w+:\s*\d+\s+tools?\b")

# Counts this project has actually published and got wrong. A doc that says
# anything outside these sets is not corrected — add a value here only when a
# real stale claim of that value is found in a doc.
STALE_TOOL_COUNTS = ("112", "76", "73", "108", "104", "71", "70")
STALE_ACTOR_COUNTS = ("112", "94", "110")
STALE_TEMPLATE_COUNTS = ("112", "100")
STALE_CATEGORY_COUNTS = "35"

# Every prose doc that may state a count. Adding a doc here makes it
# self-correcting rather than a future false claim.
SWEEP_DOCS = (
    "README.md",
    "AGENTS.md",
    "SKILL.md",
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
)


def _alt(values: tuple[str, ...]) -> str:
    return "|".join(values)


def generic_rules(
    tools_n: str, actors_n: str, templates_n: str, categories_n: str
) -> list[tuple[str, str, str]]:
    """Return ``(pattern, repl, correct)`` rules for every count phrasing.

    Every pattern is anchored to a known-stale literal, so applying the rules
    twice is a no-op. ``correct`` is retained for ``patch()``'s signature.
    """
    t, a, tm, c = (
        _alt(STALE_TOOL_COUNTS),
        _alt(STALE_ACTOR_COUNTS),
        _alt(STALE_TEMPLATE_COUNTS),
        _alt(STALE_CATEGORY_COUNTS),
    )
    return [
        (rf"\b({t}) MCP tools\b", f"{tools_n} MCP tools", f"{tools_n} MCP tools"),
        (rf"\b({t})-tool\b", f"{tools_n}-tool", f"{tools_n}-tool"),
        (rf"\b({t}) tools\b", f"{tools_n} tools", f"{tools_n} tools"),
        # comparison tables: "### Tools (112 total," and "| MCP tools | **112** |"
        (rf"\b({t}) total,", f"{tools_n} total,", f"{tools_n} total,"),
        (
            rf"(tools\s*\|\s*\*\*)(?:{t})(\*\*)",
            rf"\g<1>{tools_n}\g<2>",
            f"**{tools_n}**",
        ),
        (
            rf"MCP Layer \((?:{t}) tools\)",
            f"MCP Layer ({tools_n} tools)",
            f"MCP Layer ({tools_n} tools)",
        ),
        (
            rf"\b({a}) (?:Apify )?[Aa]ctors\b",
            f"{actors_n} actors",
            f"{actors_n} actors",
        ),
        (rf"\b({tm})\+ templates\b", f"{templates_n} templates", f"{templates_n} templates"),
        (
            rf"\b({c})\+ categories\b",
            f"{categories_n} categories",
            f"{categories_n} categories",
        ),
    ]


def sweep(
    patch: object,
    check: bool,
    tools_n: str,
    actors_n: str,
    templates_n: str,
    categories_n: str,
) -> list[str]:
    """Apply :func:`generic_rules` to every doc. ``patch`` is injected.

    ``patch`` is ``docs_sync.patch``, passed in rather than imported so this
    module never depends on the hyphenated filename directly.
    """
    rules = generic_rules(tools_n, actors_n, templates_n, categories_n)
    notes: list[str] = []
    for rel in SWEEP_DOCS:
        path = REPO / rel
        if path.exists():
            notes += patch(path, rules, check, CATEGORY_SUBTOTAL_RE)  # type: ignore[operator]
    return notes


def verify_llms_sections(tools_n: int) -> list[str]:
    """Report when llms.txt has a different number of tool sections than PRY_TOOLS."""
    llms = (REPO / "llms.txt").read_text()
    n = len(re.findall(r"^### pry_", llms, re.M))
    if n == tools_n:
        return []
    return [f"  llms.txt: {n} tool sections vs {tools_n} in PRY_TOOLS — regenerate llms.txt"]


def actor_count() -> int:
    """Number of Apify store actors: ``len(actor_factory.presets.ALL_PRESETS)``."""
    from actor_factory.presets import ALL_PRESETS

    return len(ALL_PRESETS)


def template_count() -> int:
    """Number of pre-built scraper templates: ``len(list_templates())``.

    Distinct from :func:`actor_count` — templates and actors are different
    objects, so the two numbers are allowed to differ.
    """
    from pry.commerce.template_engine import list_templates

    return len(list_templates())
