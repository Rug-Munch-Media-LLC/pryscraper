# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for multi-channel alerting."""

from pry.actors.alerter import (
    _send_discord,
    _send_slack,
    _send_teams,
    _send_telegram,
    send_alert,
)


def test_send_alert_unknown_channel() -> None:
    import asyncio

    result = asyncio.run(send_alert("unknown", "Test", "Message", {}))
    assert result["success"] is False
    assert "unknown" in result["error"]


def test_send_slack_no_webhook() -> None:
    import asyncio

    result = asyncio.run(_send_slack("Test", "Message", {}, "info"))
    assert result["success"] is False


def test_send_discord_no_webhook() -> None:
    import asyncio

    result = asyncio.run(_send_discord("Test", "Message", {}, "info"))
    assert result["success"] is False


def test_send_teams_no_webhook() -> None:
    import asyncio

    result = asyncio.run(_send_teams("Test", "Message", {}, "info"))
    assert result["success"] is False


def test_send_telegram_no_creds() -> None:
    import asyncio

    result = asyncio.run(_send_telegram("Test", "Message", {}, "info"))
    assert result["success"] is False
    assert "bot_token" in result["error"]
