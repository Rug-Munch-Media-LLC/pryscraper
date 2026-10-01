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

from docs_sync_site import patch_site_config
from docs_sync_sweep import actor_count, sweep, template_count, verify_llms_sections

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


# ── Patch helpers ────────────────────────────────────────────────────────────


def patch(
    path: Path,
    rules: list[tuple[str, str, str]],
    check: bool,
    skip_re: re.Pattern[str] | None = None,
) -> list[str]:
    """Apply ``(pattern_fmt, repl_fmt, correct)`` rules.

    ``{n}`` placeholders in the patterns are filled with the correct value, so
    an already-correct line rewrites to itself. ``skip_re`` protects lines that
    must never change (llms.txt's per-category histogram).
    """
    text = path.read_text()
    original = text
    notes: list[str] = []
    for pattern_fmt, repl_fmt, correct in rules:
        if correct in text:
            continue
        pattern = pattern_fmt.replace("{n}", correct)
        repl = repl_fmt.replace("{n}", correct)
        # Per line, so skip_re can protect a whole line. This guard is what
        # stops a broad pattern from re-matching its own insertion.
        out, hits = [], 0
        for ln in text.splitlines(keepends=True):
            if skip_re is not None and skip_re.match(ln):
                out.append(ln)
                continue
            new, k = re.subn(pattern, repl, ln)
            hits += k
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

    changes: list[str] = []

    # ── Generic sweep: any "N tools" / "N actors" / "N+ templates" that is
    # not the real count is rewritten, in every prose doc. A per-file rule
    # list drifts the moment a new doc lands; one sweep does not.
    changes += sweep(patch, check, tools_n, actors_n, templates_n, cats_n)

    # ── README.md ────────────────────────────────────────────────────────
    changes += patch(
        REPO / "README.md",
        [
            (r"tests-\d+%2B?_passing", "tests-{n}_files", f"tests-{tests_n}_files"),
            (r"\*\*\d+ MCP tools\*\*", "**{n} MCP tools**", f"**{tools_n} MCP tools**"),
            (r"MCP-\d+_tools", "MCP-{n}_tools", f"MCP-{tools_n}_tools"),
            (
                r"\*\*\d+-tier anti-bot bypass\*\*",
                "**{n}-tier anti-bot bypass**",
                f"**{tiers_n}-tier anti-bot bypass**",
            ),
            (
                r"\*\*\d+-tier fallback chain\*\*",
                "**{n}-tier fallback chain**",
                f"**{tiers_n}-tier fallback chain**",
            ),
            (r"across \d+ categories", "across {n} categories", f"across {cats_n} categories"),
            (
                r"### Tools \(\d+ total, \d+ categories\)",
                "### Tools ({n})",
                f"### Tools ({tools_n} total, {cats_n} categories)",
            ),
            (r"MCP Layer \(\d+ tools\)", "MCP Layer ({n} tools)", f"MCP Layer ({tools_n} tools)"),
        ],
        check,
    )

    # ── SKILL.md ─────────────────────────────────────────────────────────
    changes += patch(
        REPO / "SKILL.md",
        [
            (
                r"via a \d+-tier fallback chain",
                "via a {n}-tier fallback chain",
                f"via a {tiers_n}-tier fallback chain",
            ),
            (
                r"exposes \d+ tools for crawling",
                "exposes {n} tools for crawling",
                f"exposes {tools_n} tools for crawling",
            ),
            (
                r"- \*\*No API keys needed\*\* — self-hosted; the server is a FastAPI app mounted at `/mcp` plus a stdio entry point \(`pry-mcp`\)\.",
                "- **Auth**: self-hosted by default — loopback-only when `PRY_API_KEY` is unset; "
                "set `PRY_API_KEY` to require `Authorization: Bearer` for remote clients. "
                "The server is a FastAPI app mounted at `/mcp` plus a stdio entry point (`pry-mcp`).",
                "- **Auth**: self-hosted by default",
            ),
        ],
        check,
    )

    # ── website/docs ─────────────────────────────────────────────────────
    web = REPO / "website/docs"
    for md in sorted(web.rglob("*.md")):
        changes += patch(
            md,
            [
                (r"\b73 tools\b", "{n} tools", f"{tools_n} tools"),
                (r"\b73 MCP tools\b", "{n} MCP tools", f"{tools_n} MCP tools"),
                (r"MCP tools \| \*\*\d+\*\*", "MCP tools | **{n}**", f"MCP tools | **{tools_n}**"),
                (
                    r"MCP Layer \(\d+ tools\)",
                    "MCP Layer ({n} tools)",
                    f"MCP Layer ({tools_n} tools)",
                ),
                (r"\b27 categories\b", "{n} categories", f"{cats_n} categories"),
                (
                    r"Tools \(\d+ total, \d+ categories\)",
                    "Tools ({n})",
                    f"Tools ({tools_n} total, {cats_n} categories)",
                ),
                (
                    r"That's it\. No API key\.",
                    "Bearer auth: free on loopback; set `PRY_API_KEY` for remote access.",
                    "Bearer auth: free on loopback",
                ),
                (
                    r"All \d+ tools are immediately available\. No API key required\.",
                    f"All {tools_n} tools are immediately available. Bearer auth is only enforced when "
                    "`PRY_API_KEY` is set (loopback-only by default).",
                    f"All {tools_n} tools are immediately available. Bearer auth",
                ),
                (
                    r"https://git\.rugmunch\.io/RugMunchMedia/pryscraper",
                    "https://codeberg.org/RugMunchMedia/pryscraper",
                    "https://codeberg.org/RugMunchMedia/pryscraper",
                ),
            ],
            check,
        )

    changes += patch_site_config(patch, check)

    changes += verify_llms_sections(FACTS["tools"])

    # ── smithery.yaml count comment ─────────────────────────────────────
    changes += patch(
        REPO / "smithery.yaml",
        [(r"exposes \d+ tools", "exposes {n} tools", f"exposes {tools_n} tools")],
        check,
    )

    if changes:
        print("changes:" if not check else "would change:")
        print("\n".join(changes))
        return 1 if check else 0
    print("all docs in sync ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
