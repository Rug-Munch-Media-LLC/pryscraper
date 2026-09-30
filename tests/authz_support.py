# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fixtures shared by the authz suites, kept out of tests/conftest.py.

conftest.py is already at the 200-line ratchet ceiling, so anything the
authz suites need lives here and is pulled in by an explicit import rather
than a global. Every test that touches the credential vault must take
``isolated_vault`` — the operator's real ``~/.pry/vault`` holds thousands of
live credential rows.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


@pytest.fixture
def isolated_vault(tmp_path: Any) -> Generator[Any, None, None]:
    """Point the credential vault at tmp_path, restoring it on teardown.

    Regression: the vault tests called store_credential() with no isolation,
    so they read and wrote the operator's LIVE ~/.pry/vault (2500+ real
    credential rows on Talos) and, passing no owner, wrote into the shared
    legacy namespace.
    """
    from pathlib import Path

    from pry.api import credential_vault

    original = credential_vault.VAULT_DIR
    scratch = Path(str(tmp_path)) / "vault"
    scratch.mkdir(parents=True, exist_ok=True)
    credential_vault.VAULT_DIR = scratch
    try:
        yield scratch
    finally:
        credential_vault.VAULT_DIR = original


@pytest.fixture
def set_env() -> Generator[Callable[[dict[str, str]], None], None, None]:
    """Set env vars for one test and restore them afterwards.

    Deliberately not pytest's monkeypatch: these suites must not add to the
    repo's monkeypatch ratchet, and an explicit save/restore reads the same
    way while keeping the blast radius obvious.
    """
    saved: dict[str, str | None] = {}

    def _apply(values: dict[str, str]) -> None:
        for key, value in values.items():
            saved.setdefault(key, os.environ.get(key))
            if value == "":
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    try:
        yield _apply
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
