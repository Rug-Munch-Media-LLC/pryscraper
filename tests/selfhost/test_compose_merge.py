"""Self-host compose profile: what the merged model actually contains.

Concern: the SHAPE of the merged compose model — which services survive,
which ports are published, which volumes exist, and how the container-prefix
variable namespaces container names. Runtime env values and template
contents live in the sibling modules.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from tests.selfhost.conftest import (
    OPERATOR_ONLY_SERVICES,
    render_compose,
)


class TestSelfhostMerge:
    """The merged self-host model is exactly two services on port 8002."""

    def test_only_the_selfhost_services_survive(self) -> None:
        model = render_compose()
        # The remote MCP rides with the API in the self-host profile.
        expected = ["flaresolverr-pry", "pry", "pry-mcp"]
        assert sorted(model["services"]) == expected

    def test_operator_only_services_are_reset(self) -> None:
        services = render_compose()["services"]
        for name in OPERATOR_ONLY_SERVICES:
            assert name not in services, f"{name} must not run in the self-host profile"

    def test_ports_are_replaced_not_appended(self) -> None:
        """Regression: the base's 8005 publish must NOT survive the merge."""
        ports = render_compose()["services"]["pry"]["ports"]
        published = {str(p["published"]) for p in ports}
        expected = {"8002"}
        assert published == expected, f"expected only 8002, got {published}"
        assert all(p["target"] == 8002 for p in ports)

    def test_host_port_is_overridable(self) -> None:
        ports = render_compose("PRY_SELFHOST_PORT=9002")["services"]["pry"]["ports"]
        expected = {"9002"}
        assert {str(p["published"]) for p in ports} == expected

    def test_no_fleet_secrets_file_is_inherited(self) -> None:
        """Regression: `!reset []` on env_file did not clear the base value."""
        assert "env_file" not in render_compose()["services"]["pry"]

    def test_flaresolverr_is_not_published_on_the_host(self) -> None:
        flaresolverr = render_compose()["services"]["flaresolverr-pry"]
        assert "ports" not in flaresolverr

    def test_only_data_volumes_are_declared(self) -> None:
        expected = ["pry-data", "pry-sessions"]
        assert sorted(render_compose()["volumes"]) == expected


class TestContainerPrefix:
    """PRY_CONTAINER_PREFIX namespaces container names (decision 1).

    The default MUST render the existing fleet names byte-for-byte: the Talos
    deployment must not be affected by the variable merely existing.
    """

    def _names(self, **kwargs: Any) -> dict[str, str]:
        env = [f"{key}={value}" for key, value in kwargs.items()]
        services = render_compose(*env, with_selfhost=False)["services"]
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
        services = render_compose("PRY_CONTAINER_PREFIX=alt-")["services"]
        assert services["pry"]["container_name"] == "alt-pry"
        assert services["flaresolverr-pry"]["container_name"] == "alt-flaresolverr-pry"
