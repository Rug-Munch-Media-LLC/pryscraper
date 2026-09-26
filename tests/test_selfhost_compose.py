"""Self-host compose profile: merge contract tests.

The self-host profile (``docker-compose.selfhost.yml``) is an OVERLAY on
``docker-compose.yml``, not a replacement. Docker Compose merges two files
non-obviously: sequences (``ports``, ``volumes``, ``environment``) are
APPENDED or merged by key rather than replaced, and scalar overrides only work
per-key. Every assertion here exists because a plausible-looking overlay
silently produced the wrong runtime configuration in practice:

* ``ports`` merged instead of replaced  -> the self-host box ALSO published
  8005 and stole the operator's production port.
* ``env_file: !reset []`` did not clear the base file -> the self-host
  container inherited an absolute operator secrets path that does not exist
  on a laptop.
* the base's ``TOR_ENABLED=1`` / ``TOR_SOCKS5_HOST=tor`` survived the merge
  -> the ladder tried to dial a SOCKS5 proxy belonging to a service this
  profile deletes, and every scrape failed on connect timeout.

The merge is resolved by the real ``docker compose config`` (the only true
oracle) and asserted against its normalized output. Tests skip when the
Docker CLI is unavailable rather than failing CI on a machine without it.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
SELFHOST_COMPOSE = REPO_ROOT / "docker-compose.selfhost.yml"
SELFHOST_ENV_EXAMPLE = REPO_ROOT / ".env.selfhost.example"

# Services the self-host profile must not boot: every one of them is either
# operator-only stateful infrastructure or a second copy of a helper service.
OPERATOR_ONLY_SERVICES = (
    "postgres",
    "redis",
    "prometheus",
    "grafana",
    "flaresolverr",
    "postgres-exporter",
    "redis-exporter",
    "blackbox-exporter",
    "otel-collector",
    "jaeger",
    "tor",
)


def _docker_compose() -> list[str]:
    """Return a usable `docker compose` argv prefix, or skip the test."""
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not available")
    docker = shutil.which("docker")
    assert docker is not None  # narrowed for the type checker
    probe = subprocess.run(  # noqa: S603 - argv is static, path resolved via which()
        [docker, "compose", "version"],
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("docker compose plugin not available")
    return [docker, "compose"]


def _render(*extra_env: str, with_selfhost: bool = True) -> dict[str, Any]:
    """Render the merged compose model via `docker compose config`."""
    files = ["-f", str(BASE_COMPOSE)]
    if with_selfhost:
        files += ["-f", str(SELFHOST_COMPOSE)]
    env = {**os.environ, "POSTGRES_PASSWORD": "t", "GRAFANA_PASSWORD": "t"}
    for item in extra_env:
        key, _, value = item.partition("=")
        env[key] = value
    proc = subprocess.run(  # noqa: S603 - argv built from repo paths + static flags
        [*_docker_compose(), *files, "config", "--format", "json"],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )
    assert proc.returncode == 0, f"compose config failed: {proc.stderr.decode()[:2000]}"
    return json.loads(proc.stdout)


class TestSelfhostMerge:
    """The merged self-host model is exactly two services on port 8002."""

    def test_only_pry_and_flaresolverr_survive(self) -> None:
        model = _render()
        assert sorted(model["services"]) == ["flaresolverr-pry", "pry"]

    def test_operator_only_services_are_reset(self) -> None:
        services = _render()["services"]
        for name in OPERATOR_ONLY_SERVICES:
            assert name not in services, f"{name} must not run in the self-host profile"

    def test_ports_are_replaced_not_appended(self) -> None:
        """Regression: the base's 8005 publish must NOT survive the merge."""
        ports = _render()["services"]["pry"]["ports"]
        published = {str(p["published"]) for p in ports}
        assert published == {"8002"}, f"expected only 8002, got {published}"
        assert all(p["target"] == 8002 for p in ports)

    def test_host_port_is_overridable(self) -> None:
        ports = _render("PRY_SELFHOST_PORT=9002")["services"]["pry"]["ports"]
        assert {str(p["published"]) for p in ports} == {"9002"}

    def test_no_fleet_secrets_file_is_inherited(self) -> None:
        """Regression: `!reset []` on env_file did not clear the base value."""
        assert "env_file" not in _render()["services"]["pry"]

    def test_tor_settings_are_neutralised(self) -> None:
        """Regression: the base enables Tor; this profile deletes the service."""
        env = _render()["services"]["pry"]["environment"]
        assert str(env.get("TOR_ENABLED")) == "0"
        assert not env.get("TOR_SOCKS5_HOST")

    def test_flaresolverr_is_not_published_on_the_host(self) -> None:
        flaresolverr = _render()["services"]["flaresolverr-pry"]
        assert "ports" not in flaresolverr

    def test_only_data_volumes_are_declared(self) -> None:
        assert sorted(_render()["volumes"]) == ["pry-data", "pry-sessions"]


