"""Pry CLI command handlers (one function per ``pry <command>``)."""

# ruff: noqa: T201 - a CLI writes to stdout by design

from __future__ import annotations

import base64
import json
import os
import sys
from typing import Any

from pry.misc.cli_helpers import BOLD, CYAN, GREEN, NC, RED, VERSION, YELLOW, _req, _spinner


def cmd_open(url: str, **opts: Any) -> None:
    """Scrape a URL and print clean markdown or JSON.

    ``offset``/``limit`` window the extracted markdown so very large bodies
    (e.g. API JSON responses) can be paged in chunks.
    """
    output_json = bool(opts.get("output_json", False))
    schema_path = opts.get("schema_path")
    timeout = int(opts.get("timeout", 30))
    offset = int(opts.get("offset", 0))
    limit = int(opts.get("limit", 100000))
    payload = {"url": url, "timeout": timeout, "offset": offset, "limit": limit}
    if schema_path:
        with open(schema_path) as f:
            payload["jsonSchema"] = json.load(f)
    done = _spinner(f"Prying open {url[:50]}")
    try:
        data = _req("POST", "/v1/scrape", payload, timeout + 10)
    finally:
        done()
    print(f"{GREEN}✓{NC} Pry opened {url}\n", end="", file=sys.stderr)
    if output_json or schema_path:
        print(json.dumps(data, indent=2))
    else:
        md = data.get("data", {}).get("markdown", "")
        print(md[:100000] if md else f"{YELLOW}(no content extracted){NC}")


def cmd_watch(url: str, webhook: str = "", interval: int = 3600) -> None:
    """Register a page for change monitoring."""
    done = _spinner(f"Registering {url[:50]} for monitoring")
    try:
        data = _req("POST", "/v1/watch", {"url": url, "webhook": webhook, "interval": interval}, 45)
    finally:
        done()
    if data.get("success"):
        status = data.get("data", {}).get("status", "registered")
        print(f"{GREEN}✓{NC} Watching {url} (status: {status})")
        if webhook:
            print(f"  Webhook: {webhook}")
    else:
        print(f"{RED}✖ {data.get('error', 'Watch failed')}{NC}")


def cmd_crawl(url: str, max_pages: int = 10, output: str | None = None, timeout: int = 120) -> None:
    """Crawl multiple pages from a starting URL."""
    done = _spinner(f"Crawling {url[:50]} (up to {max_pages} pages)")
    try:
        data = _req("POST", "/v1/crawl", {"url": url, "maxPages": max_pages}, timeout)
    finally:
        done()
    pages = data.get("data", {}).get("pages", [])
    print(f"{GREEN}✓{NC} Crawled {len(pages)} page(s) from {url}")
    if output:
        with open(output, "w") as f:
            json.dump(pages, f, indent=2)
        print(f"  Saved to {output}")
    else:
        for p in pages[:5]:
            t = p.get("title", "untitled")[:60]
            print(f"  • {t}  ({p.get('method', '?')})")
        if len(pages) > 5:
            print(f"  ... and {len(pages) - 5} more")


def cmd_batch(filepath: str, template_str: str = "", timeout: int = 30) -> None:
    """Scrape URLs from a file using a template."""
    if not os.path.exists(filepath):
        print(f"{RED}✖ File not found: {filepath}{NC}")
        sys.exit(1)
    template = json.loads(template_str) if template_str else {"body": "body"}
    done = _spinner(f"Processing {filepath}")
    try:
        data = _req(
            "POST",
            "/v1/batch-file",
            {"filepath": filepath, "template": template, "timeout": timeout},
            timeout * 5,
        )
    finally:
        done()
    results = data.get("data", {}).get("results", [])
    ok = sum(1 for r in results if r.get("status") == "ok")
    err = len(results) - ok
    print(f"{GREEN}✓{NC} Batch complete: {ok} OK, {err} errors from {len(results)} URLs")
    for r in results[:10]:
        status = f"{GREEN}✓{NC}" if r.get("status") == "ok" else f"{RED}✖{NC}"
        print(f"  {status} {r.get('url', '')[:70]}")
    if err:
        print(f"  {YELLOW}Errors: {err}{NC}")


