# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for pry.core.notifications — SMTP/sendmail delivery, notify_* helpers,
and NotificationManager preferences/dedup/batching. All I/O mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pry.core import notifications as notif


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    notif._pending.clear()
    notif._preferences.clear()
    notif._last_sent.clear()
    yield
    notif._pending.clear()
    notif._preferences.clear()
    notif._last_sent.clear()


class TestSendEmailSync:
    def test_smtp_path_success(self) -> None:
        settings = MagicMock(
            smtp_host="smtp.example.com",
            smtp_from="noreply@pry.local",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
        )
        smtp_instance = MagicMock()
        smtp_cm = MagicMock()
        smtp_cm.__enter__.return_value = smtp_instance
        with (
            patch("pry.core.settings.get_settings", return_value=settings),
            patch("smtplib.SMTP", return_value=smtp_cm) as smtp_cls,
        ):
            ok = notif._send_email_sync("a@b.com", "Subj", "Body")
        assert ok is True
        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=10)
        smtp_instance.starttls.assert_called_once()
        smtp_instance.login.assert_called_once_with("user", "pass")
        smtp_instance.send_message.assert_called_once()

    def test_smtp_port_465_skips_starttls(self) -> None:
        settings = MagicMock(
            smtp_host="smtp.example.com",
            smtp_from="noreply@pry.local",
            smtp_port=465,
            smtp_user=None,
            smtp_password=None,
        )
        smtp_instance = MagicMock()
        smtp_cm = MagicMock()
        smtp_cm.__enter__.return_value = smtp_instance
        with (
            patch("pry.core.settings.get_settings", return_value=settings),
            patch("smtplib.SMTP", return_value=smtp_cm),
        ):
            ok = notif._send_email_sync("a@b.com", "Subj", "Body")
        assert ok is True
        smtp_instance.starttls.assert_not_called()
        smtp_instance.login.assert_not_called()

    def test_no_smtp_host_falls_back_to_sendmail(self) -> None:
        settings = MagicMock(smtp_host=None)
        proc = MagicMock(returncode=0)
        with (
            patch("pry.core.settings.get_settings", return_value=settings),
            patch("subprocess.run", return_value=proc) as run,
        ):
            ok = notif._send_email_sync("a@b.com", "Subj", "Body")
        assert ok is True
        run.assert_called_once()
        assert run.call_args.args[0] == ["/usr/sbin/sendmail", "-t", "-oi"]

    def test_smtp_exception_falls_back_to_sendmail(self) -> None:
        settings = MagicMock(smtp_host="smtp.example.com")
        proc = MagicMock(returncode=0)
        with (
            patch("pry.core.settings.get_settings", return_value=settings),
            patch("smtplib.SMTP", side_effect=OSError("refused")),
            patch("subprocess.run", return_value=proc),
        ):
            ok = notif._send_email_sync("a@b.com", "Subj", "Body")
        assert ok is True

    def test_sendmail_nonzero_returncode_is_failure(self) -> None:
        settings = MagicMock(smtp_host=None)
        proc = MagicMock(returncode=1)
        with (
            patch("pry.core.settings.get_settings", return_value=settings),
            patch("subprocess.run", return_value=proc),
        ):
            ok = notif._send_email_sync("a@b.com", "Subj", "Body")
        assert ok is False

    def test_sendmail_exception_returns_false(self) -> None:
        settings = MagicMock(smtp_host=None)
        with (
            patch("pry.core.settings.get_settings", return_value=settings),
            patch("subprocess.run", side_effect=FileNotFoundError("no sendmail")),
        ):
            ok = notif._send_email_sync("a@b.com", "Subj", "Body")
        assert ok is False


class TestSendNotification:
    @pytest.mark.asyncio
    async def test_success_returns_true(self) -> None:
        with patch.object(notif, "_send_email_sync", return_value=True) as send:
            ok = await notif.send_notification("a@b.com", "S", "B", "info")
        assert ok is True
        send.assert_called_once_with("a@b.com", "S", "B")

    @pytest.mark.asyncio
    async def test_failure_returns_false(self) -> None:
        with patch.object(notif, "_send_email_sync", return_value=False):
            ok = await notif.send_notification("a@b.com", "S", "B")
        assert ok is False


