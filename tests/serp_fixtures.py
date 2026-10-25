"""Shared SERP HTML fixtures for the attention tests (no network)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.attention import serp

A_HTML = """<html><body>
<div class="MjjYud">
  <a href="/url?q=https://example.com/bitcoin&sa=U"><h3>Bitcoin - Example</h3></a>
  <div class="VwiC3b"><span>Bitcoin is a decentralized digital currency.</span></div>
</div>
<div class="MjjYud">
  <a href="/url?q=https://example.com/bitcoin&sa=U"><h3>Duplicate</h3></a>
  <div class="VwiC3b">dup snippet</div>
</div>
<div class="MjjYud">
  <a href="/url?q=https://www.google.com/preferences"><h3>Google</h3></a>
</div>
<div class="MjjYud"><span>no heading here</span></div>
</body></html>"""

B_HTML = """<html><body>
<div><a href="/goto?url=tok"><h3>Raw Title</h3></a>
  <div data-sncf="1"><span>Current DOM snippet.</span></div></div>
<div><h3>Unanchored</h3></div>
</body></html>"""

AI_CLASS = '<html><body><div class="ILfuVd">AI Overview Supply and demand.</div></body></html>'

AI_LABEL = (
    "<html><body><div><span>AI Overview Bitcoin uses proof of work to secure "
    "its ledger.</span></div></body></html>"
)

PAA_LEGACY = """<html><body>
<div class="related-question-pair">What is Bitcoin?</div>
<div class="related-question-pair">Who created Bitcoin?</div>
</body></html>"""

PAA_LABEL = """<html><body><div>
<span>People also ask</span>
<div><h3>Is Bitcoin legal?</h3><h3>How is Bitcoin mined?</h3></div>
</div></body></html>"""


def root(html: str) -> Any:
    """Parse fixture HTML into an lxml root, asserting it succeeded."""
    parsed = serp._to_root(html)
    assert parsed is not None
    return parsed
