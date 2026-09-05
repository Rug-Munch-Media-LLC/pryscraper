# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

"""Pry CLI command handlers (one function per `pry <command>`)."""

from __future__ import annotations

import base64
import json
import os
import sys

import click

from pry.misc.cli_click import cli
from pry.misc.cli_helpers import BOLD, CYAN, GREEN, NC, RED, VERSION, YELLOW, _req, _spinner


def cmd_open(url, output_json=False, schema_path=None, timeout=30):
    """Scrape a URL and print clean markdown or JSON."""
    payload = {"url": url, "timeout": timeout}
    if schema_path:
        with open(schema_path) as f:
            payload["jsonSchema"] = json.load(f)
    done = _spinner(f"Prying open {url[:50]}")
    try:
        data = _req("POST", "/v1/scrape", payload, timeout + 10)
    finally:
        done()
    print(f"{GREEN}✓{NC} Pry opened {url}\n", end="")
    if output_json or schema_path:
        print(json.dumps(data, indent=2))
    else:
        md = data.get("data", {}).get("markdown", "")
        print(md[:100000] if md else f"{YELLOW}(no content extracted){NC}")


def cmd_watch(url, webhook="", interval=3600):
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


def cmd_crawl(url, max_pages=10, output=None, timeout=120):
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


def cmd_batch(filepath, template_str="", timeout=30):
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


def cmd_parse(url, timeout=60):
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


def cmd_screenshot(url, output=None, timeout=30):
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


def cmd_migrate():
    """Run pending database migrations (alembic upgrade head)."""
    from pry.core.db import run_migrations

    run_migrations()
    print(f"{GREEN}✓{NC} Migrations up to date")


def cmd_run(pryfile_path="pry.yml"):
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


def cmd_serve(host="127.0.0.1", port=8005):
    """Start the Pry API server."""
    print(f"{CYAN}🔧 Starting Pry v{VERSION} on {host}:{port}{NC}")
    print(f"  Dashboard: http://localhost:{port}/dashboard")
    print(f"  Health:    http://localhost:{port}/health")
    os.execvp("uvicorn", ["uvicorn", "api:app", "--host", host, "--port", str(port)])  # noqa: S606 S607 - execvp replaces the process; "uvicorn" resolved from PATH intentionally


def cmd_completions(shell="bash"):
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


def _print_usage() -> None:
    """Print the standard Pry usage block (no exit)."""
    print(f"{BOLD}Pry v{VERSION}{NC} — Pry open any website. {CYAN}pryscraper.com{NC}")
    print()
    print(f"  {BOLD}Usage:{NC}")
    print(f"    {CYAN}pry open <url>{NC}              Scrape a URL")
    print(f"    {CYAN}pry watch <url>{NC}             Monitor for changes")
    print(f"    {CYAN}pry crawl <url>{NC}             Crawl a site")
    print(f"    {CYAN}pry batch <file>{NC}            Batch scrape from a file")
    print(f"    {CYAN}pry parse <url>{NC}             Parse a document")
    print(f"    {CYAN}pry ss <url>{NC}                Take a screenshot")
    print(f"    {CYAN}pry run [pry.yml]{NC}           Execute job file")
    print(f"    {CYAN}pry migrate{NC}                 Run database migrations")
    print(f"    {CYAN}pry serve{NC}                   Start the server")
    print(f"    {CYAN}pry completions{NC}             Install autocomplete")
    print(f"    {CYAN}pry proxy ...{NC}               Manage proxy providers and signup")
    print()
    print(f"  {BOLD}Examples:{NC}")
    print("    pry open https://example.com")
    print("    pry open https://store.com --json --schema product.json")
    print("    pry watch https://site.com --webhook slack://...")
    print("    pry crawl https://docs.com --max-pages 20 -o data.json")
    print('    pry batch urls.txt --template \'{"price":".price"}\'')
    print("    pry run")
    print("    pry serve")
    print("    pry proxy list")
    print("    pry proxy signup brightdata")
    print()
    print(f"  {BOLD}Settings:{NC}")
    print("    PRY_URL=http://localhost:8005    (default)")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ("proxy", "wallets") and click is not None:
        cli.main(standalone_mode=False)
        return
    if len(sys.argv) < 2:
        _print_usage()
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    try:
        if cmd == "open" or cmd == "get" or cmd == "scrape":
            url = args[0] if args else input("URL: ")
            opts = {"output_json": "--json" in sys.argv, "timeout": 30}
            if "--schema" in sys.argv:
                opts["schema_path"] = sys.argv[sys.argv.index("--schema") + 1]
            if "--timeout" in sys.argv:
                opts["timeout"] = int(sys.argv[sys.argv.index("--timeout") + 1])
            cmd_open(url, **opts)

        elif cmd == "watch":
            url = args[0] if args else input("URL: ")
            webhook = sys.argv[sys.argv.index("--webhook") + 1] if "--webhook" in sys.argv else ""
            cmd_watch(url, webhook)

        elif cmd == "crawl":
            url = args[0] if args else input("URL: ")
            max_p = (
                int(sys.argv[sys.argv.index("--max-pages") + 1])
                if "--max-pages" in sys.argv
                else 10
            )
            out = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else None
            cmd_crawl(url, max_p, out)

        elif cmd == "batch":
            fp = args[0] if args else input("File: ")
            tmpl = sys.argv[sys.argv.index("--template") + 1] if "--template" in sys.argv else ""
            cmd_batch(fp, tmpl)

        elif cmd == "parse":
            url = args[0] if args else input("URL: ")
            cmd_parse(url)

        elif cmd in ("ss", "screenshot"):
            url = args[0] if args else input("URL: ")
            out = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else None
            cmd_screenshot(url, out)

        elif cmd == "run":
            cmd_run(args[0] if args else "pry.yml")

        elif cmd == "serve":
            port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8005
            cmd_serve(port=port)

        elif cmd in ("migrate", "db"):
            cmd_migrate()

        elif cmd in ("completions", "autocomplete"):
            shell = args[0] if args else "bash"
            cmd_completions(shell)

        elif cmd in ("-v", "--version", "version"):
            print(f"Pry v{VERSION}")

        elif cmd in ("-h", "--help", "help"):
            _print_usage()

        elif cmd == "proxy":
            if click is None:
                print(f"{RED}✖ click is not installed. Run: pip install click{NC}")
                sys.exit(1)
            cli.main(standalone_mode=False)
            return

        else:
            print(f"{RED}Unknown command: {cmd}{NC}")
            print(f"Run {CYAN}pry{NC} without arguments for help.")
            sys.exit(1)

    except IndexError:
        print(f"{YELLOW}Missing argument for '{cmd}'{NC}")
        print(f"  {CYAN}pry {cmd} --help{NC} for usage.")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{NC}")
        sys.exit(130)
