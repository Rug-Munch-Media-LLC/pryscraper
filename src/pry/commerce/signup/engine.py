"""Signup automation engine — register accounts on arbitrary websites.

The :class:`SignupAutomation` engine orchestrates the full registration flow:

    fetch page → detect form → fill fields (generated password) →
    optional CAPTCHA → submit → poll email for verification → confirm →
    return status + session cookies

Everything runs in-memory (no DB models) and the engine never raises:
failures are returned as ``{"success": False, "error": ...}``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import inspect
import re
import secrets
import string
from typing import TYPE_CHECKING, Any

import httpx

from pry.commerce.signup.email_verification import follow_verification_link, verify_email
from pry.commerce.signup.form_detection import detect_signup_form

if TYPE_CHECKING:
    from pry.commerce.signup.form_detection import SignupField, SignupForm

# Optional CAPTCHA solver. Not a hard dependency: when unavailable the engine
# simply skips CAPTCHA solving (the submit may still succeed). This repo ships
# its own async captcha_solver (captcha_type/sitekey/url signature); a plain
# ``solve_captcha(html)`` callable is also supported for compatibility.
solve_captcha: Any | None
try:
    from pry.engine.captcha_solver import solve_captcha  # type: ignore[import-not-found]
except ImportError:
    solve_captcha = None

PASSWORD_ALPHABET = string.ascii_letters + string.digits
DEFAULT_PASSWORD_LENGTH = 16

_CAPTCHA_MARKERS = ("g-recaptcha", "h-captcha", "captcha", "turnstile", "cf-turnstile")
_CAPTCHA_SITEKEY_RE = re.compile(r'data-sitekey=["\']([^"\']+)["\']')


def generate_password(length: int = DEFAULT_PASSWORD_LENGTH) -> str:
    """Generate a cryptographically random alphanumeric password."""
    length = max(8, length)
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def _page_has_captcha(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in _CAPTCHA_MARKERS)


class SignupAutomation:
    """Automated account-registration engine."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        """Create the engine.

        Args:
            client: Optional shared ``httpx.AsyncClient``. When omitted the
                engine creates (and closes) its own client per registration.
        """
        self._client = client
        self._owns_client = client is None

    async def close(self) -> None:
        """Close the engine's own HTTP client, if it created one."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    # -- public API --------------------------------------------------------

    async def register(self, url: str, profile: dict[str, Any], email: str) -> dict[str, Any]:
        """Register an account at ``url``.

        Args:
            url: The signup page URL.
            profile: Extra profile values keyed by field role or field name
                (e.g. ``{"full_name": "Jane Doe", "username": "jane"}``).
            email: The email address to register with.

        Returns:
            A result dict: ``{"success": True, ...}`` with status, session
            cookies, generated password and verification info, or
            ``{"success": False, "error": ...}``.
        """
        try:
            return await self._register(url, profile, email)
        except httpx.HTTPError as exc:
            return {"success": False, "error": f"http error: {exc}"}
        except (OSError, ValueError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - contract: register never raises
            return {"success": False, "error": f"signup failed: {exc}"}

    # -- implementation ------------------------------------------------------

    async def _register(self, url: str, profile: dict[str, Any], email: str) -> dict[str, Any]:
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(follow_redirects=True, timeout=30.0)
        try:
            page_resp = await client.get(url)
            page_resp.raise_for_status()
            html = page_resp.text

            form = detect_signup_form(html, str(page_resp.url))
            if form is None:
                return {
                    "success": False,
                    "error": "no signup form detected on page",
                    "url": url,
                }

            password = generate_password()
            values = self._build_form_values(form, profile, email, password)
            values.update(await self._solve_captcha(html, str(page_resp.url)))

            if form.method.lower() == "get":
                submit_resp = await client.get(form.action, params=values)
            else:
                submit_resp = await client.post(form.action, data=values)

            verification = await verify_email(email, client=client)

            confirmed = False
            confirm_url = verification.get("link")
            if verification.get("verified") and confirm_url:
                try:
                    confirm_resp = await follow_verification_link(client, str(confirm_url))
                    confirmed = confirm_resp.status_code < 400
                except httpx.HTTPError:
                    confirmed = False

            return {
                "success": True,
                "url": url,
                "status": submit_resp.status_code,
                "submitted": True,
                "form": form.to_dict(),
                "email": email,
                "generated_password": password,
                "verification": verification,
                "confirmed": confirmed,
                "session_cookies": self._cookies_to_dict(client),
            }
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _cookies_to_dict(client: httpx.AsyncClient) -> dict[str, str]:
        try:
            return dict(client.cookies)
        except Exception:  # noqa: BLE001 - cookie extraction is best-effort
            return {}

    @staticmethod
    def _detect_captcha(html: str) -> tuple[str | None, str | None]:
        """Best-effort CAPTCHA type + sitekey detection from page HTML."""
        lowered = html.lower()
        match = _CAPTCHA_SITEKEY_RE.search(html)
        sitekey = match.group(1) if match else None
        if "h-captcha" in lowered or "hcaptcha" in lowered:
            return "hcaptcha", sitekey
        if "cf-turnstile" in lowered or "turnstile" in lowered:
            return "turnstile", sitekey
        if "g-recaptcha" in lowered or "recaptcha" in lowered:
            return "recaptcha_v2", sitekey
        return None, sitekey

    async def _solve_captcha(self, html: str, page_url: str | None = None) -> dict[str, str]:
        """Best-effort CAPTCHA solving via the optional ``captcha_solver``.

        Supports both the repo's async solver
        (``solve_captcha(captcha_type, sitekey=..., url=...)``) and a plain
        ``solve_captcha(html)`` callable. Never raises; returns an empty dict
        when no CAPTCHA is detected or solving fails.
        """
        if solve_captcha is None or not _page_has_captcha(html):
            return {}
        captcha_type, sitekey = self._detect_captcha(html)
        result: Any = None
        try:
            params = inspect.signature(solve_captcha).parameters
            if "captcha_type" in params:
                result = await solve_captcha(
                    captcha_type or "recaptcha_v2",
                    sitekey=sitekey,
                    url=page_url,
                )
            else:
                candidate: Any = solve_captcha(html)
                if inspect.iscoroutine(candidate):
                    result = await candidate
                else:
                    result = candidate
        except Exception:  # noqa: BLE001 - CAPTCHA solving is best-effort
            return {}
        if not result:
            return {}
        return {"g-recaptcha-response": str(result), "h-captcha-response": str(result)}

    @classmethod
    def _build_form_values(
        cls, form: SignupForm, profile: dict[str, Any], email: str, password: str
    ) -> dict[str, str]:
        """Map classified fields to values for form submission."""
        values: dict[str, str] = {}
        for field in form.fields:
            if not field.name:
                continue
            value = cls._value_for_field(field, profile, email, password)
            if value is not None:
                values[field.name] = value
        return values

    @staticmethod
    def _value_for_field(
        field: SignupField, profile: dict[str, Any], email: str, password: str
    ) -> str | None:
        role = field.role
        if role == "email":
            return email
        if role == "password":
            return password
        if role == "confirm_password":
            return password
        if role == "username":
            return str(profile.get("username") or email.split("@")[0])
        if role == "full_name":
            return str(
                profile.get("full_name") or profile.get("fullname") or profile.get("name") or ""
            )
        if role == "submit":
            # Include the submit button's value like a browser would.
            return field.value
        if role == "hidden":
            return field.value or ""
        if role == "checkbox":
            # Only check consent boxes when explicitly requested in the profile.
            return "on" if profile.get(field.name) or profile.get("consent") else None
        if role == "text":
            return str(profile.get(field.name) or profile.get(role) or "")
        if role == "select":
            # Do not guess at select options; only fill when explicitly provided.
            value = profile.get(field.name)
            return str(value) if value is not None else None
        if role == "textarea":
            return str(profile.get(field.name) or "")
        # captcha / radio / other — left untouched.
        return None
