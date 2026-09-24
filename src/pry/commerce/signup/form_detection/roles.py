"""Signup form detection — deciding what an HTML control is for.

Assigns each control a role (email, password, captcha, …) from its type,
autocomplete attribute, tag name and nearby text, in that order of
reliability. Pure: no parsing, no models.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re

# Tags whose content is not user-visible form text.
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "head", "svg"})

# Controls that can appear inside a form.
_CONTROL_TAGS = frozenset({"input", "select", "textarea", "button"})

# Role constants — used for field classification and signup scoring.
ROLE_EMAIL = "email"
ROLE_PASSWORD = "password"  # noqa: S105 - role label, not a credential
ROLE_CONFIRM_PASSWORD = "confirm_password"  # noqa: S105 - role label, not a credential
ROLE_USERNAME = "username"
ROLE_FULL_NAME = "full_name"
ROLE_SUBMIT = "submit"
ROLE_HIDDEN = "hidden"
ROLE_CHECKBOX = "checkbox"
ROLE_RADIO = "radio"
ROLE_CAPTCHA = "captcha"
ROLE_SELECT = "select"
ROLE_TEXTAREA = "textarea"
ROLE_TEXT = "text"


def _normalize(value: str | None) -> str:
    """Lowercase and collapse separators for fuzzy matching."""
    return re.sub(r"[\s_-]+", " ", (value or "").lower()).strip()


def classify_role(
    *,
    name: str = "",
    control_id: str = "",
    field_type: str = "text",
    tag: str = "input",
    placeholder: str = "",
    aria_label: str = "",
    autocomplete: str = "",
    label: str = "",
) -> str:
    """Classify a form control into a semantic role.

    Order matters: explicit type hints (password/email/submit) win over
    autocomplete attributes, which win over name/id/label-text heuristics.
    """
    ctype = field_type.lower()
    tag = tag.lower()
    haystack = _normalize(
        " ".join([name, control_id, placeholder, aria_label, autocomplete, label])
    )

    role = _classify_by_type(ctype, tag, haystack)
    if role:
        return role
    role = _classify_by_autocomplete(autocomplete.lower())
    if role:
        return role
    role = _classify_by_tag(tag)
    if role:
        return role
    return _classify_by_text(haystack)


# ── Classification stages (extracted from classify_role — audit P2) ─────────


def _classify_by_type(ctype: str, tag: str, haystack: str) -> str | None:
    """Explicit control-type hints win over every other signal."""
    if ctype == "password":
        if any(word in haystack for word in ("confirm", "repeat", "again", "match")):
            return ROLE_CONFIRM_PASSWORD
        return ROLE_PASSWORD
    if ctype == "email":
        return ROLE_EMAIL
    if tag == "button" or ctype == "submit":
        return ROLE_SUBMIT
    if ctype == "hidden":
        return ROLE_HIDDEN
    if ctype == "checkbox":
        return ROLE_CHECKBOX
    if ctype == "radio":
        return ROLE_RADIO
    if ctype == "file":
        # File inputs are intentionally opaque: heuristics are skipped.
        return ROLE_TEXT
    return None


def _classify_by_autocomplete(ac: str) -> str | None:
    """Autocomplete attribute hints (standard values)."""
    if ac == "email":
        return ROLE_EMAIL
    if ac == "username":
        return ROLE_USERNAME
    if ac == "name":
        return ROLE_FULL_NAME
    if ac == "password":
        return ROLE_PASSWORD
    if ac == "new-password":
        return ROLE_PASSWORD
    return None


def _classify_by_tag(tag: str) -> str | None:
    """Bare element-type hints (select / textarea)."""
    if tag == "select":
        return ROLE_SELECT
    if tag == "textarea":
        return ROLE_TEXTAREA
    return None


def _classify_by_text(haystack: str) -> str:
    """Name/id/placeholder/label-text heuristics (last resort)."""
    if "email" in haystack or "mail" in haystack:
        return ROLE_EMAIL
    if "pass" in haystack or "pwd" in haystack:
        return ROLE_PASSWORD
    if (
        "username" in haystack
        or "screenname" in haystack
        or "screen name" in haystack
        or "handle" in haystack
        or "login" in haystack
        or "user" in haystack
    ):
        return ROLE_USERNAME
    if "fullname" in haystack or "full name" in haystack:
        return ROLE_FULL_NAME
    if (
        "name" in haystack
        and "first" not in haystack
        and "last" not in haystack
        and "company" not in haystack
        and "middle" not in haystack
    ):
        return ROLE_FULL_NAME
    if "captcha" in haystack or "recaptcha" in haystack:
        return ROLE_CAPTCHA
    return ROLE_TEXT


__all__ = ["classify_role"]
