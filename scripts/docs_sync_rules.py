"""Per-document rewrite rules for ``docs_sync.py``.

Extracted from ``docs_sync.main`` so the driver stays under the 200-line
structure cap and so every rule set can be read in one place.

Rules are ``(pattern_fmt, repl_fmt)`` pairs. Named placeholders resolve from the
caller's facts mapping; see ``docs_sync.patch`` for why the old third element
was removed (it let a caller pass a pre-formatted value where a bare number
belonged, and the replacement expanded into itself on every run).
"""

from __future__ import annotations

README_RULES: list[tuple[str, str]] = [
    (r"tests-\d+%2B?_passing", "tests-{tests}_files"),
    (r"\*\*\d+ MCP tools\*\*", "**{tools} MCP tools**"),
    (r"MCP-\d+_tools(?=-)", "MCP-{tools}_tools"),
    (r"\bAll \d+ tools are\b", "All {tools} tools are"),
    (r"\b\d+ MCP tools cover\b", "{tools} MCP tools cover"),
    (r"\*\*\d+ MCP tools across\b", "**{tools} MCP tools across"),
    (r"lists all \d+ tools\b", "lists all {tools} tools"),
    (
        r"aggregated manifest \(\d+ tools\b",
        "aggregated manifest ({tools} tools",
    ),
    (r"stdio\) \u2014 \d+ tools\b", "stdio) \u2014 {tools} tools"),
    (
        r"\*\*\d+-tier anti-bot bypass\*\*",
        "**{tiers}-tier anti-bot bypass**",
    ),
    (
        r"\*\*\d+-tier fallback chain\*\*",
        "**{tiers}-tier fallback chain**",
    ),
    (r"across \d+ categories", "across {categories} categories"),
    (
        r"### Tools \(\d+ total, \d+ categories\)",
        "### Tools ({tools} total, {categories} categories)",
    ),
    (r"MCP Layer \(\d+ tools\)", "MCP Layer ({tools} tools)"),
]

SKILL_RULES: list[tuple[str, str]] = [
    (r"via a \d+-tier fallback chain", "via a {tiers}-tier fallback chain"),
    (r"exposes \d+ tools for crawling", "exposes {tools} tools for crawling"),
    (
        r"- \*\*No API keys needed\*\* \u2014 self-hosted; the server is a FastAPI app "
        r"mounted at `/mcp` plus a stdio entry point \(`pry-mcp`\)\.",
        "- **Auth**: self-hosted by default \u2014 loopback-only when `PRY_API_KEY` "
        "is unset; set `PRY_API_KEY` to require `Authorization: Bearer` for remote "
        "clients. The server is a FastAPI app mounted at `/mcp` plus a stdio entry "
        "point (`pry-mcp`).",
    ),
]

WEBSITE_RULES: list[tuple[str, str]] = [
    (r"\b\d+ tools\b", "{tools} tools"),
    (r"\b\d+ MCP tools\b", "{tools} MCP tools"),
    (r"MCP tools \| \*\*\d+\*\*", "MCP tools | **{tools}**"),
    (r"MCP Layer \(\d+ tools\)", "MCP Layer ({tools} tools)"),
    (r"\b\d+\+ categories\b", "{categories}+ categories"),
    (
        r"Tools \(\d+ total, \d+ categories\)",
        "Tools ({tools} total, {categories} categories)",
    ),
    (
        r"That.s it\. No API key\.",
        "Bearer auth: free on loopback; set `PRY_API_KEY` for remote access.",
    ),
    (
        r"https://git\.rugmunch\.io/RugMunchMedia/pryscraper",
        "https://codeberg.org/RugMunchMedia/pryscraper",
    ),
]

SMITHERY_RULES: list[tuple[str, str]] = [
    (r"exposes \d+ tools", "exposes {tools} tools"),
]
