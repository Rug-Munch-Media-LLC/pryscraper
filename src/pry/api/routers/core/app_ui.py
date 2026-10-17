"""Pry — server-rendered product UI (Phase 1): keys and usage.

One page per job, no JS framework, inline CSS (system fonts, no external
assets) — the same rendering approach as ``admin_html.py``. Mounted behind
the admin access gate. Every interpolated value goes through ``html.escape``;
both POST forms use a double-submit CSRF cookie; every response is
``Cache-Control: no-store``; key plaintext is never logged.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import html
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from pry.api.routers.core.admin_router import _check_admin_access
from pry.commerce import billing_service
from pry.core import api_keys_service

logger = logging.getLogger(__name__)
CSRF_COOKIE = "pry_csrf"
TIERS = ("FREE", "PRO", "ENTERPRISE")
_esc = html.escape
_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
}
_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "app"
_STYLE = (_TEMPLATE_DIR / "ui.css").read_text(encoding="utf-8").strip()

router = APIRouter(tags=["App UI"], dependencies=[Depends(_check_admin_access)])


def _page(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(title)}</title><style>{_STYLE}</style></head><body><h1>Pry</h1>"
        f"<p class='sub'>{_esc(title)} · <a href='/app'>keys</a> · <a href='/app/usage'>usage</a></p>{body}"
        "</body></html>"
    )


def _csrf(request: Request) -> str:
    return request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)


def _render(request: Request, title: str, body: str, token: str) -> HTMLResponse:
    response = HTMLResponse(_page(title, body), headers=dict(_HEADERS))
    if request.cookies.get(CSRF_COOKIE) != token:
        response.set_cookie(
            CSRF_COOKIE,
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )
    return response


async def _form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8", "replace")
    return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items() if v}


def _check_csrf(request: Request, form: dict[str, str]) -> str:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    sent = form.get("csrf_token", "")
    if not cookie or not sent or not secrets.compare_digest(cookie, sent):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    return cookie


def _safe(fn: Any, default: Any) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - dashboard degrades, never 500s
        logger.warning("app_ui_data_unavailable", extra={"error": type(exc).__name__})
        return default


def _key_rows(keys: list[dict[str, Any]], token: str) -> str:
    rows = []
    for key in keys:
        if key.get("is_active"):
            kid = _esc(quote(str(key.get("key_id", "")), safe=""))
            rows.append(
                f"<tr><td>{_esc(str(key.get('name') or '—'))}</td>"
                f"<td><code>{_esc(str(key.get('key_prefix') or ''))}</code></td>"
                f"<td class='muted'>{_esc(str(key.get('created_at') or '—'))[:19]}</td>"
                f"<td><form method='post' action='/app/keys/{kid}/revoke'>"
                f"<input type='hidden' name='csrf_token' value='{_esc(token)}'>"
                "<button class='danger' type='submit'>Revoke</button></form></td></tr>"
            )
    return "".join(rows) or "<tr><td colspan='4' class='muted'>No active keys yet</td></tr>"


def _usage_summary() -> dict[str, Any]:
    from sqlalchemy import func

    from pry.core.db.models import Usage
    from pry.core.db.session import get_session

    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    with get_session() as session:
        month = session.query(Usage).filter(Usage.created_at >= start)
        calls = month.count()
        spend = (
            session.query(func.coalesce(func.sum(Usage.cost_usd), 0.0))
            .filter(Usage.created_at >= start)
            .scalar()
            or 0.0
        )
        rows = (
            month.with_entities(Usage.endpoint, func.count().label("calls"))
            .group_by(Usage.endpoint)
            .order_by(func.count().desc())
            .limit(5)
            .all()
        )
    balance = billing_service.get_balance(api_keys_service.PRIMARY_USER_ID).get("balance_usd", 0)
    return {
        "calls": int(calls),
        "spend": float(spend),
        "credits": float(balance),
        "endpoints": [(str(r[0] or "unknown"), int(r[1])) for r in rows],
    }


@router.get("/app", response_class=HTMLResponse, summary="App: keys and key status")
async def app_home(request: Request) -> HTMLResponse:
    token = _csrf(request)
    keys = _safe(api_keys_service.list_keys, [])
    balance = _safe(lambda: billing_service.get_balance(api_keys_service.PRIMARY_USER_ID), {})
    usage = _safe(_usage_summary, {"calls": 0, "spend": 0.0, "credits": 0.0, "endpoints": []})
    options = "".join(f"<option value='{t}'>{t}</option>" for t in TIERS)
    body = (
        "<div class='grid'>"
        f"<div class='card'><h3>Active keys</h3><div class='v lime'>{sum(1 for k in keys if k.get('is_active'))}</div></div>"
        f"<div class='card'><h3>Usage this month</h3><div class='v'>{usage['calls']:,}</div></div>"
        f"<div class='card'><h3>Spend this month</h3><div class='v cyan'>${usage['spend']:,.4f}</div></div>"
        f"<div class='card'><h3>Credits</h3><div class='v'>${float(balance.get('balance_usd', 0)):,.2f}</div></div>"
        "</div><div class='panel'><table><tr><th>Name</th><th>Prefix</th><th>Created</th><th></th></tr>"
        f"{_key_rows(keys, token)}</table></div><div class='panel'>"
        "<h3 class='lime' style='font-size:.8rem;margin-bottom:.75rem'>Create key</h3>"
        "<form class='form' method='post' action='/app/keys'>"
        f"<input type='hidden' name='csrf_token' value='{_esc(token)}'>"
        "<input name='name' maxlength='128' placeholder='Key name (optional)'>"
        f"<select name='tier'>{options}</select><button type='submit'>Create key</button></form>"
        "<p class='muted' style='font-size:.75rem'>The key is shown once, on the next screen. "
        "Store it before leaving the page.</p></div>"
    )
    return _render(request, "Keys", body, token)


@router.post("/app/keys", response_class=HTMLResponse, summary="App: create a key (shown once)")
async def app_create_key(request: Request) -> HTMLResponse:
    form = await _form(request)
    token = _check_csrf(request, form)
    tier = (form.get("tier") or "FREE").upper()
    if tier not in TIERS:
        raise HTTPException(status_code=400, detail="unknown tier")
    try:
        result = api_keys_service.issue_key(name=(form.get("name") or "")[:128], tier=tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("app_ui_key_issued", extra={"key_id": result["key_id"], "tier": tier})
    body = (
        "<div class='panel'><h3 class='lime' style='margin-bottom:.5rem'>Key created — copy it now</h3>"
        f"<div class='keybox'><code id='new-key'>{_esc(result['plaintext'])}</code></div>"
        "<p class='note'>This is the only time the full key is shown. "
        "Copy it into your password manager or secret store before continuing.</p>"
        f"<p class='muted' style='font-size:.75rem;margin-top:.5rem'>Name: {_esc(str(result.get('name') or '—'))}"
        f" · Tier: {_esc(tier)} · ID: {_esc(str(result.get('key_id') or ''))}</p>"
        "<p style='margin-top:1rem'><a href='/app'>Back to keys</a></p></div>"
    )
    return _render(request, "Key created", body, token)


@router.post("/app/keys/{key_id}/revoke", summary="App: revoke a key")
async def app_revoke_key(request: Request, key_id: str) -> Response:
    form = await _form(request)
    _check_csrf(request, form)
    if not api_keys_service.revoke_key(key_id):
        raise HTTPException(status_code=404, detail="key not found or already revoked")
    logger.info("app_ui_key_revoked", extra={"key_id": key_id})
    return RedirectResponse("/app", status_code=303, headers=dict(_HEADERS))


@router.get("/app/usage", response_class=HTMLResponse, summary="App: usage this month")
async def app_usage(request: Request) -> HTMLResponse:
    token = _csrf(request)
    usage = _safe(_usage_summary, {"calls": 0, "spend": 0.0, "credits": 0.0, "endpoints": []})
    rows = (
        "".join(
            f"<tr><td>{_esc(name)}</td><td>{calls:,}</td></tr>"
            for name, calls in usage["endpoints"]
        )
        or "<tr><td colspan='2' class='muted'>No calls this month</td></tr>"
    )
    body = (
        "<div class='grid'>"
        f"<div class='card'><h3>Calls this month</h3><div class='v'>{usage['calls']:,}</div></div>"
        f"<div class='card'><h3>Credits</h3><div class='v'>${usage['credits']:,.2f}</div></div>"
        f"<div class='card'><h3>Spend this month</h3><div class='v cyan'>${usage['spend']:,.4f}</div></div>"
        "</div><div class='panel'><h3 class='lime' style='font-size:.8rem;margin-bottom:.75rem'>"
        "Top endpoints</h3><table><tr><th>Endpoint</th><th>Calls</th></tr>"
        f"{rows}</table></div>"
    )
    return _render(request, "Usage", body, token)
