"""Pry signup automation package.

Public surface:

- :class:`SignupAutomation` — the registration engine.
- :class:`SignupForm` / :class:`SignupField` — detected form structure.
- :func:`detect_signup_form` — HTML → SignupForm detection.
- :func:`verify_email` — IMAP / temp-mail verification polling.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from pry.commerce.signup.engine import SignupAutomation, generate_password
from pry.commerce.signup.form_detection import SignupField, SignupForm, detect_signup_form

__all__ = [
    "SignupAutomation",
    "SignupField",
    "SignupForm",
    "detect_signup_form",
    "generate_password",
]
