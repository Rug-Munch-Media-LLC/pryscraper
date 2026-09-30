# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Realistic block-page fixtures for the block-detection suites.

Split from tests/test_block_detection_hardened.py on 2026-09-30. The bytes and
the reasoning behind them are the same content that used to be inline; keeping
them here means a fixture and the decision that justifies its SHAPE travel
together, so a future edit cannot quietly weaken the page without also touching
the argument for why it is that shape.

The small multi-marker pages (grecaptcha / too many requests / access denied /
enable javascript) stay inline in the tests that use them — they are one line
each and are not shared. Size-gated page builders live in block_gate_helpers.py.
"""

from __future__ import annotations

__all__ = ["CLOUDFLARE_INTERSTITIAL"]

#: A real Cloudflare interstitial: title + challenge-platform script + the
#: cf-please-wait widget, plus a captcha marker so that "Cloudflare must beat
#: CAPTCHA" is a real contest rather than a walkover.
#:
#: A REAL Cloudflare interstitial carries several CF markers together —
#: the title, the challenge-platform script and the widget div. The old
#: fixture had exactly ONE ("just a moment") plus a captcha marker, which
#: is not a Cloudflare page; under the 2+ density gate it is correctly
#: NOT classified as Cloudflare, and this test was red because its
#: fixture did not match the thing it claimed to test.
#:
#: The density gate is deliberate and was added because a 744 KB served
#: ARTICLE was being rejected for containing challenge-platform once. A
#: single incidental mention is not a block; a real interstitial is
#: unambiguous. Fixing the fixture keeps both properties true.
CLOUDFLARE_INTERSTITIAL = (
    "<html><head><title>Just a moment...</title></head><body>"
    "<div id='cf-please-wait'></div>"
    "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate'></script>"
    "grecaptcha"
    "</body></html>"
)
