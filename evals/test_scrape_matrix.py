"""Fixture tests for the scrape-matrix verdict mapper. No network by default."""

from __future__ import annotations

import json
import os

import pytest
import scrape_matrix as sm

BIG_HTML = "<html><head><title>t</title></head><body><h1>hi</h1></body></html>" + "x" * 600


@pytest.mark.parametrize(
    ("status", "nbytes", "fields", "body", "error", "expected"),
    [
        (200, len(BIG_HTML), 3, BIG_HTML, None, "ok"),
        (403, 900, 0, "<html>nope</html>", None, "wall"),
        (429, 900, 0, "", None, "wall"),
        (200, 1200, 2, "<html><title>Just a moment...</title></html>", None, "wall"),
        (200, 1200, 2, "<html>cf_chl_opt challenge</html>", None, "wall"),
        (200, 1200, 2, "<html>Attention Required! | Cloudflare</html>", None, "wall"),
        (200, 40, 0, "<html></html>", None, "empty"),
        (200, 2000, 0, "<html><div>shell only</div></html>", None, "empty"),
        (404, 900, 1, BIG_HTML, None, "empty"),
        (502, 900, 0, "", None, "error"),
        (0, 0, 0, "", "URLError: timed out", "error"),
    ],
    ids=[
        "ok",
        "403",
        "429",
        "cloudflare-title",
        "cf-chl",
        "cf-attention",
        "tiny",
        "no-fields",
        "404",
        "502",
        "timeout",
    ],
)
def test_classify_never_promotes_wall_or_empty(status, nbytes, fields, body, error, expected):
    assert sm.classify(status, nbytes, fields, body, error) == expected


def test_classify_wall_body_beats_ok_signals():
    """A challenge page with a title and a 3KB body must still read `wall`."""
    body = "<html><title>Access Denied</title><h1>x</h1></html>" + "y" * 3000
    assert sm.classify(200, len(body), 3, body) == "wall"


def test_count_fields_json_and_html():
    assert sm.count_fields(json.dumps({"a": 1, "b": 2})) == 2
    assert sm.count_fields("[1,2,3]") == 3
    assert sm.count_fields("not json {") == 0
    assert sm.count_fields(BIG_HTML) >= 2


def test_regressions_flags_downgrade_only():
    rows = [
        {"site": "a.com", "verdict": "wall"},
        {"site": "b.com", "verdict": "ok"},
        {"site": "c.com", "verdict": "error"},
        {"site": "d.com", "verdict": "ok"},
    ]
    base = {"a.com": "ok", "b.com": "ok", "c.com": "empty", "z.com": "ok"}
    broke = sm.regressions(rows, base)
    assert [(i["site"], i["was"], i["now"]) for i in broke] == [
        ("a.com", "ok", "wall"),
        ("c.com", "empty", "error"),
    ]


def test_baseline_roundtrip(tmp_path):
    out = tmp_path / "m.json"
    out.write_text(
        json.dumps({"counts": {"wall": 1}, "rows": [{"site": "a.com", "verdict": "wall"}]})
    )
    assert sm.load_baseline(out) == {"a.com": "wall"}


def test_default_sites_are_the_agreed_six():
    assert set(sm.DEFAULT_SITES) == {
        "syndication.twitter.com",
        "dexscreener.com",
        "coingecko.com",
        "rugcheck.xyz",
        "docs.anthropic.com",
        "github.com",
    }


def test_dry_run_makes_no_network_calls():
    assert sm.main([]) == 0


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("SCRAPE_MATRIX_LIVE") != "1",
    reason="live network eval; set SCRAPE_MATRIX_LIVE=1",
)
def test_live_github_returns_a_verdict():
    row = sm.measure("github.com", sm.DEFAULT_SITES["github.com"])
    assert row["verdict"] in {"ok", "wall", "empty", "error"}
