"""Site-config fixes that are not counts.

``docs_sync.py`` owns the *numbers*. This module owns the handful of
non-numeric corrections the docs site still needs: the canonical docs
URL, broken-link strictness, the repo URL now that Forgejo is private,
and a Discord link that no longer resolves. Kept separate so the count
sweep in ``docs_sync.py`` stays the one place a number can change.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS_CONFIG = REPO / "website/docusaurus.config.js"

_CODEBERG = "https://codeberg.org/RugMunchMedia/pryscraper"

RULES: list[tuple[str, str]] = [
    (
        r'url: "https://docs\.pry\.rugmunch\.io"',
        'url: "https://docs.pryscraper.com"',
    ),
    (r'onBrokenLinks: "warn"', 'onBrokenLinks: "throw"'),
    (r"https://git\.rugmunch\.io/RugMunchMedia/pryscraper", _CODEBERG),
    (
        r'\s*\{{\ label: "Discord", href: "https://discord\.gg/pry" \}},\n',
        "\n",
    ),
]


def patch_site_config(patch: object, check: bool, facts: dict[str, str]) -> list[str]:
    """Apply :data:`RULES` to the docusaurus config. ``patch`` is injected."""
    if not DOCS_CONFIG.exists():
        return []
    return patch(DOCS_CONFIG, RULES, check, facts)  # type: ignore[operator]
