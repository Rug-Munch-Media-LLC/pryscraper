# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Signup-email verification gate for hosting invoices (audit item #4)."""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from pry.core.db import models as _models
from pry.core.db.session import session_scope

logger = logging.getLogger("pry.commerce.hosting")

ENV_HOSTING_SKIP_EMAIL_VERIFY: str = "PRY_HOSTING_SKIP_EMAIL_VERIFY"
#: Wrong-code attempts allowed before the invoice is locked for verification.
MAX_VERIFICATION_ATTEMPTS: int = 5


def _email_gate_enabled() -> bool:
    """True unless the test escape hatch disables the email gate.

    ``PRY_HOSTING_SKIP_EMAIL_VERIFY=1`` lets existing test flows confirm
    without verifying the email first (set in the hosting test fixtures).
    """
    return os.environ.get(ENV_HOSTING_SKIP_EMAIL_VERIFY, "") != "1"


def verify_hosting_email(invoice_id: str, code: str) -> dict[str, Any]:
    """Verify the signup email for *invoice_id* with *code*.

    Matches the stored verification code (constant-time compare) and marks
    the invoice ``email_verified``. Raises ``ValueError`` for unknown
    invoices; returns ``{"verified": bool}`` (False on a wrong code).
    """
    if not code or not code.strip():
        return {"verified": False, "reason": "verification code is required"}
    with session_scope() as session:
        row = session.query(_models.HostingInvoice).filter_by(invoice_id=invoice_id).first()
        if row is None:
            raise ValueError(f"unknown hosting invoice {invoice_id!r}")
        if row.email_verified:
            return {"verified": True, "invoice_id": invoice_id}

        stored = str(row.verification_code or "")
        # Fail closed on an empty stored code: ``compare_digest("", "")`` is
        # True, so an invoice with no persisted code would otherwise verify
        # with an empty payload (the mail-configured signup bug).
        if not stored:
            logger.warning("hosting_email_no_stored_code", extra={"invoice_id": invoice_id})
            return {"verified": False, "reason": "no verification code on record"}

        attempts = int(row.verification_attempts or 0)
        if attempts >= MAX_VERIFICATION_ATTEMPTS:
            logger.warning("hosting_email_locked", extra={"invoice_id": invoice_id})
            return {
                "verified": False,
                "reason": "too many invalid attempts — verification locked",
                "locked": True,
            }

        if not secrets.compare_digest(stored, code.strip()):
            attempts += 1
            row.verification_attempts = attempts
            if attempts >= MAX_VERIFICATION_ATTEMPTS:
                logger.warning("hosting_email_locked", extra={"invoice_id": invoice_id})
                return {
                    "verified": False,
                    "reason": "too many invalid attempts — verification locked",
                    "locked": True,
                }
            return {
                "verified": False,
                "reason": "invalid verification code",
                "attempts_remaining": MAX_VERIFICATION_ATTEMPTS - attempts,
            }
        row.email_verified = True
    logger.info("hosting_email_verified", extra={"invoice_id": invoice_id})
    return {"verified": True, "invoice_id": invoice_id}
