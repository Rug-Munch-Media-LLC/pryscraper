"""SSRF rejection tests for the SEO and structure actor layer.

Three actor entrypoints — ``pry.actors.seo_monitor.analyze_seo``,
``get_seo_keyword_insights``, and ``pry.actors.structure_monitor.check_selectors``
— fetched a caller-supplied URL with a bare ``client.get(..., follow_redirects=True)``.
The router layer was fixed for exactly this bug class in ``b84bd2b1``; these three
sites sit *below* the routers, so the fix never reached them. The URLs are
caller input by design: ``POST /v1/seo/analyze`` takes ``{"url": ...}`` from the
request body and the route is **not** in ``_AUTH_PUBLIC_PATHS``, so an anonymous
internet caller in ``free`` mode (no API key configured, loopback-only) cannot
reach it — but a keyless self-hosted deployment behind a reverse proxy, or any
caller holding a ``pry_`` key, can supply an arbitrary URL.

Two distinct bugs, two distinct test groups:

* **first hop** — the initial URL is an internal target. ``guard_get`` rejects
  it before any socket is opened.
* **redirect hop** — the initial URL is a *valid public page* that 302s to an
  internal target. This is the case a single ``validate_url(url)`` before an
  unguarded fetch cannot catch, and the reason ``safe_get`` re-validates every
  ``Location``.

The third concern is the error-handling regression: ``InvalidRequestError`` is a
``PryError``, **not** an ``httpx`` error, so a call site catching only
``(httpx.HTTPError, httpx.RequestError)`` lets it escape into FastAPI's
generic handler. ``test_actor_ssrf_error_channel.py`` is the module that guards
it, and its docstring explains why the damage is a silently-changed response
shape rather than a 5xx. The status assertions in this module are therefore
"not a 5xx" — these three routes report a per-URL error as HTTP 200 +
``success: false``, which is their existing contract.

The companion module ``test_actor_ssrf_allow.py`` proves the guard does not
break ordinary public monitoring.

Every test names the mutation it kills.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from tests.ssrf_actor_harness import (
    ACTOR_ROUTES,
    LEAK_BODY,
    METADATA,
    REDIRECTOR,
    ROUTE_IDS,
    client,
)

# ── first hop: the internal target is never connected ─────────────────────


@respx.mock
@pytest.mark.parametrize(("route", "actor", "body"), ACTOR_ROUTES, ids=ROUTE_IDS)
def test_cloud_metadata_is_never_fetched(route: str, actor: str, body: object) -> None:
    """Kills: reverting any of the three actor sites to a bare
    ``client.get(url, follow_redirects=True)``.

    A leak shows up two ways — the catch-all route is called, or the response
    body carries the metadata payload. Both are asserted, so the test cannot
    pass while the fetch succeeds.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post(route, json=body)

    assert not catch_all.called, f"{actor} opened a connection to the metadata service"
    assert LEAK_BODY not in r.text, f"{actor} returned metadata-service content"


