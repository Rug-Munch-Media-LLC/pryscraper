"""Free-path behavior: what a self-hoster actually gets when x402 is off.

The self-host profile is the "you pay with your own hardware" product surface.
This module proves the three claims that make that promise true, in
descending order of blast radius:

1. ``PRY_X402_ENABLED=false`` really removes the payment gate — a keyless
   request to a PAID endpoint is served normally instead of being answered
   with a 402 challenge.
2. The switch is not a soft "log a warning" flag — ``X402Middleware`` is not
   in the middleware stack at all, and the /mcp mount is likewise absent when
   ``PRY_MCP_ENABLED=false``.
3. The default (variables unset) is unchanged: the gate IS installed and a
   keyless paid request still gets 402. A self-host profile that quietly
   disabled monetization on the hosted deployment would be a revenue bug, so
   the default is pinned by test rather than by comment.

Assertion 1 is the load-bearing one. The switches are read once at import
(app assembly happens at module import), so these tests build the app in a
SUBPROCESS with the environment set — a TestClient built from an
already-imported ``app`` would silently reuse the default-on wiring and pass
vacuously.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# A PAID path (first matching prefix in PAID_ENDPOINTS) and a FREE one, used to
# prove the gate discriminates rather than blanket-answering.
PAID_PATH = "/v1/scrape"
FREE_PATH = "/v1/pricing"

_INSPECT_SNIPPET = """
import json
from starlette.routing import Mount
from pry.api.api import app

print(json.dumps({
    "middleware": [m.cls.__name__ for m in app.user_middleware],
    "mounts": [r.path for r in app.routes if isinstance(r, Mount)],
    "paths": sorted(r.path for r in app.routes if hasattr(r, "path")),
}))
"""

_PROBE_SNIPPET = """
import json
from fastapi.testclient import TestClient
from pry.api.api import app

client = TestClient(app, raise_server_exceptions=False)
out = {{}}
for label, path in (("paid", {paid!r}), ("free", {free!r})):
    resp = client.post(path, json={{"url": "https://example.com"}})
    out[label] = {{
        "status": resp.status_code,
        "payment_required_header": "payment-required" in
        {{k.lower() for k in resp.headers}},
    }}
print(json.dumps(out))
"""


def _run_py(snippet: str, env_overrides: dict[str, str]) -> dict[str, Any]:
    """Execute a snippet in a fresh interpreter with the switches set."""
    env = {
        **os.environ,
        # Never inherit the developer's live .env: it can carry a wallet and a
        # facilitator that would make these assertions lie.
        "PRY_API_KEY": "selfhost-test-key",
        "PRY_SECRET_BACKEND": "env",
        "PRY_X402_WALLET": "",
        "PRY_X402_SELF_FACILITATE": "0",
        "PRY_X402_FACILITATOR_RPC": "",
        "PRY_X402_FACILITATOR_KEY": "",
        "PRY_REDIS_URL": "",
    }
    env.update(env_overrides)
    proc = subprocess.run(  # noqa: S603 - argv is [interpreter, -c, static snippet]
        [sys.executable, "-c", snippet],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )
    assert proc.returncode == 0, f"probe failed: {proc.stderr.decode()[-2000:]}"
    return json.loads(proc.stdout.decode().strip().splitlines()[-1])


class TestSwitchParsing:
    """The flag parser: only an explicit falsy value turns a switch off."""

    def test_unset_means_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.api.kill_switches import is_enabled

        monkeypatch.delenv("PRY_TEST_SWITCH", raising=False)
        assert is_enabled("PRY_TEST_SWITCH", default=True) is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", " off "])
    def test_falsy_values_disable(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.api.kill_switches import is_enabled

        monkeypatch.setenv("PRY_TEST_SWITCH", value)
        assert is_enabled("PRY_TEST_SWITCH", default=True) is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_enable(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.api.kill_switches import is_enabled

        monkeypatch.setenv("PRY_TEST_SWITCH", value)
        assert is_enabled("PRY_TEST_SWITCH", default=False) is True

    def test_default_can_be_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.api.kill_switches import is_enabled

        monkeypatch.delenv("PRY_TEST_SWITCH", raising=False)
        assert is_enabled("PRY_TEST_SWITCH", default=False) is False

    @pytest.mark.parametrize(
        "value", ["1", "true", "TRUE", "yes", "on", "0", "false", "FALSE", "no", "off"]
    )
    def test_matches_the_startup_validator(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The app and config_validation must never disagree on a switch.

        They are separate readers of the same variables. A divergence would
        surface to an operator as "I switched x402 off and Pry still demands
        a payee wallet", which is indistinguishable from a broken toggle.

        The UNSET case differs by design and is pinned separately: the app
        reads a DEFAULT-ON switch (unset = subsystem installed), while the
        validator reads a REQUIREMENTS trigger (set-and-true = checks apply).
        Every explicit value must agree.
        """
        from pry.api.kill_switches import is_enabled
        from pry.core.config_validation import _env_flag

        monkeypatch.setenv("PRY_TEST_SHARED", value)
        assert is_enabled("PRY_TEST_SHARED", default=True) is _env_flag("PRY_TEST_SHARED"), (
            f"app and validator diverge on {value!r}"
        )


