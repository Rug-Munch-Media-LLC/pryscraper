#!/usr/bin/env python3
"""Single source of truth for docs counts.

Reads the actual numbers from source (never hardcoded) and patches every doc
that carries a stale literal:

- tool count        <- pry_mcp/tools.py PRY_TOOLS
- category count    <- src/pry/api/registry_metadata.py _categorize()
- fallback tiers    <- src/pry/engine/ultimate_scraper.py docstring ("N-tier")
- test file count   <- tests/test_*.py
- version           <- pyproject.toml

Idempotent: running twice changes nothing once everything is in sync.

Usage: .venv/bin/python scripts/docs_sync.py [--check]
  --check  exit 1 if any file would change (CI mode), without writing.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from docs_sync_rules import README_RULES, SKILL_RULES, SMITHERY_RULES, WEBSITE_RULES
from docs_sync_site import patch_site_config
from docs_sync_sweep import (
    actor_count,
    find_compounded,
    sweep,
    template_count,
    verify_llms_sections,
)

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))


# ── Fact extraction ──────────────────────────────────────────────────────────


def tool_count() -> int:
    from pry_mcp.tools import PRY_TOOLS

    return len(PRY_TOOLS)


def category_count() -> int:
    from pry.api.registry_metadata import _categorize
    from pry_mcp.tools import PRY_TOOLS

    return len({_categorize(t["name"]) for t in PRY_TOOLS})


def tier_count() -> int:
    src = (REPO / "src/pry/engine/ultimate_scraper.py").read_text()
    m = re.search(r'"""(\d+)-tier anti-detection scraper', src)
    if not m:
        raise SystemExit("cannot find tier count in ultimate_scraper.py docstring")
    return int(m.group(1))


def test_file_count() -> int:
    return len(glob.glob(str(REPO / "tests/test_*.py")))


def version() -> str:
    src = (REPO / "pyproject.toml").read_text()
    return re.search(r'^version\s*=\s*"([^"]+)"', src, re.M).group(1)


def server_json_tool_count() -> int:
    data = json.loads((REPO / "server.json").read_text())
    return len(data.get("tools", []))


FACTS = {}

# The single source every rule template draws from. Bare values only: a template
# supplies all formatting. See patch() for why the third rule element was removed.
VALUES: dict[str, str] = {}


# ── Patch helpers ────────────────────────────────────────────────────────────


