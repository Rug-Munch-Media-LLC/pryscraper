"""Pry — One-Click Business Integrations.
Native write destinations: Google Sheets, Slack, Airtable, email."""

# Licensed under MIT. See LICENSE.
import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from pry.api.client import get_client
from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import validate_url

logger = logging.getLogger(__name__)
# ── Slack ──


async def write_to_slack(
    webhook_url: str,
    message: str,
    title: str = "Pry Data",
    color: str = "#36a64f",
) -> dict[str, Any]:
    """Send data to a Slack webhook as a formatted message."""
    if not webhook_url:
        return {"success": False, "error": "Slack webhook URL is required"}
    # Caller-supplied destination: never POST to loopback/metadata/internal.
    try:
        validate_url(webhook_url)
    except InvalidRequestError as exc:
        logger.warning(
            "destination_url_rejected", extra={"destination": "slack", "reason": str(exc)}
        )
        return {"success": False, "error": f"Slack webhook URL rejected: {exc}"}

    # Truncate message if too long (Slack limit: 40000 chars)
    if len(message) > 35000:
        message = message[:35000] + "\n\n*(truncated — data too large for Slack)*"

    payload = {
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": message,
                "footer": "Pry — Web Intelligence",
                "ts": datetime.now(UTC).timestamp(),
            }
        ]
    }

    try:
        client = await get_client()
        resp = await client.post(webhook_url, json=payload, timeout=15)
        if resp.status_code >= 400:
            error_body = resp.text[:200]
            logger.error(
                "slack_write_failed",
                extra={"status": resp.status_code, "error": error_body},
            )
            return {"success": False, "error": f"Slack returned {resp.status_code}: {error_body}"}
        return {"success": True, "destination": "slack"}
    except httpx.InvalidURL:
        logger.warning("destinations_suppressed", exc_info=True)
        return {"success": False, "error": "Invalid Slack webhook URL"}
    except httpx.RequestError as e:
        logger.warning("destinations_suppressed", exc_info=True)
        return {"success": False, "error": f"Slack request failed: {str(e)[:200]}"}


async def write_to_slack_csv(
    webhook_url: str,
    csv_data: str,
    title: str = "Pry Data Export",
) -> dict[str, Any]:
    """Send CSV data to Slack as a formatted code block."""
    if len(csv_data) > 35000:
        csv_data = csv_data[:35000] + "\n...(truncated)"

    message = f"```\n{csv_data}\n```"
    return await write_to_slack(webhook_url, message, title=title)


# ── Google Sheets (via public API — requires service account) ──


async def write_to_googlesheets(
    spreadsheet_id: str,
    range_name: str,
    values: list[list[Any]],
    credentials_json: str | None = None,
) -> dict[str, Any]:
    """Write data to Google Sheets using the Sheets API.

    Requires a service account credentials JSON string.
    Falls back to a public CSV-export approach if no credentials.
    """
    if credentials_json:
        return await _write_to_sheets_api(spreadsheet_id, range_name, values, credentials_json)

    # Without credentials, generate a shareable CSV link
    csv_lines = "\n".join([",".join(str(c) for c in row) for row in values])
    data_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    return {
        "success": True,
        "destination": "googlesheets",
        "note": "Credentials required for automatic write. CSV preview available.",
        "csv_preview": csv_lines[:500],
        "manual_url": data_url,
    }


