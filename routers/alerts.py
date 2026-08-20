"""Pry — Alerts router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Alerts"])


@router.post("/v1/alert/send", tags=["Alerts"], summary="Send an alert to any channel")
async def send_alert_endpoint(
    channel: str = Body(...),
    title: str = Body("Pry Alert"),
    message: str = Body(...),
    config: dict[str, Any] = Body(...),
    severity: str = Body("info"),
) -> dict[str, Any]:
    """Send an alert to Slack, Discord, Teams, Telegram, SMS, or Email.

    Config varies by channel:
    - slack: {"webhook_url": "..."}
    - discord: {"webhook_url": "..."}
    - teams: {"webhook_url": "..."}
    - telegram: {"bot_token": "...", "chat_id": "..."}
    - sms: {"phone": "+1234567890", "twilio_sid": "...", "twilio_token": "...", "twilio_from": "..."}
    - email: {"recipient": "user@example.com", "smtp_host": "...", "smtp_user": "..."}
    """
    from alerter import send_alert

    result = await send_alert(channel, title, message, config, severity)
    return {"success": result["success"], "data": result}


@router.get("/v1/alert/channels", tags=["Alerts"], summary="List supported alert channels")
async def list_channels() -> dict[str, Any]:
    """List all supported alert channels and their config requirements."""
    return {
        "success": True,
        "data": {
            "channels": [
                {"id": "slack", "name": "Slack", "config_fields": ["webhook_url"]},
                {"id": "discord", "name": "Discord", "config_fields": ["webhook_url"]},
                {"id": "teams", "name": "Microsoft Teams", "config_fields": ["webhook_url"]},
                {"id": "telegram", "name": "Telegram", "config_fields": ["bot_token", "chat_id"]},
                {
                    "id": "sms",
                    "name": "SMS (Twilio)",
                    "config_fields": ["phone", "twilio_sid", "twilio_token", "twilio_from"],
                },
                {
                    "id": "email",
                    "name": "Email",
                    "config_fields": ["recipient", "smtp_host", "smtp_user"],
                },
            ]
        },
    }