class TestDefaultIsPaid:
    """Decision 2 safety: leaving the variables alone must keep the gate ON."""

    def test_gate_and_mcp_are_installed_by_default(self) -> None:
        model = _run_py(_INSPECT_SNIPPET, {})
        assert "X402Middleware" in model["middleware"]
        assert "/mcp" in model["mounts"]

    def test_keyless_paid_request_still_gets_402(self) -> None:
        result = _run_py(
            _PROBE_SNIPPET.format(paid=PAID_PATH, free=FREE_PATH),
            {},
        )
        assert result["paid"]["status"] == 402, (
            "the hosted default must still challenge keyless paid traffic"
        )
        assert result["paid"]["payment_required_header"] is True


class TestSelfhostFreePath:
    """x402 off: a paid endpoint is served like any other route."""

    def test_paid_endpoint_is_served_without_payment(self) -> None:
        result = _run_py(
            _PROBE_SNIPPET.format(paid=PAID_PATH, free=FREE_PATH),
            {"PRY_X402_ENABLED": "false"},
        )
        assert result["paid"]["status"] != 402, (
            "PRY_X402_ENABLED=false must not emit a payment challenge"
        )
        assert result["paid"]["payment_required_header"] is False
        # A 401/404/422 is fine — the point is that payment is NOT the blocker.
        # The API-key layer still applies, which is what keeps the instance safe.
        assert result["paid"]["status"] in (200, 401, 404, 422, 500), result["paid"]

    def test_middleware_is_absent_not_merely_inert(self) -> None:
        model = _run_py(_INSPECT_SNIPPET, {"PRY_X402_ENABLED": "false"})
        assert "X402Middleware" not in model["middleware"]
        # The free path is unaffected either way.
        assert "PryHttpMiddleware" in model["middleware"]

    def test_mcp_can_be_switched_off(self) -> None:
        model = _run_py(_INSPECT_SNIPPET, {"PRY_MCP_ENABLED": "false"})
        assert "/mcp" not in model["mounts"], "/mcp must be unmounted, not just denied"

    def test_mcp_stays_on_by_default_in_the_selfhost_profile(self) -> None:
        model = _run_py(_INSPECT_SNIPPET, {"PRY_X402_ENABLED": "false"})
        assert "/mcp" in model["mounts"], "self-host ships the agent surface"


class TestConfigValidationAgrees:
    """The validator and the app must read the same switch.

    If they disagreed, an operator could switch x402 off, still be told the
    instance needs a payee wallet at boot, and conclude the switch is broken.
    """

    @staticmethod
    def _settings() -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(
            host="127.0.0.1",
            port=8002,
            api_key="selfhost-test-key",
            database_url="",
            redis_url="",
            proxy_url="",
            proxy_enabled=False,
            x402_wallet="",
            rate_limit_rpm=120,
        )

    def test_no_wallet_required_when_x402_is_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.core.config_validation import has_errors, validate_config

        monkeypatch.setenv("PRY_X402_ENABLED", "false")
        monkeypatch.setenv("PRY_X402_WALLET", "")
        issues = validate_config(self._settings())
        assert not any("x402 is enabled" in issue for issue in issues), issues
        assert not has_errors(issues), issues

    def test_wallet_required_when_x402_is_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.core.config_validation import validate_config

        monkeypatch.setenv("PRY_X402_ENABLED", "true")
        monkeypatch.setenv("PRY_X402_WALLET", "")
        issues = validate_config(self._settings())
        assert any("x402 is enabled" in issue for issue in issues), issues
