# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP resource-read error paths: no silent escalation, no silent success.

Two failure modes are covered:

1. **Resource reads must degrade, not raise.** The `pry://x402/pricing` and
   `pry://referrals` handlers only ever caught ``(json.JSONDecodeError,
   ValueError)`` — types those code paths can never raise, so a real
   ``AttributeError`` / ``TypeError`` escaped and broke the MCP response. The
   error payload must be returned AND the failure logged.
2. **Autocomplete must not fake an empty result.** A failed ``template_id``
   completion returned ``{"values": []}``, which is indistinguishable from
   "no matching template". The failure must be logged.
"""

from __future__ import annotations

import json
import logging
import sys
import types

import pytest

from pry_mcp.resources_handler import ResourceHandler


@pytest.fixture
def handler() -> ResourceHandler:
    """A handler registered with the two resources exercised below."""
    return ResourceHandler(
        resources={
            "pry://x402/pricing": {"mimeType": "application/json"},
            "pry://referrals": {"mimeType": "application/json"},
        },
        prompts={},
        tools={},
    )


def _install_raising_attr(target: str, attr: str, exc: BaseException) -> None:
    """Force ``target.attr`` access to raise ``exc``.

    Uses a module-level stub installed into ``sys.modules`` rather than
    ``mock.patch`` so the ratchet is untouched. Realistic failure: the
    expected attribute no longer exists (relocated or renamed upstream).
    """
    module = types.ModuleType(target)
    setattr(module, attr, types.SimpleNamespace(__getattr__=_raise(exc)))
    sys.modules[target] = module


def _raise(exc: BaseException):
    def _raiser(_name: str):
        raise exc

    return _raiser


# ---------------------------------------------------------------------------
# Fix 1: resource reads degrade to an error payload and log
# ---------------------------------------------------------------------------


def test_x402_pricing_attribute_error_is_reported_not_raised(
    handler: ResourceHandler, caplog: pytest.LogCaptureFixture
) -> None:
    """An AttributeError from get_stats() must not escape the resource read."""
    boom = AttributeError("X402Handler has no attribute 'get_stats'")
    original = sys.modules.get("pry.payments.x402")
    _install_raising_attr("pry.payments.x402", "X402Handler", boom)
    try:
        with caplog.at_level(logging.WARNING, logger="pry_mcp.resources_handler"):
            response = handler.read_resource("pry://x402/pricing")
    finally:
        if original is not None:
            sys.modules["pry.payments.x402"] = original
        else:
            sys.modules.pop("pry.payments.x402", None)

    # Degrades to a well-formed MCP error payload instead of raising.
    text = response["contents"][0]["text"]
    assert "error" in json.loads(text)
    # And it is visible in the log, not silent.
    assert any(r.levelno >= logging.WARNING for r in caplog.records), "failure was not logged"


def test_referrals_attribute_error_is_reported_not_raised(
    handler: ResourceHandler, caplog: pytest.LogCaptureFixture
) -> None:
    """An AttributeError from get_catalog() must not escape the resource read."""
    boom = AttributeError("ReferralTracker has no attribute 'get_catalog'")
    original = sys.modules.get("pry.commerce.referrals")
    _install_raising_attr("pry.commerce.referrals", "ReferralTracker", boom)
    try:
        with caplog.at_level(logging.WARNING, logger="pry_mcp.resources_handler"):
            response = handler.read_resource("pry://referrals")
    finally:
        if original is not None:
            sys.modules["pry.commerce.referrals"] = original
        else:
            sys.modules.pop("pry.commerce.referrals", None)

    text = response["contents"][0]["text"]
    assert "error" in json.loads(text)
    assert any(r.levelno >= logging.WARNING for r in caplog.records), "failure was not logged"


# ---------------------------------------------------------------------------
# Fix 2: a failed completion is logged, not reported as "no suggestions"
# ---------------------------------------------------------------------------


def test_failed_template_completion_is_logged(
    handler: ResourceHandler, caplog: pytest.LogCaptureFixture
) -> None:
    """A broken template registry must be logged, not silently yield no values."""
    boom = RuntimeError("template registry unavailable")
    original = sys.modules.get("pry.commerce.template_engine")
    module = types.ModuleType("pry.commerce.template_engine")

    def _list_templates():
        raise boom

    module.list_templates = _list_templates  # type: ignore[attr-defined]
    sys.modules["pry.commerce.template_engine"] = module
    try:
        with caplog.at_level(logging.WARNING, logger="pry_mcp.resources_handler"):
            result = handler.complete(
                {"type": "ref/tool", "name": "pry_template"},
                {"name": "template_id", "value": "amz"},
            )
    finally:
        if original is not None:
            sys.modules["pry.commerce.template_engine"] = original
        else:
            sys.modules.pop("pry.commerce.template_engine", None)

    # Values stay empty (correct — we have nothing to offer) ...
    assert result == {"values": []}
    # ... but the failure is no longer indistinguishable from "no match".
    assert any(r.levelno >= logging.WARNING for r in caplog.records), "failure was not logged"
    assert "template_id" in caplog.text
