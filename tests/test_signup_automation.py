# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT.
"""Tests for the signup automation engine (form detection, verification, engine)."""

from __future__ import annotations

import json as _json
from email.message import EmailMessage
from typing import TYPE_CHECKING, cast

import httpx

from signup.email_verification import (
    IMAPConfig,
    extract_verification_link,
    fetch_temp_mail,
    imap_config_from_env,
    poll_imap_for_verification,
    verify_email,
)
from signup.engine import SignupAutomation, generate_password
from signup.form_detection import classify_role, detect_signup_form

if TYPE_CHECKING:
    import pytest

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


# ---------------------------------------------------------------------------
# Fixtures / doubles
# ---------------------------------------------------------------------------


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
            response = httpx.Response(self.status_code, request=self._request, text=self.text)
            raise httpx.HTTPStatusError("error", request=self._request, response=response)


class FakeClient:
    """Minimal injectable httpx.AsyncClient stand-in for engine tests."""

    def __init__(self, responses: dict[str, FakeResponse] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.cookies = httpx.Cookies()
        self.cookies.set("session", "abc123")
        self.closed = False

    def _match(self, url: str) -> FakeResponse:
        for key, response in self.responses.items():
            if key in url:
                return response
        return FakeResponse(200, url=url)

    async def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("get", url, kwargs))
        return self._match(url)

    async def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("post", url, kwargs))
        return self._match(url)

    async def aclose(self) -> None:
        return None


