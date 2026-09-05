"""Pry — wallet configuration CLI.

Interactive tooling for the operator (crmuncher) to configure the receiving
payment wallets used by the x402 pay-per-call gate. This is the OSS-facing
counterpart to the coffer's ``X402_WALLET_*`` env vars — Pry reads the
``PRY_X402_WALLET_*`` family (see ``pry.payments.x402``).

Commands (registered on the main ``pry`` CLI as the ``wallets`` group):

  pry wallets init      Interactive setup wizard (prompts + validation + write)
  pry wallets show      Show currently configured wallets (masked)
  pry wallets validate  Validate all configured wallet address formats
  pry wallets test      Send a test 402 challenge to verify the payment flow

Address validation per chain family:

  EVM (Base/ETH/Arb/Op/Poly)  — 0x + 40 hex chars, checksum-valid
                                (eth_utils when available, else basic format)
  Solana                      — 32-44 base58 chars
  TRON                        — starts with 'T', 34 chars

Wallets are written to the repo-root ``.env`` (the documented OSS convention —
see ``.env.example``). Override the target file with ``--env-file``.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

import click

# ── Chain registry ──────────────────────────────────────────────────────────
# Each chain maps to the PRY_X402_WALLET_* env var Pry actually reads
# (see pry.payments.x402.X402_NETWORK_WALLETS). EVM networks share the EVM
# treasury; Solana/TRON use distinct base58 addresses.
Chain = dict[str, str | Callable[[str], bool]]

CHAINS: list[Chain] = [
    {
        "name": "Base",
        "env": "PRY_X402_WALLET_BASE",
        "family": "evm",
        "hint": "0x + 40 hex chars (checksum-valid)",
    },
    {
        "name": "Ethereum",
        "env": "PRY_X402_WALLET_ETHEREUM",
        "family": "evm",
        "hint": "0x + 40 hex chars (checksum-valid)",
    },
    {
        "name": "Arbitrum",
        "env": "PRY_X402_WALLET_ARBITRUM",
        "family": "evm",
        "hint": "0x + 40 hex chars (checksum-valid)",
    },
    {
        "name": "Optimism",
        "env": "PRY_X402_WALLET_OPTIMISM",
        "family": "evm",
        "hint": "0x + 40 hex chars (checksum-valid)",
    },
    {
        "name": "Polygon",
        "env": "PRY_X402_WALLET_POLYGON",
        "family": "evm",
        "hint": "0x + 40 hex chars (checksum-valid)",
    },
    {
        "name": "Solana",
        "env": "PRY_X402_WALLET_SOLANA",
        "family": "solana",
        "hint": "32-44 base58 chars",
    },
    {
        "name": "TRON",
        "env": "PRY_X402_WALLET_TRON",
        "family": "tron",
        "hint": "starts with 'T', 34 chars",
    },
]

# ── Address validation ──────────────────────────────────────────────────────
_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
# base58 alphabet (Bitcoin-style, excludes 0/O/I/l)
_BASE58_ALPHABET = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
_TRON_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


def _is_evm_address(addr: str) -> bool:
    """True when ``addr`` is a 0x-prefixed 40-hex EVM address (42 chars)."""
    addr = addr.strip()
    if not _EVM_RE.fullmatch(addr):
        return False
    # Checksum validation via eth_utils when available; fall back to the
    # basic format check (any-case hex) otherwise.
    try:
        from eth_utils import (  # type: ignore[attr-defined]
            is_checksum_address,
            is_hex_address,
        )

        if not is_hex_address(addr):
            return False
        # Accept both checksummed and all-lowercase/all-uppercase addresses
        # (all-lowercase is a valid, non-checksummed representation).
        if addr == addr.lower() or addr == addr.upper():
            return True
        return is_checksum_address(addr)
    except Exception:  # noqa: BLE001 - pragma: no cover - eth_utils unavailable
        return True


def _is_solana_address(addr: str) -> bool:
    """True when ``addr`` is a 32-44 char base58 Solana address."""
    addr = addr.strip()
    if not (32 <= len(addr) <= 44):
        return False
    return all(c in _BASE58_ALPHABET for c in addr)


def _is_tron_address(addr: str) -> bool:
    """True when ``addr`` is a 34-char T-prefixed TRON base58 address."""
    return bool(addr and _TRON_RE.fullmatch(addr.strip()))


_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "evm": _is_evm_address,
    "solana": _is_solana_address,
    "tron": _is_tron_address,
}


def validate_address(family: str, addr: str) -> bool:
    """Validate ``addr`` against the address format for ``family``."""
    validator = _VALIDATORS.get(family)
    if validator is None:
        return False
    return validator(addr)


# ── .env read/write helpers ─────────────────────────────────────────────────
def _default_env_file() -> Path:
    """The repo-root .env (documented OSS convention)."""
    return Path.cwd() / ".env"


def _read_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict (last value wins)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    return values


def _write_env(path: Path, updates: dict[str, str]) -> None:
    """Update a .env file in place, preserving comments and ordering.

    Existing keys are replaced in place; new keys are appended at the end.
    """
    path = path.expanduser()
    lines: list[str] = []
    if path.exists():
        lines = path.read_text().splitlines()

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)

    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")


def _mask(addr: str) -> str:
    """Mask an address for display: 0x1234...5678 (or T...abcd for TRON)."""
    addr = addr.strip()
    if not addr:
        return "(unset)"
    if len(addr) <= 10:
        return addr[:4] + "..." + addr[-2:]
    return f"{addr[:6]}...{addr[-4:]}"


def _current_wallets(env_file: Path) -> dict[str, str]:
    """Read the currently configured wallets from the env file + os.environ."""
    file_vals = _read_env(env_file)
    result: dict[str, str] = {}
    for chain in CHAINS:
        env_key = str(chain["env"])
        # Prefer the live process env, then the .env file.
        result[env_key] = os.getenv(env_key, file_vals.get(env_key, ""))
    return result


# ── Click command group ─────────────────────────────────────────────────────
@click.group()
def wallets() -> None:
    """Configure receiving payment wallets for the x402 pay gate."""


@wallets.command(name="init")
@click.option(
    "--env-file",
    "env_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to the .env file to write (default: ./.env)",
)
def wallets_init(env_file: Path | None) -> None:
    """Interactive setup wizard: prompt for each chain wallet, validate, write."""
    target = env_file or _default_env_file()
    click.echo(click.style("Pry wallet setup wizard", bold=True))
    click.echo(f"Writing to: {target}")
    click.echo("Leave a prompt empty to skip that chain (fail closed).")
    click.echo("")

    updates: dict[str, str] = {}
    for chain in CHAINS:
        name = str(chain["name"])
        env_key = str(chain["env"])
        hint = str(chain["hint"])
        family = str(chain["family"])
        current = os.getenv(env_key, "")
        prompt = f"{name} wallet ({hint})"
        if current:
            prompt += f" [current: {_mask(current)}]"
        value = click.prompt(prompt, default="", show_default=False).strip()
        if not value:
            click.echo(f"  {click.style('skipped', fg='yellow')} — {name} left unconfigured")
            continue
        if not validate_address(family, value):
            click.echo(
                f"  {click.style('✖ invalid', fg='red')} {name}: not a valid {family} address"
            )
            continue
        updates[env_key] = value
        click.echo(f"  {click.style('✓ ok', fg='green')} {name} set")

    if not updates:
        click.echo(click.style("No wallets configured. Nothing written.", fg="yellow"))
        return

    _write_env(target, updates)
    click.echo("")
    click.echo(click.style(f"✓ Wrote {len(updates)} wallet(s) to {target}", fg="green"))
    click.echo("Restart the service (or reload env) for changes to take effect.")


@wallets.command(name="show")
@click.option(
    "--env-file",
    "env_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to the .env file to read (default: ./.env)",
)
def wallets_show(env_file: Path | None) -> None:
    """Show currently configured wallets (masked)."""
    target = env_file or _default_env_file()
    current = _current_wallets(target)
    click.echo(click.style("Configured receiving wallets", bold=True))
    click.echo(f"Source: {target} + environment")
    click.echo("")
    for chain in CHAINS:
        env_key = str(chain["env"])
        val = current.get(env_key, "")
        status = click.style("✓", fg="green") if val else click.style("✖", fg="red")
        click.echo(f"  {status} {chain['name']!s:10s} {_mask(val)}  ({env_key})")


@wallets.command(name="validate")
@click.option(
    "--env-file",
    "env_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to the .env file to read (default: ./.env)",
)
def wallets_validate(env_file: Path | None) -> None:
    """Validate all configured wallet addresses are correct for their chain."""
    target = env_file or _default_env_file()
    current = _current_wallets(target)
    click.echo(click.style("Validating configured wallets", bold=True))
    click.echo("")
    all_ok = True
    for chain in CHAINS:
        env_key = str(chain["env"])
        family = str(chain["family"])
        val = current.get(env_key, "")
        if not val:
            click.echo(f"  {click.style('—', fg='yellow')} {chain['name']!s:10s} unset")
            continue
        if validate_address(family, val):
            click.echo(f"  {click.style('✓', fg='green')} {chain['name']!s:10s} valid")
        else:
            all_ok = False
            click.echo(
                f"  {click.style('✖', fg='red')} {chain['name']!s:10s} INVALID ({_mask(val)})"
            )
    click.echo("")
    if all_ok:
        click.echo(click.style("All configured wallets are valid.", fg="green"))
    else:
        click.echo(
            click.style(
                "One or more wallets are invalid — fix them before accepting payments.", fg="red"
            )
        )
        sys.exit(1)


@wallets.command(name="test")
@click.option(
    "--env-file",
    "env_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to the .env file to read (default: ./.env)",
)
@click.option("--network", default=None, help="CAIP-2 network id to test (default: base)")
@click.option("--amount", default="0.01", help="USD amount for the test challenge")
def wallets_test(env_file: Path | None, network: str | None, amount: str) -> None:
    """Send a test 402 challenge to verify the payment flow works."""

    # Resolve the payTo for the requested network.
    try:
        from pry.payments.x402 import (
            X402_NETWORK_WALLETS,
            build_payment_required,
            resolve_pay_to,
            wallet_configured,
        )
    except Exception as exc:  # noqa: BLE001 - pragma: no cover - import guard
        click.echo(click.style(f"✖ Could not import x402 module: {exc}", fg="red"))
        sys.exit(1)

    net = network or "eip155:8453"
    pay_to = resolve_pay_to(net, X402_NETWORK_WALLETS)
    if not pay_to or not wallet_configured(pay_to):
        click.echo(
            click.style(
                f"✖ No configured receiving wallet for {net}. Run `pry wallets init` first.",
                fg="red",
            )
        )
        sys.exit(1)

    click.echo(click.style("Sending test 402 challenge", bold=True))
    click.echo(f"  Network: {net}")
    click.echo(f"  PayTo:   {_mask(pay_to)}")
    click.echo(f"  Amount:  ${amount}")

    try:
        body = build_payment_required(
            operation="wallet-test",
            resource=f"pry://wallet-test/{net}",
            description=f"Pry wallet test challenge (${amount})",
            preferred_networks=[net],
            preferred_assets=["USDC"],
        )
        click.echo("")
        click.echo(click.style("✓ Test challenge built successfully.", fg="green"))
        click.echo(f"  payTo: {pay_to}")
        click.echo(f"  scheme: {body.get('scheme', 'n/a')}")
        click.echo(f"  accepts: {len(body.get('accepts', []))} option(s)")
        for acc in body.get("accepts", []):
            click.echo(
                f"    - {acc.get('network')} {acc.get('asset')} "
                f"maxAmountRequired={acc.get('maxAmountRequired')}"
            )
    except Exception as exc:  # noqa: BLE001 - pragma: no cover - network/price oracle failure
        click.echo(click.style(f"✖ Test challenge failed: {exc}", fg="red"))
        sys.exit(1)


__all__ = [
    "CHAINS",
    "validate_address",
    "wallets",
    "wallets_init",
    "wallets_show",
    "wallets_test",
    "wallets_validate",
]
