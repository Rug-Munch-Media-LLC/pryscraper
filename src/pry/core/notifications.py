"""Pry — Customer notification service.

Email alerts for usage limits, payments, subscriptions, and low balances.
Fire-and-forget: sending never blocks the API response. Uses an in-memory
queue for pending notifications (production would use Celery/Redis).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import logging
import smtplib
import time
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)

# In-memory queue of pending notifications: list of dicts with user_id,
# notification_type, created_at, and payload. Production would use Celery/Redis.
_pending: list[dict[str, Any]] = []

# User notification preferences: user_id -> {type: enabled}
_preferences: dict[str, dict[str, bool]] = {}

# Rate-limit dedup: (user_id, notification_type) -> last sent timestamp
_last_sent: dict[tuple[str, str], float] = {}

# Minimum seconds between repeated notifications of the same type per user.
_DEDUP_WINDOW = 3600.0


def _queue(user_id: str, notification_type: str, payload: dict[str, Any]) -> None:
    """Record a notification in the in-memory pending queue."""
    _pending.append(
        {
            "user_id": user_id,
            "notification_type": notification_type,
            "created_at": time.time(),
            "payload": payload,
        }
    )


def _send_email_sync(user_email: str, subject: str, body: str) -> bool:
    """Blocking email send. Tries SMTP via settings, falls back to sendmail."""
    try:
        from pry.core.settings import get_settings

        settings = get_settings()
        host = getattr(settings, "smtp_host", None)
        if host:
            msg = EmailMessage()
            msg["From"] = getattr(settings, "smtp_from", "noreply@pry.local")
            msg["To"] = user_email
            msg["Subject"] = subject
            msg.set_content(body)
            port = getattr(settings, "smtp_port", 587)
            user = getattr(settings, "smtp_user", None)
            password = getattr(settings, "smtp_password", None)
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                if port == 587:
                    smtp.starttls()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
            return True
    except Exception:
        logger.debug("SMTP send failed for %s, trying sendmail", user_email, exc_info=True)

    # Fallback: local sendmail
    try:
        import subprocess

        proc = subprocess.run(
            ["/usr/sbin/sendmail", "-t", "-oi"],
            input=f"To: {user_email}\nSubject: {subject}\n\n{body}\n",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        logger.warning("sendmail fallback failed for %s", user_email, exc_info=True)
        return False


async def send_notification(
    user_email: str,
    subject: str,
    body: str,
    notification_type: str = "info",
) -> bool:
    """Send an email notification. Fire-and-forget: never blocks the caller.

    Returns True on success.
    """
    try:
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, _send_email_sync, user_email, subject, body)
    except RuntimeError:
        ok = _send_email_sync(user_email, subject, body)
    if not ok:
        logger.warning("Notification send failed: type=%s to=%s", notification_type, user_email)
    return ok


async def notify_usage_limit(user_email: str, usage_pct: int, tier: str) -> bool:
    """Alert when usage hits 80%/90%/100% of quota."""
    if usage_pct not in (80, 90, 100):
        return False
    subject = f"[Pry] {tier} plan usage at {usage_pct}%"
    body = f"You've used {usage_pct}% of your {tier} plan quota."
    return await send_notification(user_email, subject, body, "usage_limit")


async def notify_payment_received(user_email: str, amount: float, chain: str, tx_hash: str) -> bool:
    """Payment confirmation email."""
    subject = f"[Pry] Payment received: ${amount:.2f} on {chain}"
    body = f"Payment of ${amount} received on {chain}. TX: {tx_hash}"
    return await send_notification(user_email, subject, body, "payment_received")


async def notify_subscription_expiring(user_email: str, tier: str, days_remaining: int) -> bool:
    """Subscription expiring soon email."""
    subject = f"[Pry] Your {tier} subscription expires in {days_remaining} days"
    body = f"Your {tier} subscription expires in {days_remaining} days."
    return await send_notification(user_email, subject, body, "subscription_expiring")


async def notify_low_balance(user_email: str, balance: float, estimated_days: int) -> bool:
    """Low x402 balance email."""
    subject = f"[Pry] Low x402 balance: ${balance:.2f}"
    body = f"Your x402 balance is ${balance}. Estimated {estimated_days} days remaining."
    return await send_notification(user_email, subject, body, "low_balance")


async def notify_subscription_cancelled(user_email: str, tier: str, access_until: str) -> bool:
    """Cancellation confirmation email."""
    subject = f"[Pry] {tier} subscription cancelled"
    body = f"Your {tier} subscription has been cancelled. You retain access until {access_until}."
    return await send_notification(user_email, subject, body, "subscription_cancelled")


async def notify_actor_complete(
    user_email: str, actor_name: str, status: str, results_url: str
) -> bool:
    """Actor run completed email."""
    subject = f"[Pry] Actor '{actor_name}' run {status}"
    body = f"Actor '{actor_name}' finished with status '{status}'. Results: {results_url}"
    return await send_notification(user_email, subject, body, "actor_complete")


class NotificationManager:
    """Manages notification preferences and batching."""

    def should_notify(self, user_id: str, notification_type: str) -> bool:
        """Check user preferences and dedup window for a notification type."""
        prefs = _preferences.get(user_id, {})
        if not prefs.get(notification_type, True):
            return False
        key = (user_id, notification_type)
        last = _last_sent.get(key)
        return not (last is not None and time.time() - last < _DEDUP_WINDOW)

    def mark_sent(self, user_id: str, notification_type: str) -> None:
        """Record that a notification was sent (updates dedup window)."""
        _last_sent[(user_id, notification_type)] = time.time()

    def set_preference(self, user_id: str, notification_type: str, enabled: bool) -> None:
        """Enable or disable a notification type for a user."""
        _preferences.setdefault(user_id, {})[notification_type] = enabled

    def batch_notifications(self, user_id: str) -> list[dict[str, Any]]:
        """Group pending notifications for a user, oldest first."""
        batch = [n for n in _pending if n["user_id"] == user_id]
        batch.sort(key=lambda n: n["created_at"])
        return batch

    def clear_batch(self, user_id: str) -> int:
        """Remove a user's pending notifications from the queue. Returns count."""
        global _pending
        before = len(_pending)
        _pending = [n for n in _pending if n["user_id"] != user_id]
        return before - len(_pending)