class FakeIMAP:
    """Minimal imaplib.IMAP4_SSL stand-in."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.messages: dict[int, bytes] = {}
        self.logged_out = False

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        return ("OK", [b"LOGIN completed"])

    def select(self, mailbox: str = "INBOX") -> tuple[str, list[bytes]]:
        return ("OK", [b"1"])

    def search(self, charset: object, *criteria: object) -> tuple[str, list[bytes]]:
        if self.messages:
            ids = b" ".join(str(num).encode() for num in sorted(self.messages))
            return ("OK", [ids])
        return ("OK", [b""])

    def fetch(self, num: bytes, part: str) -> tuple[str, list[tuple[bytes, bytes] | bytes]]:
        raw = self.messages[int(num)]
        return ("OK", [(b"1 (RFC822 {123}", raw)])

    def logout(self) -> tuple[str, list[bytes]]:
        self.logged_out = True
        return ("BYE", [b"Logging out"])


class FakeHTTPXClient:
    """Stand-in httpx client for mail.tm API tests."""

    def __init__(self, token: str | None = "tok123", messages: list[dict[str, str]] | None = None):  # noqa: S107 - test fixture token
        self.token = token
        self.messages = messages or [{"id": "m1", "subject": "Verify your account"}]
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    async def post(self, url: str, json: object = None, **kwargs: object):
        self.calls.append(("post", url))
        if url.endswith("/token"):
            if self.token is None:
                return FakeResponse(200, '{"token": null}')
            return FakeResponse(200, _json.dumps({"token": self.token}))
        if url.endswith("/accounts"):
            # Account creation succeeds → subsequent /token calls now work.
            self.token = self.token or "tok-new"
            return FakeResponse(201, '{"id": "1"}')
        return FakeResponse(200, "{}")

    async def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("get", url))
        if url.endswith("/messages"):
            return FakeResponse(200, _json.dumps(self.messages))
        if url.endswith("/messages/m1"):
            return FakeResponse(
                200,
                _json.dumps(
                    {
                        "text": "Confirm your account: https://example.com/verify?t=1",
                        "html": [],
                    }
                ),
            )
        return FakeResponse(200, "{}")

    async def aclose(self) -> None:
        self.closed = True


def make_message(body: str) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Verify your account"
    msg["From"] = "noreply@example.com"
    msg["To"] = "user@example.com"
    msg.set_content(body)
    return bytes(msg)


def make_engine_client() -> FakeClient:
    return FakeClient(
        responses={
            "https://example.com/signup": FakeResponse(
                200, SIGNUP_PAGE_HTML, url="https://example.com/signup"
            ),
            "https://example.com/register": FakeResponse(
                201, "", url="https://example.com/register"
            ),
            "https://example.com/confirm": FakeResponse(200, "", url="https://example.com/confirm"),
        }
    )


# ---------------------------------------------------------------------------
# Password generation
# ---------------------------------------------------------------------------


def test_generate_password_default_length() -> None:
    password = generate_password()
    assert len(password) == 16
    assert password.isalnum()


def test_generate_password_minimum_length() -> None:
    assert len(generate_password(4)) == 8
    assert len(generate_password(24)) == 24


def test_generate_password_unique() -> None:
    assert generate_password() != generate_password()


# ---------------------------------------------------------------------------
# Form detection
# ---------------------------------------------------------------------------


def test_detect_signup_form_classifies_fields() -> None:
    form = detect_signup_form(SIGNUP_PAGE_HTML, "https://example.com/signup")
    assert form is not None
    assert form.action == "https://example.com/register"
    assert form.method == "post"
    assert form.email_field is not None
    assert form.email_field.name == "email"
    assert form.email_field.required is True
    assert form.password_field is not None
    assert form.password_field.name == "password"
    assert form.username_field is not None
    assert form.username_field.name == "username"
    assert form.full_name_field is not None
    assert form.full_name_field.name == "full_name"
    assert form.submit_button is not None
    assert form.submit_button.name == "commit"
    assert [f.name for f in form.hidden_fields()] == ["csrf"]
    assert form.score() >= 8


def test_detect_signup_form_label_text() -> None:
    form = detect_signup_form(SIGNUP_PAGE_HTML, "https://example.com/signup")
    assert form is not None
    assert form.email_field is not None
    assert form.email_field.label == "Email address"
    assert form.full_name_field is not None
    assert form.full_name_field.label == "Full name"


def test_detect_signup_form_none_when_no_form() -> None:
    assert detect_signup_form("<html><body><p>nothing here</p></body></html>") is None


def test_detect_signup_form_login_style_qualifies() -> None:
    html = """<form method="post"><input name="email" type="email">
    <input name="password" type="password">
    <button type="submit">Log in</button></form>"""
    form = detect_signup_form(html)
    assert form is not None
    assert form.email_field is not None
    assert form.password_field is not None


def test_detect_prefers_richer_signup_form() -> None:
    html = """<form action="/login" method="post">
      <input name="email" type="email"><input name="password" type="password">
    </form>
    <form action="/register" method="post">
      <input name="email" type="email"><input name="password" type="password">
      <input name="full_name" type="text"><input name="username" type="text">
      <button type="submit">Sign up</button>
    </form>"""
    form = detect_signup_form(html, "https://example.com/")
    assert form is not None
    assert form.form_index == 1
    assert form.action == "https://example.com/register"


def test_detect_ignores_script_and_nested_forms() -> None:
    html = """<script>var email = "x@y.z";</script>
    <form><input name="email" type="email"><input name="password" type="password">
    <div><form><input name="nested" type="text"></form></div>
    </form>"""
    form = detect_signup_form(html)
    assert form is not None
    names = {f.name for f in form.fields}
    assert "email" in names
    assert "password" in names
    assert "nested" not in names  # nested form popped off the stack


def test_classify_role_variants() -> None:
    assert classify_role(name="email", field_type="text") == "email"
    assert classify_role(name="user_mail", field_type="text") == "email"
    assert classify_role(field_type="password") == "password"
    assert classify_role(name="passwd", field_type="text") == "password"
    assert classify_role(name="username") == "username"
    assert classify_role(name="login_id") == "username"
    assert classify_role(name="fullname") == "full_name"
    assert classify_role(label="Full name") == "full_name"
    assert classify_role(autocomplete="email") == "email"
    assert classify_role(autocomplete="new-password") == "password"
    assert classify_role(name="password2", field_type="password") == "password"
    assert classify_role(name="confirm_password", field_type="password") == "confirm_password"
    assert classify_role(field_type="submit") == "submit"
    assert classify_role(tag="button", field_type="submit") == "submit"
    assert classify_role(name="g-recaptcha") == "captcha"
    assert classify_role(name="first_name") == "text"


def test_detect_select_and_textarea() -> None:
    html = """<form method="post">
      <input name="email" type="email"><input name="password" type="password">
      <select name="country"><option value="US">US</option></select>
      <textarea name="bio"></textarea>
    </form>"""
    form = detect_signup_form(html)
    assert form is not None
    roles = {f.name: f.role for f in form.fields}
    assert roles["country"] == "select"
    assert roles["bio"] == "textarea"


# ---------------------------------------------------------------------------
# Verification link/code extraction
# ---------------------------------------------------------------------------


def test_extract_verification_link_keyword() -> None:
    body = "Welcome! Click https://example.com/verify?token=abc123 to confirm your account."
    link, code = extract_verification_link(body)
    assert link == "https://example.com/verify?token=abc123"
    assert code is None


def test_extract_verification_link_from_html() -> None:
    html = '<a href="https://app.example.com/activate?id=9">Activate now</a>'
    link, _ = extract_verification_link("", html)
    assert link == "https://app.example.com/activate?id=9"


def test_extract_verification_link_single_plain_link() -> None:
    body = "Just go to https://example.com/click/abc and you are done."
    link, _ = extract_verification_link(body)
    assert link == "https://example.com/click/abc"


def test_extract_verification_code() -> None:
    body = "Your verification code is 482913. Enter it to finish."
    link, code = extract_verification_link(body)
    assert code == "482913"
    assert link is None


def test_extract_nothing() -> None:
    link, code = extract_verification_link("No links or codes here.")
    assert link is None
    assert code is None


# ---------------------------------------------------------------------------
# IMAP verification
# ---------------------------------------------------------------------------


def test_imap_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNUP_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("SIGNUP_IMAP_PORT", "143")
    monkeypatch.setenv("SIGNUP_IMAP_USER", "user")
    monkeypatch.setenv("SIGNUP_IMAP_PASSWORD", "secret")
    config = imap_config_from_env()
    assert config is not None
    assert config.host == "imap.example.com"
    assert config.port == 143
    assert config.user == "user"
    assert config.password == "secret"


def test_imap_config_from_env_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNUP_IMAP_HOST", raising=False)
    assert imap_config_from_env() is None


def test_poll_imap_for_verification_finds_link(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeIMAP("imap.example.com", 993)
    fake.messages = {1: make_message("Verify now: https://example.com/confirm?token=abc")}
    monkeypatch.setattr("signup.email_verification.imaplib.IMAP4_SSL", lambda host, port: fake)

    config = IMAPConfig(host="imap.example.com", user="user", password="secret")
    result = poll_imap_for_verification(config, from_email="user@example.com")
    assert result["success"] is True
    assert result["link"] == "https://example.com/confirm?token=abc"
    assert fake.logged_out is True


def test_poll_imap_for_verification_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeIMAP("imap.example.com", 993)
    monkeypatch.setattr("signup.email_verification.imaplib.IMAP4_SSL", lambda host, port: fake)

    config = IMAPConfig(host="imap.example.com", user="user", password="secret")
    result = poll_imap_for_verification(config)
    assert result["success"] is True
    assert result["link"] is None


def test_poll_imap_for_verification_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(host: str, port: int) -> FakeIMAP:
        raise OSError("connection refused")

    monkeypatch.setattr("signup.email_verification.imaplib.IMAP4_SSL", _boom)
    config = IMAPConfig(host="imap.example.com", user="user", password="secret")
    result = poll_imap_for_verification(config)
    assert result["success"] is False
    assert "imap connect failed" in (result.get("error") or "")


async def test_verify_email_imap_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeIMAP("imap.example.com", 993)
    fake.messages = {1: make_message("Confirm: https://example.com/confirm?token=abc")}
    monkeypatch.setattr("signup.email_verification.imaplib.IMAP4_SSL", lambda host, port: fake)
    monkeypatch.setenv("SIGNUP_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("SIGNUP_IMAP_USER", "user")
    monkeypatch.setenv("SIGNUP_IMAP_PASSWORD", "secret")

    result = await verify_email("user@example.com", timeout_seconds=5)
    assert result["verified"] is True
    assert result["method"] == "imap"
    assert result["link"] == "https://example.com/confirm?token=abc"


async def test_verify_email_no_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNUP_IMAP_HOST", raising=False)
    result = await verify_email("user@example.com")
    assert result["verified"] is False
    assert result["method"] == "none"


# ---------------------------------------------------------------------------
# Temp-mail (mail.tm) fallback
# ---------------------------------------------------------------------------


async def test_fetch_temp_mail_finds_link() -> None:
    fake = FakeHTTPXClient()
    result = await fetch_temp_mail("user@mail.tm", password="pwd123", client=fake)  # type: ignore[arg-type]
    assert result["verified"] is True
    assert result["method"] == "mail_tm"
    assert result["link"] == "https://example.com/verify?t=1"
    assert fake.closed is False  # injected client is not owned by fetch_temp_mail


async def test_fetch_temp_mail_creates_account() -> None:
    fake = FakeHTTPXClient(token=None)
    result = await fetch_temp_mail("user@mail.tm", password="pwd123", client=fake)  # type: ignore[arg-type]
    assert result["verified"] is True
    assert any(call[0] == "post" and call[1].endswith("/accounts") for call in fake.calls)


async def test_fetch_temp_mail_no_password() -> None:
    fake = FakeHTTPXClient(token=None)
    result = await fetch_temp_mail("user@mail.tm", password=None, client=fake)  # type: ignore[arg-type]
    assert result["success"] is False
    assert "without a password" in (result.get("error") or "")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


async def test_register_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_verify(email: str, client: object = None) -> dict[str, object]:
        return {
            "success": True,
            "verified": True,
            "method": "imap",
            "link": "https://example.com/confirm?token=abc",
            "code": None,
        }

    monkeypatch.setattr("signup.engine.verify_email", fake_verify)
    client = make_engine_client()
    engine = SignupAutomation(client=client)  # type: ignore[arg-type]

    result = await engine.register(
        "https://example.com/signup", {"full_name": "Jane Doe"}, "jane@example.com"
    )

    assert result["success"] is True
    assert result["status"] == 201
    assert result["submitted"] is True
    assert result["email"] == "jane@example.com"
    assert result["confirmed"] is True
    assert result["session_cookies"] == {"session": "abc123"}
    assert len(result["generated_password"]) >= 8
    assert result["verification"]["method"] == "imap"

    # Verify the submitted payload contained the expected values.
    post_calls = [c for c in client.calls if c[0] == "post"]
    assert any("https://example.com/register" in str(call[1]) for call in post_calls)
    payload = post_calls[0][2]
    assert isinstance(payload, dict)
    data = cast("dict[str, object]", payload.get("data") or {})
    assert data.get("email") == "jane@example.com"
    assert data.get("username") == "jane"
    assert data.get("full_name") == "Jane Doe"
    assert data.get("password") == result["generated_password"]
    assert data.get("csrf") == "tok123"


async def test_register_no_form() -> None:
    client = FakeClient(
        responses={"https://example.com/plain": FakeResponse(200, "<html><body>hi</body></html>")}
    )
    engine = SignupAutomation(client=client)  # type: ignore[arg-type]
    result = await engine.register("https://example.com/plain", {}, "a@b.com")
    assert result["success"] is False
    assert "no signup form" in (result.get("error") or "")


async def test_register_http_error() -> None:
    client = FakeClient(responses={"https://example.com/boom": FakeResponse(500, "server error")})
    engine = SignupAutomation(client=client)  # type: ignore[arg-type]
    result = await engine.register("https://example.com/boom", {}, "a@b.com")
    assert result["success"] is False
    assert "http error" in (result.get("error") or "")


async def test_register_verification_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_verify(email: str, client: object = None) -> dict[str, object]:
        return {
            "success": True,
            "verified": False,
            "method": "none",
            "reason": "no mailbox configured",
            "link": None,
            "code": None,
        }

    monkeypatch.setattr("signup.engine.verify_email", fake_verify)
    client = make_engine_client()
    engine = SignupAutomation(client=client)  # type: ignore[arg-type]
    result = await engine.register("https://example.com/signup", {}, "a@b.com")
    assert result["success"] is True
    assert result["confirmed"] is False
    assert result["verification"]["method"] == "none"


def test_captcha_solver_import_guarded() -> None:
    import signup.engine as engine_module

    # The guard never crashes on import: solve_captcha is either the repo's
    # real solver (callable) or None when captcha_solver is unavailable.
    assert engine_module.solve_captcha is None or callable(engine_module.solve_captcha)


async def test_engine_captcha_solved_with_simple_solver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "signup.engine.solve_captcha",
        lambda html: "tok-from-solver",
    )
    page = SIGNUP_PAGE_HTML.replace(
        "</form>",
        '<div class="g-recaptcha" data-sitekey="6Lc"></div></form>',
    )
    client = FakeClient(
        responses={
            "https://example.com/signup": FakeResponse(200, page, url="https://example.com/signup"),
            "https://example.com/register": FakeResponse(
                201, "", url="https://example.com/register"
            ),
        }
    )
    engine = SignupAutomation(client=client)  # type: ignore[arg-type]
    result = await engine.register("https://example.com/signup", {}, "a@b.com")
    assert result["success"] is True
    post_calls = [c for c in client.calls if c[0] == "post"]
    data = cast("dict[str, object]", post_calls[0][2].get("data") or {})
    assert data.get("g-recaptcha-response") == "tok-from-solver"


async def test_engine_captcha_solver_raises_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken_solver(html: str) -> str:
        raise RuntimeError("solver down")

    monkeypatch.setattr("signup.engine.solve_captcha", _broken_solver)
    page = SIGNUP_PAGE_HTML.replace("</form>", '<div class="h-captcha"></div></form>')
    client = FakeClient(
        responses={
            "https://example.com/signup": FakeResponse(200, page, url="https://example.com/signup"),
            "https://example.com/register": FakeResponse(
                201, "", url="https://example.com/register"
            ),
        }
    )
    engine = SignupAutomation(client=client)  # type: ignore[arg-type]
    result = await engine.register("https://example.com/signup", {}, "a@b.com")
    assert result["success"] is True  # CAPTCHA failure must not fail the flow


async def test_engine_never_raises_on_unknown_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected")

    client = make_engine_client()
    monkeypatch.setattr(client, "get", _boom)
    engine = SignupAutomation(client=client)  # type: ignore[arg-type]
    result = await engine.register("https://example.com/signup", {}, "a@b.com")
    assert result["success"] is False
    assert "signup failed" in (result.get("error") or "")


async def test_engine_owns_and_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[FakeClient] = []

    class OwnedClient(FakeClient):
        def __init__(self, **kwargs: object):
            super().__init__()
            created.append(self)
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr("signup.engine.httpx.AsyncClient", lambda **kwargs: OwnedClient())
    engine = SignupAutomation()  # no client injected → engine creates its own
    result = await engine.register("https://example.com/signup", {}, "a@b.com")
    assert isinstance(result, dict)
    assert len(created) == 1
    assert created[0].closed is True


# ---------------------------------------------------------------------------
# Facade + router
# ---------------------------------------------------------------------------


def test_facade_reexports() -> None:
    import signup_automation

    assert signup_automation.SignupAutomation is SignupAutomation
    assert signup_automation.SignupForm is not None
    assert signup_automation.SignupField is not None


def test_signup_package_exports() -> None:
    import signup

    assert signup.SignupAutomation is SignupAutomation
    assert signup.detect_signup_form is detect_signup_form


def test_router_import_safe_and_exposes_route() -> None:
    from routers.signup import router

    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/v1/signup" in paths


def test_router_endpoint_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.signup import router

    class FakeEngine:
        def __init__(self, client: object = None):
            pass

        async def close(self) -> None:
            return None

        async def register(
            self, url: str, profile: dict[str, object], email: str
        ) -> dict[str, object]:
            return {
                "success": True,
                "url": url,
                "email": email,
                "status": 201,
                "session_cookies": {},
            }

    monkeypatch.setattr("signup.engine.SignupAutomation", FakeEngine)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post(
        "/v1/signup",
        json={
            "url": "https://example.com/signup",
            "profile": {"full_name": "Jane Doe"},
            "email": "jane@example.com",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["email"] == "jane@example.com"
    assert data["status"] == 201


def test_router_endpoint_validation() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.signup import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post("/v1/signup", json={"url": "https://example.com"})
    assert resp.status_code == 422


def test_router_supports_minimal_body(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.signup import router

    class FakeEngine:
        def __init__(self, client: object = None):
            pass

        async def close(self) -> None:
            return None

        async def register(
            self, url: str, profile: dict[str, object], email: str
        ) -> dict[str, object]:
            return {"success": True, "url": url, "email": email, "profile": profile, "status": 201}

    monkeypatch.setattr("signup.engine.SignupAutomation", FakeEngine)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Only url + email → profile defaults to {} via the Pydantic model.
    resp = client.post("/v1/signup", json={"url": "https://example.com", "email": "a@b.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["profile"] == {}
