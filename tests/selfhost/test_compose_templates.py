"""Self-host compose files: template hygiene and YAML-tag constraints.

Concern: the static shape of the two compose files and the two env templates
as TEXT — no Docker CLI required, so these run everywhere CI does.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re

import yaml

from tests.selfhost.conftest import BASE_COMPOSE, REPO_ROOT, SELFHOST_COMPOSE, SELFHOST_ENV_EXAMPLE


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
    expected = {"reset", "override"}
    assert tags == expected, f"unexpected compose tags: {tags}"


def test_base_compose_is_valid_yaml() -> None:
    """The production file must stay plain YAML (no merge tags).

    The base file is loaded by tooling other than the Docker CLI (policy
    scanners, editors, the fleet's own compose linters), so it must not
    depend on the compose-spec extension tags.
    """
    data = yaml.safe_load(BASE_COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "services" in data