def patch(
    path: Path,
    rules: list[tuple[str, ...]],
    check: bool,
    facts: dict[str, str],
    skip_re: re.Pattern[str] | None = None,
) -> list[str]:
    """Apply ``(pattern_fmt, repl_fmt)`` rules.

    Named placeholders (``{tools}``, ``{tiers}``...) resolve from the caller's
    ``facts`` mapping, so
    an already-correct line rewrites to itself and the sweep is idempotent.
    ``skip_re`` protects lines that must never change (llms.txt's histogram).

    Rules are TWO elements on purpose. An earlier three-element form
    ``(pattern, repl, correct)`` fed ``correct`` into BOTH templates, so passing
    a pre-formatted value ("**15-tier anti-bot bypass**") instead of the bare
    number ("15") expanded the replacement into itself and corrupted the file on
    every run -- README badge read ``MCP-MCP-MCP-MCP-99_tools_tools_tools...``.
    Deriving the value from a single source removes the whole class of bug.
    """
    # Validate every rule BEFORE touching the filesystem: a malformed rule must
    # fail loudly, not after a half-applied edit or an unrelated file error.
    for rule in rules:
        if len(rule) != 2:
            msg = (
                "docs_sync: rule must be (pattern_fmt, repl_fmt), got "
                f"{len(rule)} elements: {rule!r}"
            )
            raise ValueError(msg)

    text = path.read_text()
    original = text
    notes: list[str] = []
    for pattern_fmt, repl_fmt in rules:
        # Per-RULE idempotence, not per-file. A file-level `if correct in text`
        # skipped every rule whenever the correct value appeared anywhere in the
        # file, so after the tool count moved 113 -> 99 the stale 113 lines were
        # never rewritten because "99" already occurred for an unrelated reason.
        # Each rule is anchored on both sides (e.g. \*\*\d+ MCP tools\*\*), so
        # re-matching its own output rewrites it to itself and no guard is needed.
        pattern = pattern_fmt.format(**facts)
        repl = repl_fmt.format(**facts)
        # Per line, so skip_re can protect a whole line. This guard is what
        # stops a broad pattern from re-matching its own insertion.
        out, hits = [], 0
        for ln in text.splitlines(keepends=True):
            if skip_re is not None and skip_re.match(ln):
                out.append(ln)
                continue
            new, _matched = re.subn(pattern, repl, ln)
            # Count only substitutions that ACTUALLY change the line. re.subn
            # returns a count for every match, including one that rewrites the
            # line to itself -- so a rule already satisfied still reported a
            # change and --check never converged.
            if new != ln:
                hits += 1
            out.append(new)
        if hits:
            notes.append(f"  {path.relative_to(REPO)}: {hits}x /{pattern[:60]}/")
            text = "".join(out)
    if text != original and not check:
        path.write_text(text)
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    check = args.check

    FACTS.update(
        tools=tool_count(),
        categories=category_count(),
        tiers=tier_count(),
        tests=test_file_count(),
        version=version(),
        server_tools=server_json_tool_count(),
        actors=actor_count(),
        templates=template_count(),
    )
    print(
        "facts: tools={tools} categories={categories} tiers={tiers} "
        "tests={tests} version={version} server.json tools={server_tools} "
        "actors={actors} templates={templates}".format(**FACTS)
    )
    if FACTS["tools"] != FACTS["server_tools"]:
        print(
            f"WARNING: server.json has {FACTS['server_tools']} tools, "
            f"PRY_TOOLS has {FACTS['tools']} — registry out of sync"
        )

    tools_n = str(FACTS["tools"])
    cats_n = str(FACTS["categories"])
    tests_n = str(FACTS["tests"])
    tiers_n = str(FACTS["tiers"])
    actors_n = str(FACTS["actors"])
    templates_n = str(FACTS["templates"])

    VALUES.update(
        tools=tools_n,
        categories=cats_n,
        tests=tests_n,
        tiers=tiers_n,
        actors=actors_n,
        templates=templates_n,
    )

    # Refuse to touch a repo whose docs already carry compounding damage. A
    # generic (\d+) rule would amplify it on every run, so stop and let a human
    # repair the text first. This is the guard that stops one bad run becoming
    # permanent, unreadable documentation.
    damaged = find_compounded()
    if damaged:
        print(
            "docs_sync: REFUSING TO RUN -- these docs already show compounding "
            "substitution damage. Repair them by hand first:",
            file=sys.stderr,
        )
        for loc in damaged[:20]:
            print(f"  {loc}", file=sys.stderr)
        return 2

    changes: list[str] = []

    # ── Generic sweep: any "N tools" / "N actors" / "N+ templates" that is
    # not the real count is rewritten, in every prose doc. A per-file rule
    # list drifts the moment a new doc lands; one sweep does not.
    changes += sweep(patch, check, VALUES)

    # ── Per-document rules. The rule sets live in docs_sync_rules.py; see that
    # module for why every rule is a two-element pair.
    changes += patch(REPO / "README.md", README_RULES, check, VALUES)
    changes += patch(REPO / "SKILL.md", SKILL_RULES, check, VALUES)

    web = REPO / "website/docs"
    for md in sorted(web.rglob("*.md")):
        changes += patch(md, WEBSITE_RULES, check, VALUES)

    changes += patch_site_config(patch, check, VALUES)

    changes += verify_llms_sections(FACTS["tools"], check)

    changes += patch(REPO / "smithery.yaml", SMITHERY_RULES, check, VALUES)

    if changes:
        print("changes:" if not check else "would change:")
        print("\n".join(changes))
        return 1 if check else 0
    print("all docs in sync ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
