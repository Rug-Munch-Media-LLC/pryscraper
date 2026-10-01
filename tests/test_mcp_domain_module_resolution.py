# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Namespaced module resolution for the MCP tool dispatchers.

Split from a single 491-line file to stay under the 200-line structure cap.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest

from pry_mcp.tools._common import (
    resolve_domain_module,
    resolve_domain_package,
)


class TestNamespacedResolution:
    def test_datasets_food_data_restaurants_resolves(self) -> None:
        """``datasets.food_data.restaurants`` must resolve; bare must not.

        Kills the mutation that reverts ``resolve_domain_module`` to a bare
        ``{package}.{module}`` import — the dispatcher then never reaches
        ``get_restaurant_menu`` and returns MODULE_UNAVAILABLE instead.
        """
        module = resolve_domain_module("food_data", "restaurants")

        assert module.__name__ == "datasets.food_data.restaurants"
        assert callable(module.get_restaurant_menu)

    def test_bare_domain_package_is_absent(self) -> None:
        """Pins the premise: no top-level ``food_data`` package exists.

        The defect was a bare ``__import__("food_data.restaurants")``. If a
        top-level package of that name ever appears it is a *different* module,
        and the namespacing assertions above would be testing the wrong thing.
        """
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("food_data.restaurants")

    @pytest.mark.parametrize(
        ("package", "module_name"),
        [
            ("food_data", "grocery"),
            ("food_data", "restaurants"),
            ("app_store_data", "apple"),
            ("news_data", "headlines"),
            ("news_data", "sentiment"),
            ("research_data", "academic"),
            ("research_data", "domain"),
            ("energy_data", "lmp"),
            ("freight_data", "rates"),
            ("compliance_data", "enforcement"),
            ("deals_data", "drops"),
            ("events_data", "tickets"),
            ("supply_data", "imports"),
            ("bidding_data", "grants"),
            ("climate_data", "weather"),
            ("climate_data", "agri"),
        ],
    )
    def test_every_domain_module_resolves_under_datasets(
        self, package: str, module_name: str
    ) -> None:
        """All 12 domain packages resolve under ``datasets``.

        Kills the mutation that drops the ``datasets.`` prefix from the
        candidate list, or narrows it to one hardcoded package — any package
        not listed would go back to MODULE_UNAVAILABLE.
        """
        module = resolve_domain_module(package, module_name)

        assert module.__name__ == f"datasets.{package}.{module_name}"

    @pytest.mark.parametrize(
        ("package", "expected_fn"),
        [
            ("gov_data", "search_opportunities"),
            ("gov_data", "search_recalls"),
            ("ip_data", "search_patents"),
            ("ip_data", "search_trademarks"),
        ],
    )
    def test_gov_ip_packages_resolve(self, package: str, expected_fn: str) -> None:
        """gov/ip name a *package*, not a module — same namespace rule.

        Kills the mutation that reverts gov.py to ``__import__(package)``.
        """
        module = resolve_domain_package(package)

        assert module.__name__ == f"datasets.{package}"
        assert callable(getattr(module, expected_fn))
