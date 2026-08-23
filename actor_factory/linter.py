"""Pry - Apify Actor Factory: store-readiness linter.

Encodes Apify's actor quality-score categories and Store publishing
requirements as deterministic checks (docs: actors/publishing/quality-score,
actors/publishing/test, actors/publishing/actor-readme):

- RELIABILITY / daily-test survival: required fields MUST carry a prefill;
  prefill URLs must point at stable targets so the platform's automated
  run (default input -> Succeeded + non-empty dataset in 5 minutes) passes.
- EASE OF USE: every input field documented; description length for SEO.
- PRICING TRANSPARENCY: PPE events present, priced, documented in README.
- CONGRUENCY: primary event name and title terminology must appear across
  description, README and input schema.
- TRUSTWORTHINESS: memory limits declared (cost control + least surprise).

lint_actor(spec) returns a list of findings; empty list = store-ready.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from actor_factory.spec import ActorSpec

MIN_DESCRIPTION_CHARS = 80
STABLE_PREFILL_HOSTS = (
    "example.com",
    "example.org",
    "httpbin.org",
    "docs.apify.com",
)


def lint_actor(spec: ActorSpec) -> list[str]:
    """Return store-readiness findings. Empty list = ready to publish."""
    findings: list[str] = []

    # ── Ease of use / SEO ──
    if len(spec.description) < MIN_DESCRIPTION_CHARS:
        findings.append(
            f"description too short ({len(spec.description)} chars) for store SEO "
            f"- aim for >= {MIN_DESCRIPTION_CHARS}"
        )
    for f in spec.inputs:
        if not f.description:
            findings.append(f"input '{f.name}' has no description (ease-of-use)")
        if f.type == "array" and f.editor is None:
            findings.append(f"array input '{f.name}' should declare an editor")

    # ── Reliability: survive the platform's daily default-input test ──
    for f in spec.inputs:
        if f.required and f.prefill is None and f.default is None:
            findings.append(
                f"required input '{f.name}' has neither prefill nor default - "
                "the daily automated test runs DEFAULT INPUT only"
            )
    urls_field = next((f for f in spec.inputs if f.name == "urls"), None)
    if urls_field is not None and urls_field.prefill:
        for entry in urls_field.prefill:
            url = entry.get("url", "") if isinstance(entry, dict) else str(entry)
            host = url.split("/")[2] if "://" in url else ""
            if host not in STABLE_PREFILL_HOSTS:
                findings.append(
                    f"prefill URL '{url}' is not a known-stable target "
                    f"{STABLE_PREFILL_HOSTS} - the daily test will run it"
                )

    # ── Pricing transparency ──
    if not spec.pricing_events:
        findings.append("no PPE pricing events defined")
    for e in spec.pricing_events:
        if len(e.description) < 20:
            findings.append(f"event '{e.name}' description too thin for transparency")

    # ── Trustworthiness ──
    if spec.max_memory_mbytes == 0:
        findings.append("maxMemoryMbytes not set")

    # ── Congruency ──
    if spec.pricing_events:
        primary = spec.primary_event()
        # Generic action verbs appear in every event name ("page-scraped")
        # and need not recur in copy; DOMAIN NOUNS are the congruency signal.
        _verbs = {
            "scraped",
            "crawled",
            "checked",
            "parsed",
            "extracted",
            "captured",
            "taken",
            "harvested",
            "emitted",
            "audited",
            "scanned",
            "detected",
            "updated",
            "collected",
            "screened",
            "probed",
            "compared",
            "page",
            "pages",
            "set",
        }
        tokens = {
            t for t in re.findall(r"[a-z]+", primary.name.replace("-", " ")) if t not in _verbs
        }
        haystack = (spec.title + " " + spec.description).lower()
        # substring match so plurals ("opportunities") satisfy singular
        # event nouns ("opportunity")
        missing = [t for t in sorted(tokens) if t not in haystack and t[:-1] not in haystack]
        if missing:
            findings.append(
                f"congruency: primary event domain noun(s) {missing} absent "
                "from title/description - keep terminology aligned"
            )
    return findings


README_MIN_WORDS = 300  # docs.apify.com/actors/publishing/actor-readme
REQUIRED_README_SECTIONS = (
    "## What can this Actor do?",
    "## Tutorial",
    "## How much will it cost",
    "## Input reference",
    "## Output reference",
    "## FAQ",
    "## Support",
)


def lint_generated(files: dict[str, Any]) -> list[str]:
    """Lint the GENERATED package against Store best practices."""
    findings: list[str] = []
    readme = files["README.md"].read_text()

    # Length: docs say "aim for at least 300 words".
    words = len(readme.split())
    if words < README_MIN_WORDS:
        findings.append(f"README too thin ({words} words; docs recommend >= {README_MIN_WORDS})")

    # Required sections (H2 headings form the Store table of contents).
    for section in REQUIRED_README_SECTIONS:
        if section not in readme:
            findings.append(f"README missing '{section}' section")

    # H1 must not appear in the body (Store renders the actor name as H1).
    body_after_frontmatter = readme
    if body_after_frontmatter.count("\n# ") > 0:
        findings.append("README contains an extra H1 - use H2/H3 only")

    # JSON output example present (docs: show users what they get).
    if "```json" not in readme:
        findings.append("README missing JSON output example")

    schema = json_loads_safe(files["INPUT_SCHEMA.json"].read_text())
    if schema.get("type") != "object":
        findings.append("input schema root type must be object")
    return findings


def json_loads_safe(text: str) -> dict[str, Any]:
    import json

    result: dict[str, Any] = json.loads(text)
    return result
