# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""BYOK token gate for mail providers — Pry holds no mail credentials."""

from typing import Any

#: BYOK: the caller supplies their own OAuth2 token. Pry never holds a Gmail or
#: Microsoft credential, stores no refresh token, and has no service account. An
#: empty token is rejected here rather than sent, because Gmail and Graph answer
#: a blank bearer with an opaque 401 that reads like an auth failure rather than
#: the caller bug it is.
_NO_TOKEN = (
    "BYOK: pass your own OAuth2 access token. "  # noqa: S105 - a help message, not a secret
    "Gmail needs https://www.googleapis.com/auth/gmail.readonly; "
    "Outlook needs https://graph.microsoft.com/Mail.Read. "
    "Pry holds no mail credentials."
)


def require_token(access_token: str, provider: str) -> dict[str, Any] | None:
    """Return an error payload when the BYOK token is missing, else None."""
    if not access_token or not access_token.strip():
        return {"success": False, "error": f"{provider}: {_NO_TOKEN}", "code": "missing_token"}
    return None
