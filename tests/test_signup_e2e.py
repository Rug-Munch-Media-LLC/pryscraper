# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""End-to-end signup automation tests."""

from __future__ import annotations

import json as _json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from pry.commerce.signup.engine import SignupAutomation, _page_has_captcha, generate_password
from pry.commerce.signup.form_detection import classify_role, detect_signup_form


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", url: str = "https://example.com/"):
        self.status_code = status_code
        self.text = text
        self.url = url
        self._request = httpx.Request("GET", url)

    def json(self) -> object:
        return _json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self._request, response=self)


SIGNUP_PAGE_HTML = """<html><body>
<form action="/register" method="post">
  <label for="email">Email address</label>
  <input type="email" id="email" name="email" required>
  <label for="password">Password</label>
  <input type="password" id="password" name="password" required>
  <label for="username">Username</label>
  <input type="text" id="username" name="username">
  <label>Full name <input type="text" name="full_name"></label>
  <button type="submit" name="commit" value="Sign Up">Sign Up</button>
  <input type="hidden" name="csrf" value="tok123">
</form></body></html>"""

SIGNUP_PAGE_WITH_CAPTCHA = """<html><body>
<form action="/register" method="post">
  <input type="email" name="email" required>
  <input type="password" name="password" required>
  <div class="g-recaptcha" data-sitekey="test_key_123"></div>
  <button type="submit">Sign Up</button>
</form></body></html>"""


class TestEndToEndSignup:
    """End-to-end signup automation tests."""

    def test_generate_password_default(self) -> None:
        pw = generate_password()
        assert len(pw) == 16
        assert pw.isalnum()

    def test_generate_password_custom_length(self) -> None:
        pw = generate_password(20)
        assert len(pw) == 20

    def test_generate_password_minimum_length(self) -> None:
        pw = generate_password(4)
        assert len(pw) >= 8

    def test_page_has_captcha_detects_recaptcha(self) -> None:
        assert _page_has_captcha(SIGNUP_PAGE_WITH_CAPTCHA) is True

    def test_page_has_captcha_no_captcha(self) -> None:
        assert _page_has_captcha(SIGNUP_PAGE_HTML) is False

    def test_detect_signup_form_finds_form(self) -> None:
        form = detect_signup_form(SIGNUP_PAGE_HTML, "https://example.com/")
        assert form is not None
        assert form.method == "post"
        assert "register" in form.action

    def test_detect_signup_form_no_form(self) -> None:
        form = detect_signup_form("<html><body>No form here</body></html>", "https://example.com/")
        assert form is None

    def test_classify_role_email(self) -> None:
        assert classify_role(name="email") == "email"

    def test_classify_role_password(self) -> None:
        assert classify_role(name="password") == "password"

    def test_classify_role_username(self) -> None:
        assert classify_role(name="username") == "username"

    @pytest.mark.asyncio
    async def test_register_success_flow(self) -> None:
        engine = SignupAutomation()
        get_resp = FakeResponse(200, SIGNUP_PAGE_HTML, "https://example.com/register")
        post_resp = FakeResponse(200, '{"status": "ok"}', "https://example.com/register")

        with (
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=get_resp),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=post_resp),
            patch(
                "pry.commerce.signup.engine.verify_email",
                new_callable=AsyncMock,
                return_value={"verified": False},
            ),
        ):
            result = await engine.register(
                "https://example.com/register",
                {"full_name": "Test User", "username": "testuser"},
                "test@example.com",
            )

        assert result["success"] is True
        assert "submitted" in result

    @pytest.mark.asyncio
    async def test_register_no_form_detected(self) -> None:
        engine = SignupAutomation()
        get_resp = FakeResponse(200, "<html><body>No form</body></html>", "https://example.com/")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=get_resp):
            result = await engine.register("https://example.com/", {}, "test@example.com")

        assert result["success"] is False
        assert "no signup form" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_register_http_error(self) -> None:
        engine = SignupAutomation()
        get_resp = FakeResponse(500, "Server Error", "https://example.com/")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=get_resp):
            result = await engine.register("https://example.com/", {}, "test@example.com")

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_register_with_captcha(self) -> None:
        engine = SignupAutomation()
        get_resp = FakeResponse(200, SIGNUP_PAGE_WITH_CAPTCHA, "https://example.com/register")
        post_resp = FakeResponse(200, '{"status": "ok"}', "https://example.com/register")

        with (
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=get_resp),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=post_resp),
            patch(
                "pry.commerce.signup.engine.verify_email",
                new_callable=AsyncMock,
                return_value={"verified": False},
            ),
        ):
            result = await engine.register(
                "https://example.com/register",
                {"full_name": "Test User"},
                "test@example.com",
            )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_register_never_raises(self) -> None:
        engine = SignupAutomation()

        with patch("httpx.AsyncClient.get", side_effect=Exception("network error")):
            result = await engine.register("https://example.com/", {}, "test@example.com")

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_register_with_verification_email(self) -> None:
        engine = SignupAutomation()
        get_resp = FakeResponse(200, SIGNUP_PAGE_HTML, "https://example.com/register")
        post_resp = FakeResponse(200, '{"status": "ok"}', "https://example.com/register")

        with (
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=get_resp),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=post_resp),
            patch(
                "pry.commerce.signup.engine.verify_email",
                new_callable=AsyncMock,
                return_value={
                    "verified": True,
                    "link": "https://example.com/verify?token=abc",
                },
            ),
        ):
            result = await engine.register(
                "https://example.com/register",
                {"full_name": "Test User"},
                "test@example.com",
            )

        # Verification email flow — result may indicate pending verification
        assert result["success"] is True or "verification" in str(result).lower()
