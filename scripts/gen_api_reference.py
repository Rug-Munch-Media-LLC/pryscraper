#!/usr/bin/env python3
"""Generate docs/ops/API-REFERENCE.md from openapi.json (deterministic).

Stdlib only. Reads the checked-in OpenAPI snapshot and emits one table per
tag: method, path, summary, auth required, 402 possible. No timestamps, no
network, sorted output — re-running yields byte-identical bytes.

Auth is NOT declared in the snapshot (no per-operation security), so the
column is inferred from the router guards and marked with a footnote.
The 402 column is inferred from the paid-endpoint table in
``src/pry/payments/x402_middleware/config.py::PAID_ENDPOINTS``.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "openapi.json"
OUT = ROOT / "docs" / "ops" / "API-REFERENCE.md"
METHODS = ("get", "post", "put", "patch", "delete", "head", "options")

# Prefix -> credential. Mirrors router guards; ordered, first match wins.
AUTH = (
    ("/pry-admin-dev/", "admin key + loopback"),
    ("/v1/keys", "Bearer"),
    ("/v1/api-keys", "Bearer"),
    ("/v1/hosting", "Bearer"),
    ("/v1/account", "Bearer"),
    ("/v1/billing", "Bearer"),
    ("/v1/gdpr", "Bearer"),
    ("/v1/pipelines", "Bearer"),
    ("/v1/proxy/configure", "Bearer"),
    ("/v1/config", "Bearer"),
)

# Mirrors PAID_ENDPOINTS in src/pry/payments/x402_middleware/config.py.
PAID = (
    "/v1/scrape",
    "/v1/crawl",
    "/v1/extract/css",
    "/v1/extract/llm",
    "/v1/templates/execute",
    "/v1/templates/batch",
    "/v1/automate",
    "/v1/monitor",
    "/v1/pdf/extract",
    "/v1/ultimate-scrape",
    "/v1/batch",
    "/v1/map",
    "/v1/capture",
    "/v1/graphql",
    "/v1/crypto/token-launches",
    "/v1/crypto/cex-listings",
    "/v1/crypto/token-security",
    "/v1/legal/",
    "/v1/realestate/",
    "/v1/jobs/",
    "/v1/travel/",
    "/v1/attention/",
    "/v1/local/",
    "/v1/gov/",
    "/v1/ip/",
    "/v1/sports/",
    "/v1/climate/",
    "/v1/research/",
    "/v1/events/",
    "/v1/freight/",
    "/v1/energy/",
    "/v1/food/",
    "/v1/supply/",
    "/v1/appstore/",
    "/v1/news/",
    "/v1/compliance/enforcement",
    "/v1/compliance/watch/",
    "/v1/deals/",
    "/v1/bidding/",
)

# Highest-traffic paid routes, per the product surface (not derivable from the spec).
NEXT_402 = ("/v1/scrape", "/v1/crawl", "/v1/extract/css", "/v1/extract/llm", "/v1/ultimate-scrape")


def cell(text: object) -> str:
    return str(text or "—").replace("|", "\\|").replace("\n", " ").strip()


def is_paid(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in PAID)


def collect_ops(spec: dict) -> list[tuple[str, str, dict]]:
    return [
        (path, method, op)
        for path, item in spec.get("paths", {}).items()
        for method, op in item.items()
        if method in METHODS
    ]


def group_by_tag(ops: list[tuple[str, str, dict]]) -> dict[str, list]:
    tags: dict[str, list] = {}
    for path, method, op in ops:
        for tag in dict.fromkeys(op.get("tags") or ["Untagged"]):
            tags.setdefault(tag, []).append((path, method, op))
    return tags


def header_lines(spec: dict, ops: list, tags: dict, documented: int) -> list[str]:
    info = spec.get("info", {})
    return [
        "# Pry — API Reference",
        "",
        "[//]: # (SPDX-License-Identifier: MIT)",
        "[//]: # (Copyright (c) 2026 Rug Munch Media LLC)",
        "",
        "<!-- GENERATED FILE — do not edit. Regenerate: python3 scripts/gen_api_reference.py -->",
        "",
        f"Source: `openapi.json` ({cell(info.get('title'))} v{cell(info.get('version'))}, "
        f"OpenAPI {cell(spec.get('openapi'))}).",
        "",
        f"- Paths: **{len(spec.get('paths', {}))}** · Operations: **{len(ops)}** · Tags: **{len(tags)}**",
        f"- `402` responses documented in the spec: **{documented} of {len(ops)}**",
        "- Auth column is inferred from router guards (`require_sensitive_config_auth`, "
        "hosting/admin gates), not from the spec — the spec declares no per-operation `security`.",
        "- Error shapes (RFC 7807, FastAPI 422, legacy `success:false`, x402 402): see "
        "[`docs/ERRORS.md`](../ERRORS.md).",
    ]


def coverage_lines(index: dict) -> list[str]:
    lines = [
        "",
        "## 402 coverage",
        "",
        "The audit found **0 of 371** operations declaring `402 Payment Required`, although the "
        "x402 middleware gates the paid routes below. Clients must treat an undocumented 402 as a "
        "normal payment challenge, not a failure. The next five routes to annotate:",
        "",
        "| # | Method | Path | Summary |",
        "|--:|--------|------|---------|",
    ]
    for n, path in enumerate(NEXT_402, 1):
        op = index.get((path, "post"), {})
        lines.append(f"| {n} | POST | `{path}` | {cell(op.get('summary'))} |")
    return lines


def tag_index(tags: dict) -> list[str]:
    lines = ["", "## Tags", ""]
    for tag in sorted(tags, key=str.lower):
        anchor = tag.lower().replace(" ", "-").replace("/", "")
        lines.append(f"- [`{tag}`](#{anchor}) — {len(tags[tag])} operations")
    return [*lines, ""]


def tag_sections(tags: dict) -> list[str]:
    lines: list[str] = []
    for tag in sorted(tags, key=str.lower):
        rows = sorted(tags[tag], key=lambda r: (r[0], r[1]))
        lines += [
            f"## {tag}",
            "",
            "| Method | Path | Summary | Auth | 402 possible |",
            "|--------|------|---------|------|--------------|",
        ]
        for path, method, op in rows:
            auth = next((v for p, v in AUTH if path.startswith(p)), "—")
            paid = "yes" if is_paid(path) else "—"
            if "402" in op.get("responses", {}):
                paid = "yes (documented)"
            lines.append(
                f"| {method.upper()} | `{path}` | {cell(op.get('summary'))} | {auth} | {paid} |"
            )
        lines.append("")
    return lines


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    ops = collect_ops(spec)
    tags = group_by_tag(ops)
    documented = sum(1 for _, _, op in ops if "402" in op.get("responses", {}))
    index = {(p, m): op for p, m, op in ops}
    lines = [
        *header_lines(spec, ops, tags, documented),
        *coverage_lines(index),
        *tag_index(tags),
        *tag_sections(tags),
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(ops)} operations, {len(tags)} tags, 402 documented {documented}"
    )


if __name__ == "__main__":
    main()
