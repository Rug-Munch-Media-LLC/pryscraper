"""Stable facade for signup email verification."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import imaplib

from pry.commerce.signup.email_verification.common import (
    _CODE_PATTERNS,
    _CONFIRM_WORDS,
    _LINK_RE,
    _TRAILING_PUNCTUATION,
    IMAPConfig,
    _clean_link,
    _link_score,
    extract_verification_link,
    imap_config_from_env,
)
from pry.commerce.signup.email_verification.imap import (
    _try_logout,
    _walk_message_bodies,
    poll_imap_for_verification,
)
from pry.commerce.signup.email_verification.orchestration import (
    _verify_via_imap,
    follow_verification_link,
    verify_email,
)
from pry.commerce.signup.email_verification.temp_mail import (
    _TEMP_MAIL_DOMAINS,
    _looks_like_temp_mail,
    _mail_tm_api_base,
    _mail_tm_create_account,
    _mail_tm_token,
    fetch_temp_mail,
)

__all__ = [
    "_CODE_PATTERNS",
    "_CONFIRM_WORDS",
    "_LINK_RE",
    "_TEMP_MAIL_DOMAINS",
    "_TRAILING_PUNCTUATION",
    "IMAPConfig",
    "_clean_link",
    "_link_score",
    "_looks_like_temp_mail",
    "_mail_tm_api_base",
    "_mail_tm_create_account",
    "_mail_tm_token",
    "_try_logout",
    "_verify_via_imap",
    "_walk_message_bodies",
    "extract_verification_link",
    "fetch_temp_mail",
    "follow_verification_link",
    "imap_config_from_env",
    "imaplib",
    "poll_imap_for_verification",
    "verify_email",
]
