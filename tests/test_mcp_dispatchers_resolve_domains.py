# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Dispatcher source must reach domain modules through the shared resolver.

``tests/test_mcp_domain_module_resolution.py`` proves the *resolver* works. It
cannot prove any *dispatcher* calls it — a bare ``from travel.flights import``
sits in the same repo, resolves nothing, and every tool behind it answers
``MODULE_UNAVAILABLE`` forever. This module closes that gap by reading the
dispatcher sources themselves, so a reintroduced bare import fails here rather
than in production.

Genuinely top-level packages are exempted: ``actor_factory``, ``extraction``
and ``crypto_market`` are real top-level packages, and their imports are
correct. Only a package that shadows a ``datasets.`` subpackage is the defect.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from pry_mcp.tools._common import DATASETS_PACKAGE

TOOLS_DIR = Path(__file__).resolve().parents[1] / "pry_mcp" / "tools"

# A bare domain import inside a dispatcher: `from travel.flights import x`.
BARE_DOMAIN_IMPORT = re.compile(r"^\s*from\s+(?P<package>[A-Za-z_][\w]*)\.[\w.]+\s+import\b")

# Names that are NOT `datasets.*` domains — importing them bare is correct, so
# the scanner must not flag them. `pry.*` resolves through the src-layout
# namespace package; the rest are real top-level directories.
NON_DOMAIN_PACKAGES = frozenset(
    {"actor_factory", "crypto_market", "extraction", "pry", DATASETS_PACKAGE}
)


def _dataset_subpackages() -> frozenset[str]:
    """Names of the real ``datasets/`` subpackages, read from the filesystem."""
    root = TOOLS_DIR.parents[1] / DATASETS_PACKAGE
    return frozenset(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("_"))


def _bare_domain_imports_from_lines(lines: list[str]) -> list[tuple[int, str]]:
    """``(lineno, statement)`` for bare *domain* imports in ``lines``.

    A line is a domain import when its root package is not in
    ``NON_DOMAIN_PACKAGES`` — i.e. it names something the ``datasets/`` tree
    owns. The namespace package ``pry`` and the ``datasets`` prefix itself are
    excluded because those imports are already correctly namespaced.
    """
    return [
        (lineno, line.strip())
        for lineno, line in enumerate(lines, start=1)
        if (m := BARE_DOMAIN_IMPORT.match(line)) and m.group("package") not in NON_DOMAIN_PACKAGES
    ]


def _bare_domain_imports(path: Path) -> list[tuple[int, str]]:
    """``(lineno, statement)`` for every bare domain import in ``path``."""
    return _bare_domain_imports_from_lines(path.read_text().splitlines())


def _dispatcher_files() -> list[Path]:
    return sorted(p for p in TOOLS_DIR.glob("*.py") if p.name != "_common.py")


class TestDispatchersUseTheResolver:
    def test_scanner_actually_matches_a_bare_import(self) -> None:
        """The scanner is proven live on a synthetic string before it is trusted.

        A regex that never matches would make every assertion below vacuously
        green. This kills the mutation that breaks ``BARE_DOMAIN_IMPORT`` (a
        mangled character class, a dropped ``\\s+``) so the guard cannot
        silently stop detecting anything.
        """
        line = "            from travel.flights import cheapest_date_grid"

        expected = [(1, "from travel.flights import cheapest_date_grid")]
        assert _bare_domain_imports_from_lines([line]) == expected

    def test_scanner_ignores_genuine_top_level_packages(self) -> None:
        """``actor_factory``/``crypto_market``/``pry.*`` are really top-level.

        Kills the mutation that drops ``NON_DOMAIN_PACKAGES`` from the filter:
        every ``from crypto_market...`` and ``from pry.commerce...`` import in
        the marketplace/crypto dispatchers would be reported and the guard
        would demand a wrong ``datasets.`` prefix for a correct import.
        """
        for line in (
            "        from crypto_market.cex_listings import get_listing_signals",
            "        from actor_factory.presets import ALL_PRESETS",
            "        from pry.engine.mega_search import mega_search",
        ):
            assert _bare_domain_imports_from_lines([line]) == []

    def test_scanner_ignores_the_resolver_itself(self) -> None:
        """``from datasets.x import y`` is already namespaced — not a defect.

        Kills the mutation that flags any dotted ``from`` line, which would
        reject the correct fix and make the guard unsatisfiable.
        """
        line = "        from datasets.sports_data import derivatives"

        assert _bare_domain_imports_from_lines([line]) == []


@pytest.mark.parametrize("path", _dispatcher_files(), ids=lambda p: p.name)
def test_dispatcher_has_no_bare_domain_import(path: Path) -> None:
    """No dispatcher may import a ``datasets`` subpackage by its bare name.

    Kills the exact production bug this guards: a dispatcher reaching
    ``travel.flights`` / ``local_data.places`` / ``real_estate.listings`` /
    ``attention.serp`` directly. Such an import raises ``ModuleNotFoundError``
    at call time, the handler's ``except ImportError`` swallows it, and the
    tool answers MODULE_UNAVAILABLE even though the handler exists and matches.
    """
    assert _bare_domain_imports(path) == [], (
        f"{path.name} imports a domain module by its bare name; "
        f"use resolve_domain_module(package, module) from ._common"
    )


def test_scanner_agrees_with_the_real_datasets_subpackages() -> None:
    """The filesystem and the scanner must describe the same set of packages.

    Kills the mutation that hardcodes a package list into the scanner: a new
    ``datasets/`` subpackage would ship unguarded. Reading the directory keeps
    the guard honest as domains are added.
    """
    subpackages = _dataset_subpackages()

    assert {
        "travel",
        "local_data",
        "real_estate",
        "attention",
        "jobs",
        "legal_docs",
    } <= subpackages
    # ``datasets/`` may hold a subpackage whose name also exists as a real
    # top-level package (e.g. ``crypto_market/`` at the repo root); only names
    # that are dataset-only can be *non-domain*.
    top_level = {
        p.name
        for p in (TOOLS_DIR.parents[1]).iterdir()
        if p.is_dir() and not p.name.startswith((".", "_"))
    }
    assert not (subpackages & (NON_DOMAIN_PACKAGES - top_level - {DATASETS_PACKAGE}))


def test_every_flagged_package_is_a_real_dataset_subpackage() -> None:
    """Any bare import the scanner would flag must correspond to a real domain.

    Keeps the guard honest in the other direction: if a dispatcher started
    importing some unrelated top-level package, the fix is to add it to
    ``NON_DOMAIN_PACKAGES``, not to leave a permanently failing assertion.
    """
    subpackages = _dataset_subpackages()
    flagged: set[str] = set()
    for path in _dispatcher_files():
        for match in BARE_DOMAIN_IMPORT.finditer(path.read_text()):
            package = match.group("package")
            if package not in NON_DOMAIN_PACKAGES:
                flagged.add(package)

    assert flagged <= subpackages, f"undeclared top-level packages: {flagged - subpackages}"


def test_dispatcher_modules_are_syntactically_valid() -> None:
    """Every dispatcher must parse — an unparseable file hides a bare import.

    Kills the mutation that makes the scanner skip a dispatcher by leaving it
    syntactically broken, since the scanner reads text, not the AST.
    """
    for path in _dispatcher_files():
        ast.parse(path.read_text(), filename=str(path))