def cmd_parse(url: str, timeout: int = 60) -> None:
    """Parse a document to text."""
    done = _spinner(f"Parsing {url[:50]}")
    try:
        data = _req("POST", "/v1/parse", {"url": url, "timeout": timeout}, timeout + 10)
    finally:
        done()
    text = data.get("data", {}).get("text", "")
    fmt = data.get("data", {}).get("format", "unknown")
    pages = data.get("data", {}).get("pages", 0)
    print(f"{GREEN}✓{NC} Parsed {fmt} ({pages} pages, {len(text)} chars)")
    print(text[:50000])


def cmd_screenshot(url: str, output: str | None = None, timeout: int = 30) -> None:
    """Take a screenshot."""
    done = _spinner(f"Capturing {url[:50]}")
    try:
        data = _req("POST", "/v1/screenshot", {"url": url}, timeout + 10)
    finally:
        done()
    b64 = data.get("data", {}).get("screenshot", "")
    if not b64:
        print(f"{RED}✖ No screenshot returned{NC}")
        sys.exit(1)
    if output:
        with open(output, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"{GREEN}✓{NC} Screenshot saved to {output}")
    else:
        print(f"{GREEN}✓{NC} Screenshot: {len(b64)} bytes (base64)")


def cmd_migrate() -> None:
    """Run pending database migrations (alembic upgrade head)."""
    from pry.core.db import run_migrations

    run_migrations()
    print(f"{GREEN}✓{NC} Migrations up to date")


def cmd_run(pryfile_path: str = "pry.yml") -> None:
    """Execute jobs defined in pry.yml."""
    if not os.path.exists(pryfile_path):
        print(f"{RED}✖ No {pryfile_path} found{NC}")
        print(f"  Create one: {CYAN}pry open https://example.com{NC}")
        sys.exit(1)
    done = _spinner(f"Running jobs from {pryfile_path}")
    try:
        data = _req("POST", "/v1/run", {"path": pryfile_path}, 120)
    finally:
        done()
    jobs = data.get("data", {}).get("jobs", [])
    print(f"{GREEN}✓{NC} Executed {len(jobs)} job(s)")
    for j in jobs:
        name = j.get("name", "unnamed")
        status = j.get("status", "error")
        if status == "ok":
            print(
                f"  {GREEN}✓{NC} {name} ({j.get('method', '?')}) — {j.get('content_length', 0)} chars"
            )
        else:
            print(f"  {RED}✖{NC} {name} — {j.get('error', 'failed')}{NC}")


def cmd_serve(host: str = "127.0.0.1", port: int = 8005) -> None:
    """Start the Pry API server."""
    print(f"{CYAN}🔧 Starting Pry v{VERSION} on {host}:{port}{NC}")
    print(f"  Dashboard: http://localhost:{port}/dashboard")
    print(f"  Health:    http://localhost:{port}/health")
    os.execvp("uvicorn", ["uvicorn", "pry.api.api:app", "--host", host, "--port", str(port)])  # noqa: S606 S607 - execvp replaces the process; "uvicorn" from PATH. src-layout: a bare "api:app" cannot be imported


def cmd_completions(shell: str = "bash") -> None:
    """Print shell-autocomplete installation instructions.

    Pry does not currently ship a `_PRY_COMPLETE` env-var handler, so we do
    not silently write a broken eval line into the user's shell rc file.
    Print copy/paste instructions instead.
    """
    if shell not in ("bash", "zsh", "fish"):
        print(f"{YELLOW}Unknown shell: {shell}. Supported: bash, zsh, fish{NC}")
        return
    print(f"{BOLD}Pry shell autocomplete ({shell}){NC}")
    print()
    if shell == "bash":
        print("  Add the following line to your ~/.bashrc:")
        print(f'    {CYAN}eval "$(register-python-argcomplete pry)"{NC}')
        print()
        print("  install dependency: pip install argcomplete")
    elif shell == "zsh":
        print("  Add the following line to your ~/.zshrc:")
        print(f'    {CYAN}eval "$(register-python-argcomplete --shell zsh pry)"{NC}')
        print()
        print("  install dependency: pip install argcomplete")
    else:
        print("  Add the following line to ~/.config/fish/config.fish:")
        print(f"    {CYAN}register-python-argcomplete --shell fish pry | source{NC}")
        print()
        print("  install dependency: pip install argcomplete")
    print()
    print(f"{YELLOW}Note:{NC} Pry does not yet wire `_PRY_COMPLETE` itself; once it")
    print("  does, this command will switch to a one-shot installer.")


