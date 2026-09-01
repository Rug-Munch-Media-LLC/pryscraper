"""Pry — human crypto checkout for hosted instances.

Humans don't speak x402: they need a page with a QR code, a wallet
deep-link, a place to paste their transaction hash, and a receipt in their
inbox. This module serves that flow on top of the existing hosting
invoice + on-chain verification stack (no new payment code — the same
self-facilitator that settles bot traffic settles humans).

Flow:
  1. POST /v1/hosting/signup  -> invoice (existing)
  2. GET  /checkout/{id}      -> this page (QR + address + amount)
  3. Human pays from any wallet, pastes the tx hash on the page
  4. POST /v1/hosting/signup/{id}/confirm (existing) -> on-chain verify
  5. On paid: receipt email + API key + portal link (existing provision)
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import html
import json
import logging
import ssl
from typing import Any

logger = logging.getLogger(__name__)

_PAGE_STYLE = """
  body{font-family:ui-sans-serif,system-ui,sans-serif;background:#0b0e14;color:#e6e9f0;
       margin:0;display:flex;justify-content:center;padding:40px 16px}
  .card{background:#131722;border:1px solid #232a3a;border-radius:14px;
        max-width:520px;width:100%;padding:28px}
  h1{font-size:20px;margin:0 0 4px} .sub{color:#8b93a7;font-size:13px;margin-bottom:20px}
  .row{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #1c2333}
  .k{color:#8b93a7;font-size:13px} .v{font-weight:600;font-size:14px;text-align:right}
  .addr{font-family:ui-monospace,monospace;font-size:12px;word-break:break-all;
        background:#0b0e14;padding:10px;border-radius:8px;margin:8px 0}
  .qr{display:flex;justify-content:center;margin:18px 0}
  input{width:100%;box-sizing:border-box;background:#0b0e14;border:1px solid #2a3245;
        color:#e6e9f0;border-radius:8px;padding:11px;font-size:13px;margin:8px 0}
  button{width:100%;background:#4f7cff;color:#fff;border:0;border-radius:8px;
         padding:12px;font-size:15px;font-weight:600;cursor:pointer;margin-top:6px}
  button:disabled{opacity:.5}
  .status{margin-top:14px;font-size:14px;min-height:20px}
  .ok{color:#4ade80}.err{color:#f87171}
  select{width:100%;background:#0b0e14;border:1px solid #2a3245;color:#e6e9f0;
         border-radius:8px;padding:10px;font-size:13px;margin:8px 0}
  a{color:#7aa2f7}
"""


def _qr_svg(data: str) -> str:
    """Render a QR code as an inline SVG (no external requests)."""
    import qrcode.image.svg

    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    return img.to_string().decode() if isinstance(img.to_string(), bytes) else img.to_string()


_WALLET_LINKS = {
    "eip155:8453": "ethereum:",
    "eip155:1": "ethereum:",
    "eip155:42161": "ethereum:",
    "eip155:10": "ethereum:",
    "eip155:137": "ethereum:",
    "solana:mainnet": "solana:",
    "tron:mainnet": "tron:",
}


def render_checkout_page(invoice: dict[str, Any]) -> str:
    """Self-contained HTML checkout for a hosting invoice.

    Shows plan/amount/address/QR, wallet deep-links per supported network,
    a tx-hash submission form that calls the existing confirm endpoint, and
    live status. No JS frameworks, no external assets.
    """
    invoice_id = html.escape(str(invoice.get("invoice_id", "")))
    plan = html.escape(str(invoice.get("plan_tier", "")))
    amount_usd = invoice.get("amount_usd", "")
    amount_atomic = html.escape(str(invoice.get("amount_atomic", "")))
    pay_to = html.escape(str(invoice.get("pay_to", "")))
    asset = html.escape(str(invoice.get("asset", "USDC")))
    qr = _qr_svg(f"{_WALLET_LINKS.get(str(invoice.get('chain', '')), 'ethereum:')}{pay_to}")
    confirm_url = f"/v1/hosting/signup/{invoice_id}/confirm"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pry checkout — {plan} plan</title>
<style>{_PAGE_STYLE}</style></head>
<body><div class="card">
<h1>Pry Hosted — {plan} plan</h1>
<div class="sub">Send exactly the amount below, then paste your transaction hash.
Your instance provisions automatically on confirmation.</div>
<div class="row"><span class="k">Plan</span><span class="v">{plan}</span></div>
<div class="row"><span class="k">Amount</span><span class="v">${amount_usd} ({amount_atomic} atomic {html.escape(str(asset))})</span></div>
<div class="row"><span class="k">Network</span><span class="v">{html.escape(str(invoice.get("chain", "")))}</span></div>
<div class="row"><span class="k">Invoice</span><span class="v">{invoice_id}</span></div>
<div class="qr">{qr}</div>
<div class="k">Send to ({html.escape(str(asset))} on {html.escape(str(invoice.get("chain", "")))}):</div>
<div class="addr">{pay_to}</div>
<label class="k" for="net">Network used</label>
<select id="net">
  <option value="eip155:8453">Base</option>
  <option value="eip155:1">Ethereum</option>
  <option value="eip155:42161">Arbitrum</option>
  <option value="eip155:10">Optimism</option>
  <option value="eip155:137">Polygon</option>
  <option value="solana:mainnet">Solana</option>
  <option value="tron:mainnet">TRON</option>
</select>
<label class="k" for="tx">Transaction hash</label>
<input id="tx" placeholder="0x… / signature / signature (SPL)">
<button onclick="verify()">I've paid — verify &amp; provision</button>
<div class="status" id="status"></div>
<div class="sub" style="margin-top:16px">A receipt goes to your email the moment
the payment verifies on-chain. Questions: biz@pryscraper.com</div>
</div>
<script>
const CONFIRM = {json.dumps(confirm_url)};
async function verify() {{
  const tx = document.getElementById('tx').value.trim();
  const st = document.getElementById('status');
  if (!tx) {{ st.className = 'status err'; st.textContent = 'Paste your transaction hash first.'; return; }}
  st.className = 'status'; st.textContent = 'Verifying on-chain…';
  try {{
    const r = await fetch(CONFIRM, {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{tx_hash: tx, network: document.getElementById('net').value}})}});
    const j = await r.json();
    const d = j.data || {{}};
    if (j.success && d.paid) {{
      st.className = 'status ok';
      st.textContent = 'Payment verified — instance provisioning. API key + receipt sent to your email.';
    }} else {{
      st.className = 'status err';
      st.textContent = 'Not verified: ' + (d.reason || r.status);
    }}
  }} catch (e) {{ st.className = 'status err'; st.textContent = 'Verification failed: ' + e; }}
}}
</script></body></html>"""


# ── Receipt email ──────────────────────────────────────────────────────────


def send_hosting_receipt(
    *,
    to_email: str,
    invoice_id: str,
    plan_tier: str,
    amount_usd: float,
    tx_hash: str,
    api_key: str | None,
    instance_id: str | None,
) -> dict[str, Any]:
    """Email the payment receipt + credentials after on-chain confirmation.

    Uses the fleet mail relay with the biz@ identity —
    the same pipeline verified for deliverability. Never raises: a failed
    receipt must not fail the provisioning flow (it's logged and the
    customer can be re-sent manually).
    """
    import os
    import smtplib
    from email.message import EmailMessage
    from email.utils import formatdate, make_msgid

    portal_url = (
        os.getenv("PRY_PUBLIC_BASE_URL", "https://api.pryscraper.com").rstrip("/")
        + f"/v1/hosting/portal?email={to_email}"
    )
    key_block = f"Your API key (shown once, store it safely):\n  {api_key}\n\n" if api_key else ""
    instance_block = f"Instance ID: {instance_id}\n" if instance_id else ""
    body = f"""Pry Hosted — payment receipt

Invoice:   {invoice_id}
Plan:      {plan_tier}
Amount:    ${amount_usd:.2f} (paid in crypto, verified on-chain)
Tx:        {tx_hash}
Instance:  {instance_id or "(renewal — existing instance extended)"}

{key_block}{instance_block}
Manage your instance, monitor usage and rotate API keys any time:
  {portal_url}

Support: support@pryscraper.com
— Rug Munch Media LLC
"""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # loopback/tailscale SMTP hop
        s = smtplib.SMTP("100.104.130.92", 587, timeout=15)
        s.starttls(context=ctx)
        s.login("biz@pryscraper.com", os.getenv("PRY_MAIL_PASSWORD", ""))
        msg = EmailMessage()
        msg["From"] = "Pry Business <biz@pryscraper.com>"
        msg["To"] = to_email
        msg["Subject"] = f"[Pry] Receipt {invoice_id} — {plan_tier} plan (${amount_usd:.2f})"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="pryscraper.com")
        msg.set_content(body)
        s.send_message(msg)
        s.quit()
        logger.info("hosting_receipt_sent", extra={"to": to_email, "invoice": invoice_id})
        return {"success": True}
    except Exception as e:  # noqa: BLE001 — receipt failure must not fail provisioning
        logger.warning("hosting_receipt_failed", extra={"to": to_email, "error": str(e)[:120]})
        return {"success": False, "error": str(e)[:200]}