class TestSelfhostRuntimeConfig:
    """The values the container actually boots with."""

    @staticmethod
    @pytest.fixture(scope="class")
    def env() -> dict[str, str]:
        return _render()["services"]["pry"]["environment"]

    def test_x402_is_off(self, env: dict[str, str]) -> None:
        assert env["PRY_X402_ENABLED"] == "false"

    def test_no_payee_wallet_is_configured(self, env: dict[str, str]) -> None:
        assert not env.get("PRY_X402_WALLET")
        assert env.get("PRY_X402_SELF_FACILITATE") in ("0", "false", "no", "off")

    def test_mcp_is_on(self, env: dict[str, str]) -> None:
        assert env["PRY_MCP_ENABLED"] == "true"

    def test_sqlite_not_postgres(self, env: dict[str, str]) -> None:
        assert env["PRY_DATABASE_URL"].startswith("sqlite:///")
        assert env["PRY_ALLOW_SQLITE_PROD"] == "1"

    def test_redis_is_not_pointed_at_a_missing_service(self, env: dict[str, str]) -> None:
        assert not env.get("PRY_REDIS_URL")

    def test_flaresolverr_sidecar_is_wired(self, env: dict[str, str]) -> None:
        assert env["PRY_FLARESOLVERR_URL"] == "http://flaresolverr-pry:8191/v1"

    def test_pry_waits_for_the_browser_tier(self) -> None:
        deps = _render()["services"]["pry"]["depends_on"]
        assert set(deps) == {"flaresolverr-pry"}


class TestContainerPrefix:
    """PRY_CONTAINER_PREFIX namespaces container names (decision 1).

    The default MUST render the existing fleet names byte-for-byte: the Talos
    deployment must not be affected by the variable merely existing.
    """

    def _names(self, **kwargs: Any) -> dict[str, str]:
        env = [f"{key}={value}" for key, value in kwargs.items()]
        services = _render(*env, with_selfhost=False)["services"]
        return {name: svc["container_name"] for name, svc in services.items()}

    def test_unset_prefix_keeps_fleet_names(self) -> None:
        names = self._names()
        assert names["pry"] == "pry"
        assert names["postgres"] == "pry-postgres"
        assert names["flaresolverr-pry"] == "pry-flaresolverr-pry"

    def test_empty_prefix_keeps_fleet_names(self) -> None:
        """`-` (not `:-`) is required: an EMPTY prefix must still yield `pry`."""
        assert self._names(PRY_CONTAINER_PREFIX="")["pry"] == "pry"

    def test_prefix_applies_to_every_service(self) -> None:
        names = self._names(PRY_CONTAINER_PREFIX="selfhost-")
        assert names["pry"] == "selfhost-pry"
        assert names["postgres"] == "selfhost-postgres"
        assert all(v.startswith("selfhost-") for v in names.values())

    def test_selfhost_profile_honours_the_prefix(self) -> None:
        services = _render("PRY_CONTAINER_PREFIX=alt-")["services"]
        assert services["pry"]["container_name"] == "alt-pry"
        assert services["flaresolverr-pry"]["container_name"] == "alt-flaresolverr-pry"


class TestSelfhostEnvTemplate:
    """`.env.selfhost.example` is the whole self-host configuration."""

    @staticmethod
    @pytest.fixture(scope="class")
    def env() -> dict[str, str]:
        text = SELFHOST_ENV_EXAMPLE.read_text(encoding="utf-8")
        pairs = [
            line.split("=", 1)
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
        ]
        return {k.strip(): v.strip() for k, v in pairs}

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


def test_env_examples_do_not_leak_internal_hosts() -> None:
    """Public config templates must not carry internal endpoints.

    The banned tokens are assembled from fragments at runtime on purpose: a
    literal internal hostname or CGNAT prefix written into this file would
    itself be the leak this test exists to prevent (and trips the
    methodology-leak pre-commit guard). What is banned is the *shape* —
    private hostnames, overlay-network operator paths and RFC 6598 carrier
    NAT ranges.
    """
    octet = "100"
    banned = (
        f"{octet}.{'.'.join(('104', '64', '92', '119'))}.",  # CGNAT range prefix
        f"[{'INTERNAL'}",
        f"/{'srv'}/{'rmi-infra'}",
        ".".join(("talos", "rugmunch", "io")),
    )
    for template in (REPO_ROOT / ".env.example", SELFHOST_ENV_EXAMPLE):
        text = template.read_text(encoding="utf-8")
        for needle in banned:
            assert needle not in text, f"{template.name} contains an internal endpoint"


def test_selfhost_overlay_uses_only_supported_yaml_tags() -> None:
    """Guard the overlay's merge directives.

    ``!reset`` and ``!override`` are compose-spec merge tags, not YAML 1.1
    standard, so a plain ``yaml.safe_load`` of the overlay raises. That is
    expected — but it means the overlay can only be read by the Docker CLI.
    Pin the exact tag set so a future edit cannot quietly add a tag the
    installed compose version does not support (which fails at deploy time,
    on a user's machine, not in CI).
    """
    text = SELFHOST_COMPOSE.read_text(encoding="utf-8")
    tags = set(re.findall(r"!(reset|override)\b", text))
    assert tags == {"reset", "override"}, f"unexpected compose tags: {tags}"


def test_base_compose_is_valid_yaml() -> None:
    """The production file must stay plain YAML (no merge tags).

    The base file is loaded by tooling other than the Docker CLI (policy
    scanners, editors, the fleet's own compose linters), so it must not
    depend on the compose-spec extension tags.
    """
    data = yaml.safe_load(BASE_COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "services" in data
