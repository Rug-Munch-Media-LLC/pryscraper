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


def generic_rules() -> list[tuple[str, str]]:
    """Return ``(pattern, repl, correct)`` rules for every count phrasing.

    Tool counts match ANY integer, never an enumerated stale literal. An
    enumerated list was the original design and it rots silently: when the real
    count moved 113 -> 99, every doc still said 113, so 113 was absent from the
    stale list and none of those lines were ever rewritten. The list needed a
    hand edit on every change to the tool set.

    A bare ``\\d+`` is safe because every pattern is anchored on BOTH sides, so a
    rule re-matching its own output rewrites it to itself. The earlier
    compounding corruption came from UNANCHORED ``\\d{2,3}`` matching part of an
    inserted number ("****113 MCP tools** MCP tools**"), which these cannot do.
    Per-category counts are excluded by the caller's ``skip_re``, so the sweep
    never rewrites them. ``correct`` is retained for ``patch()``'s signature.
    """
    return [
        (r"\b\d+ MCP tools\b", "{tools} MCP tools"),
        (r"\b\d+-tool\b", "{tools}-tool"),
        (r"\b\d+ tools\b", "{tools} tools"),
        # comparison tables: "### Tools (112 total," and "| MCP tools | **112** |"
        (r"\b\d+ total,", "{tools} total,"),
        (r"(tools\s*\|\s*\*\*)\d+(\*\*)", r"\g<1>{tools}\g<2>"),
        (r"MCP Layer \(\d+ tools\)", "MCP Layer ({tools} tools)"),
        (r"\b\d+ (?:Apify )?[Aa]ctors\b", "{actors} actors"),
        (r"\b\d+\+ templates\b", "{templates} templates"),
        (r"\b\d+\+ categories\b", "{categories} categories"),
    ]


# Signatures of a compounding-substitution accident: a bare \\d{2,3} pattern that
# re-matched part of its own inserted output. Once a doc contains one of these,
# a generic (\\d+) rule AMPLIFIES it on every run, so the sync must refuse to
# write rather than make it worse.
COMPOUNDED_RE = re.compile(
    # Only signatures that cannot occur in legitimate prose. An earlier draft
    # also matched r"-\w+-tier", which false-positived on the ADR filename
    # "0005-15-tier-scraping.md" -- a guard that cries wolf gets switched off.
    r"\*{4,}"  # ****99 MCP tools** MCP tools**
    r"|(?:MCP-){2,}"  # MCP-MCP-MCP-99_tools
    r"|(?:_tools){2,}"  # 99_tools_tools_tools
    r"|tools\*\*\s*[A-Za-z][A-Za-z ]*tools\*\*"  # 99 tools** MCP tools**
)


def find_compounded() -> list[str]:
    """Return ``file:line`` for every doc already showing compounding damage."""
    out: list[str] = []
    for path in sorted(REPO.glob("**/*.md")):
        if any(part in {".venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if COMPOUNDED_RE.search(line):
                out.append(f"{path.relative_to(REPO)}:{lineno}")
    return out


def sweep(patch: object, check: bool, facts: dict[str, str]) -> list[str]:
    """Apply :func:`generic_rules` to every doc. ``patch`` is injected.

    ``patch`` is ``docs_sync.patch``, passed in rather than imported so this
    module never depends on the hyphenated filename directly.
    """
    rules = generic_rules()
    notes: list[str] = []
    for rel in SWEEP_DOCS:
        path = REPO / rel
        if path.exists():
            notes += patch(path, rules, check, facts, CATEGORY_SUBTOTAL_RE)  # type: ignore[operator]
    return notes


def verify_llms_sections(tools_n: int, check: bool = False) -> list[str]:
    """Verify llms.txt against PRY_TOOLS, and REGENERATE the category histogram.

    The histogram used to be hand-maintained prose, so it silently went stale
    whenever a tool was added or removed -- the sweep skips these lines on
    purpose (``CATEGORY_SUBTOTAL_RE``), which left nothing keeping them honest.
    It is now derived from ``_categorize`` on every run.

    Returns notes describing what changed (or what would change under ``check``).
    """
    import collections

    from pry.api.registry_metadata import _categorize
    from pry_mcp.tools import PRY_TOOLS

    path = REPO / "llms.txt"
    llms = path.read_text()

    notes: list[str] = []
    n_sections = len(re.findall(r"^### pry_", llms, re.M))
    if n_sections != tools_n:
        notes.append(f"  llms.txt: {n_sections} tool sections vs {tools_n} in PRY_TOOLS")

    hist = collections.Counter(_categorize(t["name"]) for t in PRY_TOOLS)
    block = "".join(f"- {k}: {v} tool{'s' if v != 1 else ''}\n" for k, v in sorted(hist.items()))
    lines = llms.splitlines(keepends=True)
    idx = [i for i, ln in enumerate(lines) if re.match(r"^- \w+: \d+ tools?$", ln.rstrip())]
    if idx and "".join(lines[idx[0] : idx[-1] + 1]) != block:
        notes.append(
            f"  llms.txt: category histogram rewritten ({len(hist)} categories, "
            f"sum {sum(hist.values())})"
        )
        if not check:
            lines[idx[0] : idx[-1] + 1] = [block]
            path.write_text("".join(lines))
    return notes


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