async def _write_to_sheets_api(
    spreadsheet_id: str,
    range_name: str,
    values: list[list[Any]],
    credentials_json: str,
) -> dict[str, Any]:
    """Write to Google Sheets using the Sheets API v4."""
    try:
        creds = json.loads(credentials_json)
        access_token = creds.get("access_token") or creds.get("token") or ""
        if not access_token:
            return {"success": False, "error": "No access_token found in credentials"}

        client = await get_client()

        body = {"values": values, "majorDimension": "ROWS"}
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{quote(range_name)}?valueInputOption=USER_ENTERED"

        resp = await client.put(
            url,
            json=body,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        if resp.status_code < 400:
            return {
                "success": True,
                "destination": "googlesheets",
                "updated_cells": len(values) * len(values[0]) if values else 0,
            }
        return {
            "success": False,
            "error": f"Sheets API error: {resp.status_code} {resp.text[:200]}",
        }

    except json.JSONDecodeError:
        logger.warning("destinations_suppressed", exc_info=True)
        return {"success": False, "error": "Invalid credentials JSON"}
    except ValueError as e:
        logger.warning("destinations_suppressed", exc_info=True)
        return {"success": False, "error": str(e)[:200]}


# ── Airtable ──


async def write_to_airtable(
    base_id: str,
    table_name: str,
    records: list[dict[str, Any]],
    api_key: str = "",
) -> dict[str, Any]:
    """Write records to an Airtable base/table."""
    if not api_key:
        return {"success": False, "error": "Airtable API key required"}

    client = await get_client()

    # Airtable API accepts up to 10 records per request
    all_results: list[dict[str, Any]] = []
    batch_size = 10
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        payload = {"records": [{"fields": r} for r in batch]}

        try:
            resp = await client.post(
                f"https://api.airtable.com/v0/{base_id}/{quote(table_name)}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            if resp.status_code < 400:
                data = resp.json()
                created = data.get("records", [])
                all_results.append(
                    {
                        "batch": i // batch_size,
                        "created": len(created),
                        "success": True,
                    }
                )
            else:
                all_results.append(
                    {
                        "batch": i // batch_size,
                        "success": False,
                        "error": f"Airtable error {resp.status_code}: {resp.text[:200]}",
                    }
                )
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("destinations_suppressed", exc_info=True)
            all_results.append({"batch": i // batch_size, "success": False, "error": str(e)[:200]})

    total_created = sum(r.get("created", 0) for r in all_results if r.get("success"))
    return {
        "success": all(r["success"] for r in all_results),
        "destination": "airtable",
        "total_records": len(records),
        "successfully_written": total_created,
        "batches": all_results,
    }


# ── Email (SMTP) ──


async def write_to_email(
    recipient: str,
    subject: str,
    body: str,
    smtp_host: str = "",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_password: str = "",
    sender: str = "",
) -> dict[str, Any]:
    """Send data via email using SMTP.

    Falls back to generating a mailto: link if SMTP not configured.
    """
    if smtp_host and smtp_user and smtp_password:
        return await _send_smtp(
            recipient, subject, body, smtp_host, smtp_port, smtp_user, smtp_password, sender
        )

    # Generate mailto link as fallback
    body_short = body[:500].replace("\n", "%0A").replace(" ", "%20")
    mailto = f"mailto:{recipient}?subject={quote(subject)}&body={body_short}"
    return {
        "success": True,
        "destination": "email",
        "note": "SMTP not configured — mailto link generated",
        "mailto_link": mailto,
    }


async def _send_smtp(
    recipient: str,
    subject: str,
    body: str,
    host: str,
    port: int,
    user: str,
    password: str,
    sender: str,
) -> dict[str, Any]:
    """Send email via SMTP."""
    import smtplib
    from email.mime.text import MIMEText

    try:
        msg = MIMEText(body, "plain" if not body.startswith("<") else "html")
        msg["Subject"] = subject
        msg["From"] = sender or user
        msg["To"] = recipient

        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)

        return {"success": True, "destination": "email"}
    except Exception as e:
        logger.warning("destinations_suppressed", exc_info=True)
        return {"success": False, "error": f"SMTP error: {str(e)[:200]}"}


# ── Generic dispatch ──

DESTINATIONS: dict[str, Any] = {
    "slack": write_to_slack,
    "googlesheets": write_to_googlesheets,
    "airtable": write_to_airtable,
    "email": write_to_email,
}

SUPPORTED_DESTINATIONS = list(DESTINATIONS.keys())


async def dispatch(
    destination: str,
    data: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch data to a configured destination.

    Args:
        destination: One of: slack, googlesheets, airtable, email
        data: Data to send (will be formatted for the destination)
        config: Destination-specific config (webhook_url, api_key, etc.)
    """
    handler = DESTINATIONS.get(destination)
    if not handler:
        return {
            "success": False,
            "error": f"Unknown destination: {destination}. Supported: {SUPPORTED_DESTINATIONS}",
        }

    # Format data for destination
    if destination == "slack":
        message = json.dumps(data, indent=2, default=str)
        return await handler(  # type: ignore[no-any-return]
            webhook_url=config.get("webhook_url", ""),
            message=message,
            title=config.get("title", "Pry Data"),
        )

    if destination == "googlesheets":
        rows = _data_to_rows(data)
        return await handler(  # type: ignore[no-any-return]
            spreadsheet_id=config.get("spreadsheet_id", ""),
            range_name=config.get("range", "Sheet1!A1"),
            values=rows,
            credentials_json=config.get("credentials_json"),
        )

    if destination == "airtable":
        records = data if isinstance(data, list) else [data]
        return await handler(  # type: ignore[no-any-return]
            base_id=config.get("base_id", ""),
            table_name=config.get("table_name", "Table 1"),
            records=records,
            api_key=config.get("api_key", ""),
        )

    if destination == "email":
        body = json.dumps(data, indent=2, default=str)
        return await handler(  # type: ignore[no-any-return]
            recipient=config.get("recipient", ""),
            subject=config.get("subject", "Pry Data Export"),
            body=body,
            smtp_host=config.get("smtp_host", ""),
            smtp_port=config.get("smtp_port", 587),
            smtp_user=config.get("smtp_user", ""),
            smtp_password=config.get("smtp_password", ""),
            sender=config.get("sender", ""),
        )

    return {"success": False, "error": f"Unhandled destination: {destination}"}


def _data_to_rows(data: dict[str, Any] | list[Any]) -> list[list[Any]]:
    """Convert extracted data to spreadsheet rows (header row + data rows)."""
    if isinstance(data, list):
        if not data:
            return [["No data"]]
        if isinstance(data[0], dict):
            headers = list(data[0].keys())
            rows = [[str(v) for v in r.values()] for r in data]
            return [headers, *rows]
        return [[str(item) for item in data]]

    if isinstance(data, dict):
        headers = list(data.keys())
        values = [str(v) for v in data.values()]
        return [headers, values]

    return [["value"], [str(data)]]
