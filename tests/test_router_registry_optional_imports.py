# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

"""Optional router imports must announce themselves when they do not import.

A guarded import that swallows ``ImportError`` leaves ``_X_ROUTER = None``, so
the router is never mounted and its endpoints 404 with no handler, no
traceback and no log line. ``_log_missing_router`` is the single in-band
signal; these tests lock both halves of the contract — the module name is
logged, and the import is still swallowed so a missing router cannot break
app startup.
"""

from __future__ import annotations

import importlib
import logging
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

from pry.api import router_registry

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest

_GOV_DATA = "pry.api.routers.data.gov_data"


@contextmanager
def _gov_data_unimportable() -> Iterator[None]:
    """Reload the registry with the optional gov_data module unimportable.

    ``patch.dict(sys.modules, {name: None})`` makes ``import name`` raise
    ImportError; the real module is evicted from sys.modules first so the
    shadow takes effect. The registry is reloaded again on the way out, so
    this leaves the rest of the suite with the true module.
    """
    real = sys.modules.pop(_GOV_DATA, None)
    try:
        with patch.dict(sys.modules, {_GOV_DATA: None}):
            yield
    finally:
        if real is not None:
            sys.modules[_GOV_DATA] = real
        importlib.reload(router_registry)


def test_missing_optional_router_logs_module_name(caplog: pytest.LogCaptureFixture) -> None:
    """The guard names the module that did not import, at DEBUG level."""
    caplog.set_level(logging.DEBUG, logger=router_registry.__name__)

    with _gov_data_unimportable():
        importlib.reload(router_registry)
        records = [r for r in caplog.records if "Optional router module" in r.getMessage()]

    assert records, "a guarded import that did not import must log"
    assert all(r.levelno == logging.DEBUG for r in records)
    assert _GOV_DATA in "\n".join(r.getMessage() for r in records)


def test_missing_optional_router_yields_none_and_module_still_imports() -> None:
    """ImportError stays swallowed: registry imports, router resolves to None."""
    with _gov_data_unimportable():
        reloaded = importlib.reload(router_registry)
        # Module attribute: SLF001 flags private access, but this is the very
        # public contract under test — the guard must yield None, not raise.
        assert reloaded._GOV_DATA_ROUTER is None
        # The module is really loaded, not a stub: the mount function is present.
        assert reloaded.register_routers is not None
