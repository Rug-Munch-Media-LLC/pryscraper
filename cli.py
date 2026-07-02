#!/usr/bin/env python3
"""Pry CLI — pry open any website.

Usage:
  pry open <url>           Scrape a URL to clean markdown
  pry watch <url>          Monitor a page for changes
  pry crawl <url>          Crawl multiple pages
  pry batch <file>         Batch scrape URLs from a file
  pry parse <url>          Parse a document (PDF, DOCX, image)
  pry screenshot <url>     Take a screenshot
  pry transform <data>     Convert data format
  pry run [pry.yml]        Execute jobs from pry.yml
  pry serve                Start the API server
  pry completions          Install shell autocomplete
  pry proxy ...            Manage proxy providers and signup
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import base64
import json
import os
import sys

try:
    import click
except ImportError:
    click = None  # type: ignore[assignment]

# Color support
NC = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"

API_DEFAULT = os.getenv("PRY_URL", "http://localhost:8005")
VERSION = "3.0.0"


def _api():
    return os.getenv("PRY_URL", API_DEFAULT)


def _req(method: str, path: str, data: dict | None = None, timeout=30):
    import httpx

    url = f"{_api()}{path}"
    try:
        if method == "GET":
            resp = httpx.get(url, timeout=timeout)
        else:
            resp = httpx.post(url, json=data or {}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        print(f"{RED}✖ Cannot connect to Pry at {_api()}{NC}")
        print(f"  Start it: {CYAN}pry serve{NC}")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            print(f"{YELLOW}⚠ Rate limited. Slow down.{NC}")
        else:
            print(f"{RED}✖ API error ({e.response.status_code}): {e.response.text[:200]}{NC}")
        sys.exit(1)


def _spinner(label: str):
    import itertools
    import threading
    import time

    stop = False

    def _spin():
        nonlocal stop
        for c in itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]):
            if stop:
                break
            print(f"  {CYAN}{c}{NC} {label}...  ", end="\r", flush=True)
            time.sleep(0.1)

    t = threading.Thread(target=_spin, daemon=True)
    t.start()

    def _done():
        nonlocal stop
        stop = True

    return _done


def cmd_open(url, output_json=False, schema_path=None, timeout=30):
    """Scrape a URL and print clean markdown or JSON."""
    payload = {"url": url, "timeout": timeout}
    if schema_path:
        with open(schema_path) as f:
            payload["jsonSchema"] = json.load(f)
    _spinner(f"Prying open {url[:50]}")
    data = _req("POST", "/v1/scrape", payload, timeout + 10)
    print(f"{GREEN}✓{NC} Pry opened {url}\n", end="")
    if output_json or schema_path:
        print(json.dumps(data, indent=2))
    else:
        md = data.get("data", {}).get("markdown", "")
        print(md[:100000] if md else f"{YELLOW}(no content extracted){NC}")


def cmd_watch(url, webhook="", interval=3600):
    """Register a page for change monitoring."""
    _spinner(f"Registering {url[:50]} for monitoring")
    data = _req("POST", "/v1/watch", {"url": url, "webhook": webhook, "interval": interval}, 45)
    if data.get("success"):
        status = data.get("data", {}).get("status", "registered")
        print(f"{GREEN}✓{NC} Watching {url} (status: {status})")
        if webhook:
            print(f"  Webhook: {webhook}")
    else:
        print(f"{RED}✖ {data.get('error', 'Watch failed')}{NC}")


def cmd_crawl(url, max_pages=10, output=None, timeout=120):
    """Crawl multiple pages from a starting URL."""
    _spinner(f"Crawling {url[:50]} (up to {max_pages} pages)")
    data = _req("POST", "/v1/crawl", {"url": url, "maxPages": max_pages}, timeout)
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
    _spinner(f"Processing {filepath}")
    data = _req(
        "POST",
        "/v1/batch-file",
        {"filepath": filepath, "template": template, "timeout": timeout},
        timeout * 5,
    )
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
    _spinner(f"Parsing {url[:50]}")
    data = _req("POST", "/v1/parse", {"url": url, "timeout": timeout}, timeout + 10)
    text = data.get("data", {}).get("text", "")
    fmt = data.get("data", {}).get("format", "unknown")
    pages = data.get("data", {}).get("pages", 0)
    print(f"{GREEN}✓{NC} Parsed {fmt} ({pages} pages, {len(text)} chars)")
    print(text[:50000])


def cmd_screenshot(url, output=None, timeout=30):
    """Take a screenshot."""
    _spinner(f"Capturing {url[:50]}")
    data = _req("POST", "/v1/screenshot", {"url": url}, timeout + 10)
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


def cmd_run(pryfile_path="pry.yml"):
    """Execute jobs defined in pry.yml."""
    if not os.path.exists(pryfile_path):
        print(f"{RED}✖ No {pryfile_path} found{NC}")
        print(f"  Create one: {CYAN}pry open https://example.com{NC}")
        sys.exit(1)
    _spinner(f"Running jobs from {pryfile_path}")
    data = _req("POST", "/v1/run", {"path": pryfile_path}, 120)
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


def cmd_serve(host="0.0.0.0", port=8005):
    """Start the Pry API server."""
    print(f"{CYAN}🔧 Starting Pry v{VERSION} on {host}:{port}{NC}")
    print(f"  Dashboard: http://localhost:{port}/dashboard")
    print(f"  Health:    http://localhost:{port}/health")
    os.execvp("uvicorn", ["uvicorn", "api:app", "--host", host, "--port", str(port)])


def cmd_completions(shell="bash"):
    """Install shell autocomplete."""
    script = {
        "bash": 'eval "$(_PRY_COMPLETE=bash_source pry)"',
        "zsh": 'eval "$(_PRY_COMPLETE=zsh_source pry)"',
        "fish": 'eval "$(_PRY_COMPLETE=fish_source pry)"',
    }.get(shell, "")
    if shell == "bash":
        rc = os.path.expanduser("~/.bashrc")
    elif shell == "zsh":
        rc = os.path.expanduser("~/.zshrc")
    elif shell == "fish":
        rc = os.path.expanduser("~/.config/fish/config.fish")
    else:
        print(f"{YELLOW}Unknown shell: {shell}. Supported: bash, zsh, fish{NC}")
        return
    dirname = os.path.dirname(rc)
    os.makedirs(dirname, exist_ok=True)
    with open(rc, "a") as f:
        f.write(f"\n# Pry autocomplete\n{script}\n")
    print(f"{GREEN}✓{NC} Autocomplete installed for {shell}")
    print(f"  Restart your shell or run: source {rc}")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "proxy" and click is not None:
        cli.main(standalone_mode=False)
        return
    if len(sys.argv) < 2:
        print(f"{BOLD}Pry v{VERSION}{NC} — Pry open any website. {CYAN}pry.dev{NC}")
        print()
        print(f"  {BOLD}Usage:{NC}")
        print(f"    {CYAN}pry open <url>{NC}              Scrape a URL")
        print(f"    {CYAN}pry watch <url>{NC}             Monitor for changes")
        print(f"    {CYAN}pry crawl <url>{NC}             Crawl a site")
        print(f"    {CYAN}pry batch <file>{NC}            Batch scrape from a file")
        print(f"    {CYAN}pry parse <url>{NC}             Parse a document")
        print(f"    {CYAN}pry ss <url>{NC}                Take a screenshot")
        print(f"    {CYAN}pry run [pry.yml]{NC}           Execute job file")
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

        elif cmd in ("completions", "autocomplete"):
            shell = args[0] if args else "bash"
            cmd_completions(shell)

        elif cmd in ("-v", "--version", "version"):
            print(f"Pry v{VERSION}")

        elif cmd in ("-h", "--help", "help"):
            main()

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


# ── Click-based subcommand: pry proxy ... ──
if click is not None:
    from proxy_manager import ProxyManager

    @click.group()
    def cli() -> None:
        """Pry CLI (click entrypoint for subcommands)."""

    @cli.group()
    def mcp() -> None:
        """Model Context Protocol (MCP) server for AI agent integration."""

    @mcp.command(name="serve")
    def mcp_serve() -> None:
        """Start the MCP server (stdio transport)."""
        import sys

        sys.path.insert(0, ".")
        import asyncio

        from mcp_production import main

        asyncio.run(main())

    @mcp.command(name="info")
    def mcp_info() -> None:
        """Show MCP server info and configuration."""
        click.echo("Pry MCP Server v3.0.0")
        click.echo("")
        click.echo("Add to Claude Desktop config:")
        click.echo("""{
  "mcpServers": {
    "pry": {
      "command": "python",
      "args": ["-m", "mcp_production"]
    }
  }
}""")
        click.echo("")
        click.echo("Or run directly: pry mcp serve")
        click.echo("Or: python -m mcp_production")

    @cli.group()
    def proxy() -> None:
        """Proxy provider configuration and signup."""

    @proxy.command(name="list")
    def proxy_list() -> None:
        """List all available proxy providers (free + premium)."""
        pm = ProxyManager()
        providers = pm.list_providers()
        click.echo("FREE PROVIDERS:")
        for p in providers["free"]:
            click.echo(f"  {p['name']:20s} {p['type']:10s} {p['cost']}")
        click.echo("\nPREMIUM PROVIDERS:")
        for p in providers["premium"]:
            click.echo(f"  {p['name']:20s} {p['commission']:30s}")
            click.echo(f"    Sign up: {p['signup_url']}")

    @proxy.command(name="signup")
    @click.argument("provider")
    def proxy_signup(provider: str) -> None:
        """Open signup page for a premium provider (referral link)."""
        pm = ProxyManager()
        url = pm.get_signup_link(provider)
        click.echo(f"Opening: {url}")
        click.echo(f"(If browser doesn't open, visit: {url})")
        import webbrowser

        webbrowser.open(url)

    @proxy.command(name="configure")
    @click.argument("provider")
    @click.option("--username", default=None)
    @click.option("--password", default=None)
    @click.option("--api-key", default=None)
    @click.option("--proxy-url", default=None)
    def proxy_configure(
        provider: str,
        username: str | None,
        password: str | None,
        api_key: str | None,
        proxy_url: str | None,
    ) -> None:
        """Configure credentials for a premium provider."""
        pm = ProxyManager()
        creds: dict[str, str] = {}
        if username:
            creds["username"] = username
        if password:
            creds["password"] = password
        if api_key:
            creds["api_key"] = api_key
        if proxy_url:
            creds["proxy_url"] = proxy_url
        if not creds:
            click.echo(
                "Need at least one credential (--username, --password, --api-key, or --proxy-url)"
            )
            return
        result = pm.select_provider(provider, creds)
        if result["success"]:
            click.echo(f"Configured {provider}")
        else:
            click.echo(f"Error: {result.get('error', 'unknown')}")

    @proxy.command(name="test")
    @click.option("--url", default="https://httpbin.org/ip", help="URL to test against")
    def proxy_test(url: str) -> None:
        """Test the active proxy connection."""
        pm = ProxyManager()
        proxy_url = pm.get_proxy_url()
        if not proxy_url:
            click.echo("No active proxy configured. Using direct connection.")
        result = pm.test_proxy(proxy_url, url) if proxy_url else {"working": True, "latency": 0}
        click.echo(f"Working: {result['working']}")
        click.echo(f"Latency: {result.get('latency', 'N/A')}s")
        if result.get("ip"):
            click.echo(f"IP: {result['ip'][:60]}")

    @proxy.command(name="status")
    def proxy_status() -> None:
        """Show current proxy configuration."""
        pm = ProxyManager()
        c = pm.active_config
        click.echo(f"Active provider: {c.provider}")
        click.echo(f"Type: {c.proxy_type}")
        click.echo(f"Geo: {c.geo}")
        click.echo(f"Auto-rotate: {c.auto_rotate}")
        creds = list(pm.credentials.keys())
        if creds:
            click.echo(f"Configured: {', '.join(creds)}")

    @proxy.command(name="recommend")
    @click.option("--error", "last_error", default="", help="Last error message")
    def proxy_recommend(last_error: str) -> None:
        """Get proxy recommendation after a scrape block."""
        pm = ProxyManager()
        rec = pm.get_recommendation(last_error)
        click.echo(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()
