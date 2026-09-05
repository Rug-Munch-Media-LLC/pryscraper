# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

"""Click-based subcommands: `pry proxy ...`, `pry mcp ...`, `pry wallets ...`."""

from __future__ import annotations

import json

import click

if click is not None:
    from pry.engine.proxy_manager import ProxyManager

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

        from pry_mcp import main

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
    def wallets() -> None:
        """Configure receiving payment wallets for the x402 pay gate."""

    # Register the wallet subcommands (init/show/validate/test) from the
    # wallet_setup module so the CLI stays thin and the logic is testable.
    from pry.payments.wallet_setup import wallets as _wallets_group

    for _cmd in _wallets_group.commands.values():
        wallets.add_command(_cmd)

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
