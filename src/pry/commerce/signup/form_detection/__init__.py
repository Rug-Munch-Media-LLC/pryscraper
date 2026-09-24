"""Signup form detection — public API.

Finds a site's signup form from its HTML and reports it as
:class:`SignupForm`. Importing from here keeps every caller unchanged:

    from pry.commerce.signup.form_detection import detect_signup_form

Implementation is split by concern: :mod:`roles` classifies controls,
:mod:`parser` builds the control tree, :mod:`fields` assembles the form,
and :mod:`models` holds the returned types.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from .fields import _build_form
from .models import SignupField, SignupForm
from .parser import _RawControl, _RawForm, _SignupFormParser
from .roles import classify_role


def detect_signup_form(html: str, url: str | None = None) -> SignupForm | None:
    """Detect the best signup form in an HTML document.

    Args:
        html: The raw HTML of the page.
        url: The page URL, used to resolve relative form actions.

    Returns:
        The highest-scoring :class:`SignupForm` that qualifies as a signup
        form, or ``None`` if no registration form is found.
    """
    parser = _SignupFormParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML must never crash detection
        return None

    forms = [_build_form(raw, index, url) for index, raw in enumerate(parser.forms)]
    candidates = [form for form in forms if form is not None and form.is_signup()]
    if not candidates:
        return None
    return max(candidates, key=lambda form: form.score())


# Backwards-compatible aliases for the former private names.
RawControl = _RawControl
RawForm = _RawForm
SignupFormParser = _SignupFormParser

__all__ = ["SignupField", "SignupForm", "classify_role", "detect_signup_form"]
