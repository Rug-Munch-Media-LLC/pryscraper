"""Markdown-quality parity tests (crawl4ai checklist, 7 features)."""

# SPDX-License-Identifier: MIT — part of Pry (https://git.rugmunch.io/RugMunchMedia/pryscraper)

import textwrap

import pytest
from markdownify import markdownify

from pry.engine.markdown_quality import (
    finalize_markdown,
    markdown_quality,
    normalize_markdown,
)

BASE = "https://example.com/page"

FIXTURE = """<html><body>
<nav><h1>Site</h1><a href="/menu">Menu</a><a href="/cookies">Accept all cookies</a></nav>
<article>
<h1>Widget Guide</h1>
<p>Read the <a href="/docs">docs</a> for details.</p>
<h2>Install</h2><h3>Python</h3>
<pre><code>def install(name):
    return name</code></pre>
<h2>Pricing</h2>
<table><tr><th>Plan</th><th>Price</th></tr><tr><td>Pro</td><td>$9</td></tr></table>
<p><img src="/chart.png" alt="chart"></p>
<p>Same paragraph.</p><p>Same paragraph.</p>
</article>
<footer>Copyright 2026 Acme</footer>
</body></html>"""


def _markdown(html: str = FIXTURE, include_images: bool = False) -> str:
    raw = markdownify(html, heading_arrows=False, strip=["script", "style"])
    return normalize_markdown(raw, BASE, include_images)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("links", "[docs](https://example.com/docs)"),
        ("code", "```python"),
        ("headings", "# Widget Guide"),
        ("tables", "| Plan | Price |"),
        ("tables-sep", "| --- | --- |"),
    ],
)
def test_fidelity_features(label: str, expected: str) -> None:
    """One fixture, one assertion per checklist feature (links/code/headings/tables)."""
    assert expected in _markdown(), f"{label} missing from markdown"


def test_headings_single_h1_from_nav() -> None:
    md = _markdown()
    assert md.count("\n# ") + md.startswith("# ") == 1, "duplicate h1 survived (nav)"
    assert "## Site" not in md, "nav h1 was demoted instead of dropped"
    assert md.index("# Widget Guide") < md.index("## Install") < md.index("### Python")


def test_images_default_stripped() -> None:
    assert "![" not in _markdown()


def test_images_kept_absolute_when_requested() -> None:
    md = _markdown(include_images=True)
    assert "![chart](https://example.com/chart.png)" in md


def test_noise_removed() -> None:
    md = _markdown()
    for noise in ("Accept all cookies", "Copyright 2026 Acme", "[Menu]"):
        assert noise not in md


def test_dedup_repeated_paragraph() -> None:
    md = _markdown()
    assert md.count("Same paragraph.") == 1
    assert "\n\n\n" not in md


def test_fidelity_score_is_100() -> None:
    assert markdown_quality(_markdown(), BASE)["score"] == 100


def test_score_penalises_broken_markdown() -> None:
    broken = "## a\n## b\n| x |\n| --- |\n<table><tr><td>1</td></tr></table>\n[x](/rel)\n"
    result = markdown_quality(broken, BASE)
    assert result["score"] < 70
    assert result["checks"]["tables"] == 0.0
    assert result["checks"]["links"] == 0.0


def test_finalize_attaches_metadata() -> None:
    out = finalize_markdown({"content": markdownify(FIXTURE)}, BASE)
    assert out["metadata"]["markdown_quality"] == out["markdown_quality"] == 100
    expected = {
        "links",
        "code",
        "headings",
        "tables",
        "images",
        "noise",
        "dedup",
    }
    assert set(out["metadata"]["markdown_checks"]) == expected


def test_trafilatura_path_stays_high_quality() -> None:
    import trafilatura

    article = textwrap.dedent("""<html><body><article><h1>Widget Guide</h1>
    <p>This is a long introductory paragraph about widgets and how they work in practice.</p>
    <h2>Install</h2>
    <p>Read the <a href="/docs">documentation</a> before you install the widget package.</p>
    <h3>Python</h3><pre><code>def install(name):
    return name</code></pre>
    <h2>Pricing</h2>
    <table><tr><th>Plan</th><th>Price</th></tr><tr><td>Pro</td><td>$9</td></tr></table>
    <p>Another long paragraph of body text so the extractor keeps this section intact.</p>
    </article></body></html>""")
    md = normalize_markdown(
        trafilatura.extract(article, output_format="markdown", include_links=True) or "", BASE
    )
    assert "[documentation](https://example.com/docs)" in md
    assert "```python" in md
    assert markdown_quality(md, BASE)["score"] >= 90


def test_scraper_extract_attaches_quality() -> None:
    """The scrape path emits metadata.markdown_quality from the engine result."""
    from pry.engine.scraper import PryScraper

    result = PryScraper()._extract(FIXTURE, BASE, {})
    assert 0 <= result["markdown_quality"] <= 100
    assert result["metadata"]["markdown_quality"] == result["markdown_quality"]
