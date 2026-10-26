"""Tests for the CAPTCHA ladder: order, key absence, robots, submission."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import httpx
import pytest
import respx

from pry.core.settings import settings
from pry.engine.captcha import flaresolverr as fs_mod
from pry.engine.captcha.diagnostics import captcha_diagnostics
from pry.engine.captcha.ladder import LADDER_ORDER, LadderResult, solve_ladder
from pry.engine.captcha.lanes import TOKEN_METHODS, Challenge
from pry.engine.captcha.submit import submit_solution
from pry.engine.captcha.token_api import CAPSOLVER_CREATE_URL, CAPSOLVER_RESULT_URL

TARGET = "https://target.test/challenge"
UNSOLVED_HTML = "<html><body>Please verify you are human. g-recaptcha</body></html>"
FLARE_OK = {
    "status": "ok",
    "solution": {"status": 200, "response": UNSOLVED_HTML, "cookies": [], "userAgent": "ua"},
}
ROBOTS_ALLOW = "User-agent: *\nAllow: /\n"
ROBOTS_DENY = "User-agent: *\nDisallow: /private\n"
WIDGET = Challenge(url=TARGET, html=UNSOLVED_HTML, captcha_type="recaptcha_v2", sitekey="SITEKEY")


def _mock_flare(router: respx.Router, payload: dict | None = None) -> None:
    for endpoint in fs_mod._endpoints():
        router.post(endpoint).mock(return_value=httpx.Response(200, json=payload or FLARE_OK))


async def _no_key_run(monkeypatch: pytest.MonkeyPatch, tmp_path) -> LadderResult:
    monkeypatch.setenv("PRY_CAPTCHA_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "")
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "")
    with respx.mock(assert_all_called=False) as router:
        router.get("https://target.test/robots.txt").mock(
            return_value=httpx.Response(200, text=ROBOTS_ALLOW)
        )
        _mock_flare(router)
        return await solve_ladder(WIDGET)


async def _key_run(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[LadderResult, str, str]:
    monkeypatch.setenv("PRY_CAPTCHA_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "test-key")
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "")
    with respx.mock(assert_all_called=False) as router:
        router.get("https://target.test/robots.txt").mock(
            return_value=httpx.Response(200, text=ROBOTS_ALLOW)
        )
        _mock_flare(router, {"status": "error", "message": "not cleared"})
        create = router.post(CAPSOLVER_CREATE_URL).mock(
            return_value=httpx.Response(200, json={"errorId": 0, "taskId": "task-1"})
        )
        router.post(CAPSOLVER_RESULT_URL).mock(
            return_value=httpx.Response(
                200, json={"status": "ready", "solution": {"gRecaptchaResponse": "TOKEN123"}}
            )
        )
        submitted = router.post(TARGET).mock(return_value=httpx.Response(200, text="ok"))
        result = await solve_ladder(WIDGET)
        await submit_solution(TARGET, result.token or "")
        return (
            result,
            create.calls[0].request.content.decode(),
            submitted.calls[0].request.content.decode(),
        )


async def _robots_run(monkeypatch: pytest.MonkeyPatch, tmp_path) -> LadderResult:
    monkeypatch.setenv("PRY_CAPTCHA_ENV_FILE", str(tmp_path / "absent.env"))
    url = "https://private.test/private/page"
    with respx.mock(assert_all_called=False) as router:
        router.get("https://private.test/robots.txt").mock(
            return_value=httpx.Response(200, text=ROBOTS_DENY)
        )
        router.post(fs_mod._endpoints()[0]).mock(
            side_effect=AssertionError("solver lane called on a robots-disallowed URL")
        )
        return await solve_ladder(Challenge(url=url, html=UNSOLVED_HTML))


@pytest.mark.asyncio
async def test_no_key_attempts_free_lanes_in_order(monkeypatch, tmp_path):
    """(a) No key: flaresolverr then image are attempted, in that order."""
    result = await _no_key_run(monkeypatch, tmp_path)
    assert result.status == "blocked.captcha_unsolved"
    assert [a.provider for a in result.attempts] == list(LADDER_ORDER)
    assert [a.provider for a in result.attempts][:2] == ["flaresolverr", "image"]


@pytest.mark.asyncio
async def test_no_key_names_missing_keys(monkeypatch, tmp_path):
    """(a) The unsolved result names the two missing key env vars."""
    result = await _no_key_run(monkeypatch, tmp_path)
    outcomes = {a.provider: a.outcome for a in result.attempts}
    assert result.missing_keys == [
        "PRY_CAPTCHA_CAPSOLVER_API_KEY",
        "PRY_CAPTCHA_2CAPTCHA_API_KEY",
    ]
    assert outcomes["capsolver"] == "no_key"
    assert outcomes["2captcha"] == "no_key"


@pytest.mark.asyncio
async def test_mocked_key_capsolver_request_shape(monkeypatch, tmp_path):
    """(b) A token key produces the documented Capsolver request shape."""
    result, body, _ = await _key_run(monkeypatch, tmp_path)
    assert result.status == "solved"
    assert result.provider == "capsolver"
    assert result.token == "TOKEN123"
    assert "test-key" in body
    assert TOKEN_METHODS["recaptcha_v2"][1] in body
    assert "SITEKEY" in body
    assert TARGET in body


@pytest.mark.asyncio
async def test_solved_token_is_submitted(monkeypatch, tmp_path):
    """(b) The solved token is posted back to the page."""
    _, _, submitted = await _key_run(monkeypatch, tmp_path)
    assert "TOKEN123" in submitted


@pytest.mark.asyncio
async def test_robots_disallowed_has_zero_attempts(monkeypatch, tmp_path):
    """(c) A robots-disallowed URL is refused with no solver attempt."""
    result = await _robots_run(monkeypatch, tmp_path)
    assert result.status == "blocked.robots"
    assert result.attempts == []


def test_diagnostics_reports_unavailable_token_providers(monkeypatch, tmp_path):
    """Missing keys are loud in diagnostics; solving stays enabled."""
    monkeypatch.setenv("PRY_CAPTCHA_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "")
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "")
    report = captcha_diagnostics()
    assert report["enabled"] is True
    assert set(report["token_providers_unavailable"]) == {
        "PRY_CAPTCHA_CAPSOLVER_API_KEY",
        "PRY_CAPTCHA_2CAPTCHA_API_KEY",
    }
