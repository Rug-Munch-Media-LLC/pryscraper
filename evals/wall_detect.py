"""Does this HTTP body look like a bot wall, or like a normal page?

Judged on a bounded prefix only: `wall` must come from the document head
(`<title>` or challenge scaffolding), never from a marker found anywhere in a
multi-hundred-KB body. Measured false positive this fixes: github.com, HTTP 200,
580 KB, reported `wall` because its signup markup contains the word "captcha".
"""

from __future__ import annotations

import re

PREFIX_BYTES = 4096
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
# Only meaningful inside <title>: ordinary pages use these words in their chrome.
TITLE_MARKERS = (
    "just a moment", "attention required", "access denied", "are you a robot",
    "captcha", "checking your browser", "ddos protection", "security check",
)
# Challenge scaffolding no normal page ships in its <head>.
BODY_MARKERS = (
    "just a moment", "attention required",  # interstitial phrases, prefix-only
    "cf-challenge", "cf_chl_opt", "cf_chl_", "challenge-platform", "px-captcha",
    "enable javascript and cookies", "checking your browser", "ddos protection",
    "are you a robot", "incapsula",
)


def page_title(body: str) -> str:
    """Lowercased, whitespace-collapsed <title> from the prefix, or ""."""
    match = TITLE_RE.search((body or "")[:PREFIX_BYTES])
    return " ".join(match[1].split()).lower() if match else ""


def is_wall(body: str) -> bool:
    """True only when the document head carries a challenge signal."""
    head = (body or "")[:PREFIX_BYTES]
    title = page_title(head)
    if title and any(marker in title for marker in TITLE_MARKERS):
        return True
    low = head.lower()
    return any(marker in low for marker in BODY_MARKERS)
