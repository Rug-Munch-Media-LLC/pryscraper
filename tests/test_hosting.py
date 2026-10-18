# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Cloud-hosting test suite — split by subject (was one 487-line module).

The tests live in, and run from:

* ``tests/test_hosting_plans.py``        — plan catalog + signup preconditions
* ``tests/test_hosting_provisioning.py`` — payment confirmation, provisioning, lifecycle
* ``tests/test_hosting_routes.py``       — route-level manifest / confirm / instances

Shared fixtures and doubles are in ``tests/hosting_support.py`` (``db``,
``client``, ``_clean_hosting_state`` autouse, ``_provision``, ``_FakeFacilitator``).

This module is intentionally empty: pytest collects nothing here, so running
``pytest tests/test_hosting.py`` stays a valid no-op instead of double-running
the suite under a second module path.
"""