class TestNotifyHelpers:
    @pytest.mark.asyncio
    async def test_usage_limit_valid_pct(self) -> None:
        with patch.object(notif, "send_notification", return_value=True) as send:
            ok = await notif.notify_usage_limit("a@b.com", 80, "pro")
        assert ok is True
        send.assert_called_once_with(
            "a@b.com",
            "[Pry] pro plan usage at 80%",
            "You've used 80% of your pro plan quota.",
            "usage_limit",
        )

    @pytest.mark.asyncio
    async def test_usage_limit_invalid_pct_short_circuits(self) -> None:
        with patch.object(notif, "send_notification", return_value=True) as send:
            ok = await notif.notify_usage_limit("a@b.com", 50, "pro")
        assert ok is False
        send.assert_not_called()

    @pytest.mark.asyncio
    async def test_payment_received(self) -> None:
        with patch.object(notif, "send_notification", return_value=True) as send:
            await notif.notify_payment_received("a@b.com", 12.5, "base", "0xabc")
        send.assert_called_once_with(
            "a@b.com",
            "[Pry] Payment received: $12.50 on base",
            "Payment of $12.5 received on base. TX: 0xabc",
            "payment_received",
        )

    @pytest.mark.asyncio
    async def test_subscription_expiring(self) -> None:
        with patch.object(notif, "send_notification", return_value=True) as send:
            await notif.notify_subscription_expiring("a@b.com", "pro", 3)
        send.assert_called_once_with(
            "a@b.com",
            "[Pry] Your pro subscription expires in 3 days",
            "Your pro subscription expires in 3 days.",
            "subscription_expiring",
        )

    @pytest.mark.asyncio
    async def test_low_balance(self) -> None:
        with patch.object(notif, "send_notification", return_value=True) as send:
            await notif.notify_low_balance("a@b.com", 1.5, 2)
        send.assert_called_once_with(
            "a@b.com",
            "[Pry] Low x402 balance: $1.50",
            "Your x402 balance is $1.5. Estimated 2 days remaining.",
            "low_balance",
        )

    @pytest.mark.asyncio
    async def test_subscription_cancelled(self) -> None:
        with patch.object(notif, "send_notification", return_value=True) as send:
            await notif.notify_subscription_cancelled("a@b.com", "pro", "2026-12-31")
        send.assert_called_once_with(
            "a@b.com",
            "[Pry] pro subscription cancelled",
            "Your pro subscription has been cancelled. You retain access until 2026-12-31.",
            "subscription_cancelled",
        )

    @pytest.mark.asyncio
    async def test_actor_complete(self) -> None:
        with patch.object(notif, "send_notification", return_value=True) as send:
            await notif.notify_actor_complete("a@b.com", "scraper", "succeeded", "http://r")
        send.assert_called_once_with(
            "a@b.com",
            "[Pry] Actor 'scraper' run succeeded",
            "Actor 'scraper' finished with status 'succeeded'. Results: http://r",
            "actor_complete",
        )


class TestNotificationManager:
    def test_should_notify_default_true(self) -> None:
        mgr = notif.NotificationManager()
        assert mgr.should_notify("u1", "info") is True

    def test_should_notify_respects_disabled_pref(self) -> None:
        mgr = notif.NotificationManager()
        mgr.set_preference("u1", "info", False)
        assert mgr.should_notify("u1", "info") is False

    def test_should_notify_other_type_unaffected(self) -> None:
        mgr = notif.NotificationManager()
        mgr.set_preference("u1", "info", False)
        assert mgr.should_notify("u1", "payment_received") is True

    def test_dedup_window_blocks_repeat(self) -> None:
        mgr = notif.NotificationManager()
        mgr.mark_sent("u1", "info")
        assert mgr.should_notify("u1", "info") is False

    def test_dedup_window_expired_allows(self) -> None:
        mgr = notif.NotificationManager()
        notif._last_sent[("u1", "info")] = 0.0  # long ago
        assert mgr.should_notify("u1", "info") is True

    def test_dedup_is_per_user(self) -> None:
        mgr = notif.NotificationManager()
        mgr.mark_sent("u1", "info")
        assert mgr.should_notify("u2", "info") is True

    def test_batch_returns_only_user_oldest_first(self) -> None:
        mgr = notif.NotificationManager()
        notif._pending.extend(
            [
                {"user_id": "u1", "notification_type": "b", "created_at": 2.0, "payload": {}},
                {"user_id": "u2", "notification_type": "x", "created_at": 1.0, "payload": {}},
                {"user_id": "u1", "notification_type": "a", "created_at": 1.0, "payload": {}},
            ]
        )
        batch = mgr.batch_notifications("u1")
        assert [n["notification_type"] for n in batch] == ["a", "b"]

    def test_clear_batch_removes_and_counts(self) -> None:
        mgr = notif.NotificationManager()
        notif._pending.extend(
            [
                {"user_id": "u1", "notification_type": "a", "created_at": 1.0, "payload": {}},
                {"user_id": "u1", "notification_type": "b", "created_at": 2.0, "payload": {}},
                {"user_id": "u2", "notification_type": "c", "created_at": 3.0, "payload": {}},
            ]
        )
        removed = mgr.clear_batch("u1")
        assert removed == 2
        assert [n["user_id"] for n in notif._pending] == ["u2"]

    def test_clear_batch_unknown_user_returns_zero(self) -> None:
        mgr = notif.NotificationManager()
        assert mgr.clear_batch("nobody") == 0
