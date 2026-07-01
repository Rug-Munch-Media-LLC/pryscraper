"""Pry — Multi-Channel Alerting System.
SMS, Email, Microsoft Teams, Discord, Telegram alerts."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def send_alert(
    channel: str,
    title: str,
    message: str,
    config: dict[str, Any],
    severity: str = "info",
) -> dict[str, Any]:
    """Send an alert to any supported channel.

    Channels: slack, email, discord, teams, telegram, sms
    """
    channel_map = {
        "slack": _send_slack,
        "email": _send_email,
        "discord": _send_discord,
        "teams": _send_teams,
        "telegram": _send_telegram,
        "sms": _send_sms,
    }
    handler = channel_map.get(channel)
    if not handler:
        return {"success": False, "error": f"Unknown channel: {channel}"}

    return await handler(title, message, config, severity)


async def _send_slack(
    title: str, message: str, config: dict[str, Any], severity: str
) -> dict[str, Any]:
    """Send alert to Slack via webhook."""
    from destinations import write_to_slack

    color_map = {"critical": "#dc2626", "error": "#f59e0b", "info": "#3b82f6"}
    full_msg = f"*[{severity.upper()}] {title}*\n{message}"
    return await write_to_slack(
        webhook_url=config.get("webhook_url", ""),
        message=full_msg,
        title=title,
        color=color_map.get(severity, "#36a64f"),
    )


async def _send_email(
    title: str, message: str, config: dict[str, Any], severity: str
) -> dict[str, Any]:
    """Send alert via email."""
    from destinations import write_to_email

    return await write_to_email(
        recipient=config.get("recipient", ""),
        subject=f"[{severity.upper()}] {title}",
        body=message,
        smtp_host=config.get("smtp_host", ""),
        smtp_port=config.get("smtp_port", 587),
        smtp_user=config.get("smtp_user", ""),
        smtp_password=config.get("smtp_password", ""),
        sender=config.get("sender", ""),
    )


async def _send_discord(
    title: str, message: str, config: dict[str, Any], severity: str
) -> dict[str, Any]:
    """Send alert to Discord via webhook."""
    from client import get_client

    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        return {"success": False, "error": "Discord webhook URL required"}

    color_map = {"critical": 0xDC2626, "error": 0xF59E0B, "info": 0x3B82F6}
    payload = {
        "embeds": [
            {
                "title": title,
                "description": message[:2000] if len(message) > 2000 else message,
                "color": color_map.get(severity, 0x36A64F),
                "footer": {"text": "Pry Alert System"},
                "timestamp": __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(),
            }
        ]
    }
    try:
        client = await get_client()
        resp = await client.post(webhook_url, json=payload, timeout=10)
        if resp.is_success:
            return {"success": True, "channel": "discord"}
        return {"success": False, "error": f"Discord returned {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def _send_teams(
    title: str, message: str, config: dict[str, Any], severity: str
) -> dict[str, Any]:
    """Send alert to Microsoft Teams via webhook."""
    from client import get_client

    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        return {"success": False, "error": "Teams webhook URL required"}

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": title,
        "title": f"[{severity.upper()}] {title}",
        "text": message[:5000] if len(message) > 5000 else message,
        "potentialAction": [],
    }
    try:
        client = await get_client()
        resp = await client.post(webhook_url, json=payload, timeout=10)
        if resp.is_success:
            return {"success": True, "channel": "teams"}
        return {"success": False, "error": f"Teams returned {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def _send_telegram(
    title: str, message: str, config: dict[str, Any], severity: str
) -> dict[str, Any]:
    """Send alert to Telegram via bot API."""
    from client import get_client

    bot_token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")
    if not bot_token or not chat_id:
        return {"success": False, "error": "Telegram bot_token and chat_id required"}

    text = f"*[{severity.upper()}] {title}*\n\n{message[:3000]}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        client = await get_client()
        resp = await client.post(
            url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10
        )
        if resp.is_success:
            return {"success": True, "channel": "telegram"}
        return {"success": False, "error": f"Telegram returned {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def _send_sms(
    title: str, message: str, config: dict[str, Any], severity: str
) -> dict[str, Any]:
    """Send SMS alert via Twilio or API."""
    provider = config.get("provider", "twilio")
    phone = config.get("phone", "")
    if not phone:
        return {"success": False, "error": "Phone number required for SMS"}

    if provider == "twilio":
        account_sid = config.get("twilio_sid", "")
        auth_token = config.get("twilio_token", "")
        from_number = config.get("twilio_from", "")
        if not all([account_sid, auth_token, from_number]):
            return {"success": False, "error": "Twilio credentials required"}
        text = f"[{severity.upper()}] {title}: {message[:500]}"
        try:
            from client import get_client

            cl = await get_client()
            resp = await cl.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                data={"To": phone, "From": from_number, "Body": text},
                auth=(account_sid, auth_token),
                timeout=10,
            )
            if resp.is_success:
                return {"success": True, "channel": "sms", "provider": "twilio"}
            return {"success": False, "error": f"Twilio error: {resp.text[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    return {"success": False, "error": f"SMS provider '{provider}' not supported"}
