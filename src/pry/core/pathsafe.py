"""Pry - safe path construction from untrusted identifiers.

Every module that turns a caller-supplied identifier into a filesystem path
must funnel through :func:`safe_join`. Path traversal here is not theoretical:
a ``session_id`` of ``../../etc/passwd`` turns an ordinary delete call into an
arbitrary-file unlink (CWE-22).

Two independent checks, both required:

1. :func:`validate_id` rejects anything that is not a single opaque path
   segment. Reject - never sanitize. ``os.path.basename("../../etc/passwd")``
   returns ``passwd``, which quietly rewrites an attack into a plausible-looking
   valid id and hides the attempt from logs and from the caller.
2. :func:`safe_join` re-checks containment after resolution, catching anything
   check 1 missed (symlinks, platform-specific separators, future callers).

Contiguity matters in check 2: ``/data/sessions_evil`` shares a string prefix
with ``/data/sessions`` but is not inside it, so ``str().startswith()`` is
wrong. ``Path.is_relative_to`` compares whole path components.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from pry.core.errors import InvalidRequestError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# An identifier is one path segment made only of characters that cannot alter
# path structure: ASCII alphanumerics, underscore, dot, hyphen.
#
# A leading dot is excluded so no id can ever be ".", "..", or a hidden file.
# A bare ".." can only be built from dots, which the leading-dot rule removes;
# the explicit alternative below is kept as a readable second line of defence
# rather than relying on a reader to work that out.
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

MAX_ID_LENGTH = 128


def validate_id(value: str, *, kind: str = "identifier") -> str:
    """Return ``value`` unchanged if it is a single safe path segment.

    Args:
        value: Caller-supplied identifier.
        kind: Field name for the error message, e.g. ``"session_id"``.

    Returns:
        The original string, unmodified.

    Raises:
        InvalidRequestError: 400 if the value is empty, too long, or contains
            any character that could change path structure.

    Note:
        Deliberately permissive about WHICH opaque token is used. Ids are
        generated as ``session_<12 hex>``, but the codebase also stores and
        round-trips ids like ``s3``, ``s_a``, ``old`` and ``session-abc``.
        Requiring the exact generated shape would reject those existing files,
        so the rule constrains the alphabet and shape only - never the format.
    """
    if not value or len(value) > MAX_ID_LENGTH:
        _reject(value, kind, "empty_or_too_long")
    if value.startswith(".") or value in {".", ".."}:
        _reject(value, kind, "leading_dot_or_dot_segment")
    if not _ID_PATTERN.fullmatch(value):
        _reject(value, kind, "illegal_character")
    return value


def safe_join(base_dir: Path, identifier: str, suffix: str, *, kind: str = "identifier") -> Path:
    """Build a path for ``identifier`` inside ``base_dir``, or raise.

    Args:
        base_dir: Directory the result must stay inside. Need not exist yet.
        identifier: Caller-supplied opaque token.
        suffix: Filename suffix, including the dot, e.g. ``".json"``.
        kind: Field name for error messages.

    Returns:
        The absolute, resolved path, guaranteed inside ``base_dir``.

    Raises:
        InvalidRequestError: 400 if the id is malformed or if the resolved
            path escapes ``base_dir`` by any means.
    """
    validate_id(identifier, kind=kind)
    base = base_dir.resolve()
    candidate = (base / f"{identifier}{suffix}").resolve()
    # is_relative_to compares components, so a sibling like
    # ``../sessions_evil/x`` is correctly rejected.
    if not candidate.is_relative_to(base):
        _reject(identifier, kind, "escapes_base_dir")
    return candidate


def _reject(value: str, kind: str, reason: str) -> None:
    """Log the rejected value and raise a 400. Never returns."""
    logger.warning(
        "path_traversal_rejected",
        extra={"field": kind, "reason": reason, "value_len": len(value)},
    )
    raise InvalidRequestError(f"Invalid {kind}", details={"field": kind, "reason": reason})