@respx.mock
@pytest.mark.parametrize(
    ("route", "actor", "target"),
    [
        ("/v1/seo/analyze", "analyze_seo", "http://169.254.169.254/latest/meta-data/"),
        ("/v1/seo/keywords", "get_seo_keyword_insights", "http://127.0.0.1:8080/admin"),
        ("/v1/seo/track", "track_seo_changes", "file:///etc/passwd"),
        (
            "/v1/structure/check",
            "check_selectors",
            {"url": "http://127.0.0.1:8080/admin", "selectors": [{"selector": "h1"}]},
        ),
    ],
    ids=["seo-metadata", "seo-loopback", "seo-file-scheme", "structure-loopback"],
)
def test_internal_first_hop_is_never_fetched(route: str, actor: str, target: object) -> None:
    """Kills: an over-narrow guard that only blocks the metadata IP, plus a
    revert of the non-metadata internal shapes.

    ``127.0.0.1`` and ``file://`` are the two payloads a
    metadata-IP-only blocklist never sees, so each is exercised on a *different*
    actor entrypoint — a fix applied to one site and not the others shows up
    as a failure here rather than as silently-untested code.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text="internal-secret"))

    r = client.post(route, json=target)

    assert not catch_all.called, f"{actor} fetched a rejected target: {target}"
    assert r.status_code != 500, f"{actor} turned a rejection into a 500: {r.text}"
    assert "internal-secret" not in r.text


# ── the redirect case: what a single validate_url cannot catch ────────────


@respx.mock
@pytest.mark.parametrize(
    ("route", "actor", "body"),
    ACTOR_ROUTES,
    ids=ROUTE_IDS,
)
def test_public_redirect_to_metadata_is_rejected(route: str, actor: str, body: object) -> None:
    """Kills: the "validate the first URL, then follow redirects" fix — the
    mistake that survives a first-hop-only guard.

    ``REDIRECTOR`` is a valid public page, so a one-shot ``validate_url(url)``
    before an unguarded fetch approves it and httpx follows the 302 with
    nothing re-checking it. Only per-hop re-validation stops this.

    The first hop *is* expected to be fetched: proving the public URL was
    rejected for the wrong reason would hide the real bug.
    """
    first_hop = respx.get(REDIRECTOR).mock(
        return_value=httpx.Response(302, headers={"location": METADATA})
    )
    metadata = respx.get("http://169.254.169.254/latest/meta-data/").mock(
        return_value=httpx.Response(200, text=LEAK_BODY)
    )

    r = client.post(route, json=_body_for(route))

    assert first_hop.called, f"{actor} did not fetch the public first hop at all"
    assert not metadata.called, f"{actor} followed a 302 to the metadata service"
    assert r.status_code != 500, f"{actor} turned a rejection into a 500: {r.text}"
    assert LEAK_BODY not in r.text


@respx.mock
def test_public_redirect_to_loopback_is_rejected() -> None:
    """Kills: per-hop re-validation that checks the scheme but not the host —
    the ``file://`` variant lives in ``test_router_ssrf_reject.py``; this is the
    loopback variant on the structure actor specifically.
    """
    respx.get(REDIRECTOR).mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1:8080/admin"})
    )
    loopback = respx.get("http://127.0.0.1:8080/admin").mock(
        return_value=httpx.Response(200, text="admin-secret")
    )

    r = client.post(
        "/v1/structure/check", json={"url": REDIRECTOR, "selectors": [{"selector": "h1"}]}
    )

    assert not loopback.called, "followed a 302 to loopback"
    assert r.status_code != 500, f"expected a non-500, got {r.status_code}: {r.text}"
    assert "admin-secret" not in r.text


@respx.mock
def test_redirect_chain_stops_at_the_offending_hop() -> None:
    """Kills: a fix that re-validates only the *first* redirect, or that
    validates but still follows. Two safe hops, then an internal third.
    """
    respx.get("https://a.example.com/1").mock(
        return_value=httpx.Response(302, headers={"location": "https://b.example.com/2"})
    )
    respx.get("https://b.example.com/2").mock(
        return_value=httpx.Response(302, headers={"location": METADATA})
    )
    metadata = respx.get("http://169.254.169.254/latest/meta-data/").mock(
        return_value=httpx.Response(200, text="secret")
    )

    r = client.post("/v1/seo/analyze", json="https://a.example.com/1")

    assert not metadata.called
    assert r.status_code != 500, f"expected a non-500, got {r.status_code}: {r.text}"


# ── the error-handling regression: 4xx, never 500 ──────────────────────────


def _body_for(route: str) -> object:
    """The request body for ``route`` pointed at the redirector instead of the
    metadata service, so the first hop is a public page and only the *second*
    hop is internal.
    """
    if route == "/v1/seo/keywords":
        return {"url": REDIRECTOR, "keywords": ["alpha"]}
    if route in ("/v1/structure/check", "/v1/structure/monitor"):
        return {"url": REDIRECTOR, "selectors": [{"selector": "h1"}]}
    return REDIRECTOR
