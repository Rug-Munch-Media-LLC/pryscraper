"""CSS selector validation shared by the selector and schema engines.

ReDoS guard: a user-supplied selector must be validated before it reaches
cssselect. Raises ``InvalidRequestError`` so the API maps it to a 400 field
error instead of leaking a parser exception or running a pathological selector.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from pry.core.errors import InvalidRequestError


def validate_selector(selector: str, *, field: str) -> str:
    """Validate a user-supplied CSS selector; raise 400-style on rejection."""
    try:
        from extraction.css import _validate_css_selector
    except ImportError:  # pragma: no cover - extraction ships with Pry
        return selector
    try:
        return _validate_css_selector(selector)
    except ValueError as exc:
        raise InvalidRequestError(f"Invalid {field}: {exc}", details={"field": field}) from exc


#: Historical private name, kept for the existing call sites/tests.
_validate_selector = validate_selector

__all__ = ["_validate_selector", "validate_selector"]
