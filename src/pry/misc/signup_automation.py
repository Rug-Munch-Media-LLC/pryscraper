"""Pry — signup automation facade.

Thin re-export of the signup engine's public API so existing import styles
(``from signup_automation import SignupAutomation``) keep working.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from signup.engine import SignupAutomation, generate_password
from signup.form_detection import SignupField, SignupForm, detect_signup_form

__all__ = [
    "SignupAutomation",
    "SignupField",
    "SignupForm",
    "detect_signup_form",
    "generate_password",
]
