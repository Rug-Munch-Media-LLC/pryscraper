# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fixture HTML snippets shared by the block-detection signal-kind tests."""

from __future__ import annotations

CF_CHALLENGE_HTML = """<!DOCTYPE html>
<html><head><title>Just a moment...</title></head>
<body><div class="cf-chl-opt">Checking your browser before accessing.</div>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1"></script>
</body></html>"""

CF_403_HTML = "<html><body><h1>Access denied</h1></body></html>"

RECAPTCHA_HTML = """<!DOCTYPE html>
<html><head><script src="https://www.google.com/recaptcha/api.js"></script></head>
<body><div class="g-recaptcha" data-sitekey="6Lc..."></div>
<script>grecaptcha.execute();</script>
<p>Please verify you are human.</p></body></html>"""

HCAPTCHA_HTML = (
    '<html><body><script src="https://hcaptcha.com/1/api.js" async defer></script>'
    '<div class="h-captcha" data-sitekey="abc"></div></body></html>'
)

TURNSTILE_HTML = (
    '<html><body><script src="https://challenges.cloudflare.com/turnstile/v0/api.js" '
    'async defer></script><div class="cf-turnstile" data-sitekey="0x4"></div></body></html>'
)

HUMAN_CHECK_HTML = (
    "<html><body><p>Please complete the security check. "
    "Verify you are human to continue.</p></body></html>"
)

RATE_LIMIT_HTML = (
    "<html><body><h1>Too many requests</h1><p>Please try again later.</p></body></html>"
)

ACCESS_DENIED_HTML = (
    "<html><body><h1>Access Denied</h1><p>You don't have permission.</p></body></html>"
)

FORBIDDEN_HTML = "<html><body><h1>403 Forbidden</h1><p>nginx</p></body></html>"

JS_REQUIRED_HTML = (
    "<html><head><title>Site</title></head><body>"
    "<noscript>Please enable JavaScript to view this page.</noscript>"
    '<div id="app"></div></body></html>'
)

SCRIPTS_ONLY_HTML = (
    "<html><head></head><body>"
    '<script src="/assets/app.js"></script>'
    "<script>window.__DATA__ = {};</script>"
    "</body></html>"
)

CLEAN_HTML = """<!DOCTYPE html>
<html><head><title>Example</title></head>
<body><h1>Welcome</h1>
<p>This is a perfectly normal page with lots of useful text content.</p>
<a href="/about">About</a></body></html>"""
