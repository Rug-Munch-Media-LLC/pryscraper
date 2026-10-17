"""Self-host compose profile: the values the container boots with.

Concern: the ``pry`` service's resolved environment, the sidecar wiring and
the published ``.env.selfhost.example`` template. The merged model shape
(services, ports, volumes, container names) lives in ``test_compose_merge``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import pytest

from tests.selfhost.conftest import SELFHOST_ENV_EXAMPLE, read_env_template, render_compose


class TestSelfhostRuntimeConfig:
    """The values the container actually boots with."""

    @staticmethod
    @pytest.fixture(scope="class")
    def env() -> dict[str, str]:
        return render_compose()["services"]["pry"]["environment"]

    def test_x402_is_off(self, env: dict[str, str]) -> None:
        assert env["PRY_X402_ENABLED"] == "false"

    def test_no_payee_wallet_is_configured(self, env: dict[str, str]) -> None:
        assert not env.get("PRY_X402_WALLET")
        assert env.get("PRY_X402_SELF_FACILITATE") in ("0", "false", "no", "off")

    def test_mcp_is_on(self, env: dict[str, str]) -> None:
        assert env["PRY_MCP_ENABLED"] == "true"

    def test_tor_settings_are_neutralised(self, env: dict[str, str]) -> None:
        """Regression: the base enables Tor; this profile deletes the service."""
        assert str(env.get("TOR_ENABLED")) == "0"
        assert not env.get("TOR_SOCKS5_HOST")

    def test_sqlite_not_postgres(self, env: dict[str, str]) -> None:
        assert env["PRY_DATABASE_URL"].startswith("sqlite:///")
        assert env["PRY_ALLOW_SQLITE_PROD"] == "1"

    def test_redis_is_not_pointed_at_a_missing_service(self, env: dict[str, str]) -> None:
        assert not env.get("PRY_REDIS_URL")

    def test_flaresolverr_sidecar_is_wired(self, env: dict[str, str]) -> None:
        assert env["PRY_FLARESOLVERR_URL"] == "http://flaresolverr-pry:8191/v1"

    def test_pry_waits_for_the_browser_tier(self) -> None:
        deps = render_compose()["services"]["pry"]["depends_on"]
        expected = {"flaresolverr-pry"}
        assert set(deps) == expected


class TestSelfhostEnvTemplate:
    """`.env.selfhost.example` is the whole self-host configuration."""

    @staticmethod
    @pytest.fixture(scope="class")
    def env() -> dict[str, str]:
        return read_env_template(SELFHOST_ENV_EXAMPLE)

    def test_declares_an_api_key_placeholder(self, env: dict[str, str]) -> None:
        """The template must not ship a real key; the init script writes one."""
        assert "PRY_API_KEY" in env
        assert "replace-me" in env["PRY_API_KEY"]

    def test_publishes_the_selfhost_port_of_record(self, env: dict[str, str]) -> None:
        assert env["PRY_SELFHOST_PORT"] == "8002"
        assert env["PRY_URL"].endswith(":8002")

    def test_documents_the_free_path(self, env: dict[str, str]) -> None:
        assert env["PRY_X402_ENABLED"] == "false"
        assert env["PRY_MCP_ENABLED"] == "true"

    def test_allows_sqlite_in_prod(self, env: dict[str, str]) -> None:
        assert env["PRY_ALLOW_SQLITE_PROD"] == "1"
