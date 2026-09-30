"""Error-channel regression tests for the actor-layer SSRF guard.

``pry.engine.url_guard.safe_get`` raises ``InvalidRequestError``, a subclass of
``PryError`` — **not** an ``httpx`` exception. The actors' existing handlers
catch only ``(httpx.HTTPError, httpx.RequestError)``, so a guarded rejection
escapes into FastAPI and is rendered by the ``PryError`` handler that
``pry.api.app_wiring`` installs. That handler returns a correct HTTP 400, so the
SSRF is blocked either way — but the response is a **generic problem+json
document** carrying the route's URL nowhere and the route's ``success: false``
flag nowhere, on a route whose entire contract is
``{"success": false, "data": {"url": ..., "error": ...}}``.

The consequence is a silent API break: a caller that checks
``response.json()["success"]`` gets a ``KeyError`` on exactly the request a
hostile caller probes, and a caller reading ``data.error`` gets nothing at all.
An operator reading the logs sees a clean 400 and concludes the guard worked,
while the client-side contract quietly changed shape for one input class.

So the assertions here are on the parts the generic handler destroys, and they
are red when ``PryError`` is dropped from the actors' ``except`` clauses.

[REVIEW] The prompt for this work described this failure as an HTTP 500. That
is correct only in an app without ``add_error_handlers`` (and only for a
non-``PryError``); the real app wires a ``PryError`` handler
(``src/pry/api/app_wiring.py``), so the observed regression here is the
contract break above, not a 5xx. ``test_rejection_is_never_a_5xx`` still
asserts the 5xx property explicitly so a future change to that wiring is
caught rather than assumed.

Every test names the mutation it kills.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from tests.ssrf_actor_harness import LEAK_BODY, METADATA, client

#: One case per guarded actor, so a fix that catches ``PryError`` in
#: ``analyze_seo`` but not in ``get_seo_keyword_insights`` or
#: ``check_selectors`` fails here rather than hiding.
REJECTION_ROUTES: list[tuple[str, str, object]] = [
    ("/v1/seo/analyze", "analyze_seo", METADATA),
    ("/v1/seo/track", "track_seo_changes", METADATA),
    ("/v1/seo/keywords", "get_seo_keyword_insights", {"url": METADATA, "keywords": ["alpha"]}),
    (
        "/v1/structure/check",
        "check_selectors",
        {"url": METADATA, "selectors": [{"selector": "h1"}]},
    ),
]
REJECTION_IDS = [actor for _, actor, _ in REJECTION_ROUTES]

#: The three actors' rejection payloads, all shaped the same way by the
#: routers: ``{"success": <bool>, "data": {...}}``.
_OK_KEYS = ("success", "data")


@respx.mock
@pytest.mark.parametrize(("route", "actor", "body"), REJECTION_ROUTES, ids=REJECTION_IDS)
def test_rejection_keeps_the_routes_response_contract(route: str, actor: str, body: object) -> None:
    """Kills: dropping ``PryError`` from the guarded call site's ``except``
    clause, so the rejection escapes to FastAPI's generic ``PryError`` handler
    and the response stops being the route's ``{"success", "data"}`` shape.

    This is the assertion that was wrong in the first draft of this module: it
    is not that the status becomes a 500, it is that the *body shape* changes,
    silently, for one input class.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post(route, json=body)

    payload = r.json()
    for key in _OK_KEYS:
        assert key in payload, (
            f"{actor} rejection lost the '{key}' key — the response is no longer the "
            f"route's contract shape (status {r.status_code}): {payload}"
        )
    assert payload["success"] is False, f"{actor} reported a rejection as success: {payload}"
    assert payload["data"].get("error"), f"{actor} carried no error field: {payload}"
    assert not catch_all.called


@respx.mock
@pytest.mark.parametrize(("route", "actor", "body"), REJECTION_ROUTES, ids=REJECTION_IDS)
def test_rejection_is_never_a_5xx(route: str, actor: str, body: object) -> None:
    """Kills: a guard rejection surfacing as a server fault — the version of
    this bug that occurs when the actor re-raises, or when the app's
    ``PryError`` handler is not wired. Stated separately so a regression reads
    as the specific defect it is.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post(route, json=body)

    assert r.status_code < 500, f"{actor} reported an SSRF rejection as {r.status_code}: {r.text}"
    assert LEAK_BODY not in r.text, f"{actor} leaked an internal response body"
    assert not catch_all.called
