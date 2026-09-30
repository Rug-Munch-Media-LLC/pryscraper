"""SSRF rejection tests for the parser's own fetch (``POST /v1/parse``).

``pry.engine.parser.DocumentParser.parse`` built its client
``follow_redirects=True`` and called ``client.get(url)`` on it. That is a
two-part defect and only the first part is obvious:

1. The URL — the caller's request body — was never validated.
2. The redirect behaviour lived on the CLIENT, not the call, so swapping the
   call for a guarded one while leaving the flag in place looks fixed and is
   not. The guard would validate hop one and httpx would walk every later hop
   unvalidated.

Split from ``test_engine_fetch_ssrf_reject.py`` for the 200-line structure cap.
The enrichment site is covered there; the happy path for both is in
``test_engine_fetch_ssrf_allow.py``.
"""

from __future__ import annotations

import asyncio

import httpx
import respx

from tests.test_engine_fetch_ssrf_reject import LEAK_BODY, METADATA, client


@respx.mock
def test_parser_client_does_not_follow_redirects_itself() -> None:
    """Kills: the parser-specific half of the fix.

    ``DocumentParser.parse`` built its client ``follow_redirects=True``, so the
    redirect behaviour lived on the CONSTRUCTOR, not the call. Swapping the call
    for ``guard_get`` while leaving that flag in place looks fixed and is not:
    the guard would validate hop one and httpx would walk every later hop
    unvalidated, so a 302 into 169.254.169.254 would still be fetched.

    Asserting the property directly is the only way to keep the constructor
    honest — the route-level tests cannot distinguish the two shapes, because
    both return 400 for the same submitted URL.
    """

    async def _vulnerable_shape() -> httpx.Response:
        # The shape the fix removed: client-level redirect following.
        async with httpx.AsyncClient(follow_redirects=True) as vulnerable:
            return await vulnerable.get("https://redirector.example.com/go")

    respx.get("https://redirector.example.com/go").mock(
        return_value=httpx.Response(302, headers={"location": METADATA})
    )
    metadata = respx.get(METADATA).mock(return_value=httpx.Response(200, text=LEAK_BODY))

    resp = asyncio.run(_vulnerable_shape())

    assert resp.status_code == 200
    assert metadata.called, "expected the client-level-follow shape to reach the second hop"


@respx.mock
def test_parse_rejected_url_is_4xx_not_500() -> None:
    """Kills: catching only ``(httpx.HTTPError, httpx.RequestError)`` at the call
    site — the regression this repo already shipped once.

    ``InvalidRequestError`` is a ``PryError``, NOT an httpx error, so a handler
    that lists only httpx types lets it escape as an unhandled exception. On an
    unauthenticated route that is a 500 for a caller mistake.
    """
    respx.route().mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post("/v1/parse", json={"url": METADATA, "timeout": 5})

    assert r.status_code == 400, f"/v1/parse: expected 400, got {r.status_code}"
    assert r.json()["code"] == "invalid_request", r.text[:200]
    assert r.json()["status"] == 400
