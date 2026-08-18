"""Tests for pipeline.py — hook system."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline import (
    Pipeline,
    get_pipeline,
    run_pipeline,
    _is_async,
    log_request,
    strip_html_comments,
    extract_all_links,
    HOOK_POINTS,
)


# ── Pipeline class ──


def test_init_creates_all_hook_points():
    p = Pipeline()
    for hp in HOOK_POINTS:
        assert hp in p._hooks
        assert p._hooks[hp] == []


def test_register_valid_hook():
    p = Pipeline()
    fn = lambda **kw: {"ok": True}  # noqa: E731
    p.register("before_scrape", fn)
    assert fn in p._hooks["before_scrape"]


def test_register_invalid_hook():
    p = Pipeline()
    with pytest.raises(ValueError, match="Unknown hook point"):
        p.register("invalid_point", lambda **kw: {})


def test_register_with_priority():
    p = Pipeline()
    fn = lambda **kw: {}  # noqa: E731
    p.register("after_response", fn, priority=5)
    assert fn in p._hooks["after_response"]


@pytest.mark.asyncio
async def test_run_empty_hook():
    """Running a hook point with no hooks returns kwargs."""
    p = Pipeline()
    result = await p.run("before_scrape", url="http://example.com")
    assert result == {"url": "http://example.com"}


@pytest.mark.asyncio
async def test_run_sync_hook():
    p = Pipeline()
    p.register("before_scrape", lambda **kw: {"processed": True})
    result = await p.run("before_scrape", url="http://example.com")
    assert result["processed"] is True


@pytest.mark.asyncio
async def test_run_async_hook():
    p = Pipeline()

    async def my_hook(**kw):
        return {"async_ran": True}

    p.register("before_scrape", my_hook)
    result = await p.run("before_scrape", url="x")
    assert result["async_ran"] is True


@pytest.mark.asyncio
async def test_run_chained_hooks():
    p = Pipeline()
    p.register("before_scrape", lambda **kw: {"step1": True})
    p.register("before_scrape", lambda **kw: {"step2": True})
    result = await p.run("before_scrape", url="x")
    assert result["step1"] is True
    assert result["step2"] is True


@pytest.mark.asyncio
async def test_run_hook_exception_caught():
    p = Pipeline()

    def failing_hook(**kw):
        raise RuntimeError("boom")

    p.register("before_scrape", failing_hook)
    result = await p.run("before_scrape", url="x")
    assert "errors" in result
    assert "boom" in result["errors"][0]


@pytest.mark.asyncio
async def test_run_on_error_hook_exception():
    p = Pipeline()

    def failing_hook(**kw):
        raise RuntimeError("boom")

    p.register("on_error", failing_hook)
    result = await p.run("on_error", url="x")
    assert result["error"] == "boom"


def test_clear_single_point():
    p = Pipeline()
    p.register("before_scrape", lambda **kw: {})
    p.clear("before_scrape")
    assert p._hooks["before_scrape"] == []


def test_clear_all():
    p = Pipeline()
    p.register("before_scrape", lambda **kw: {})
    p.register("after_response", lambda **kw: {})
    p.clear()
    for hp in HOOK_POINTS:
        assert p._hooks[hp] == []


def test_list_hooks_empty():
    p = Pipeline()
    result = p.list_hooks()
    assert all(result[hp] == [] for hp in HOOK_POINTS)


def test_list_hooks_with_registrations():
    p = Pipeline()

    def my_fn(**kw):
        return {}

    p.register("after_response", my_fn)
    result = p.list_hooks()
    assert "my_fn" in result["after_response"]


# ── _is_async ──


def test_is_async_async_fn():
    async def f():
        pass

    assert _is_async(f) is True


def test_is_async_sync_fn():
    def f():
        pass

    assert _is_async(f) is False


# ── get_pipeline / run_pipeline ──


def test_get_pipeline_singleton():
    p1 = get_pipeline()
    p2 = get_pipeline()
    assert p1 is p2


@pytest.mark.asyncio
async def test_run_pipeline_convenience():
    result = await run_pipeline("before_scrape", test_key="value")
    assert "test_key" in result


# ── Built-in hooks ──


@pytest.mark.asyncio
async def test_log_request_hook():
    result = await log_request(url="http://example.com", hook_point="before_scrape")
    assert result == {}


@pytest.mark.asyncio
async def test_strip_html_comments():
    result = await strip_html_comments(html="<div><!-- comment -->content</div>")
    assert "<!--" not in result["html"]


@pytest.mark.asyncio
async def test_strip_html_comments_no_html():
    result = await strip_html_comments(url="http://x.com")
    assert result == {}


@pytest.mark.asyncio
async def test_extract_all_links():
    html = '<a href="http://example.com">link</a><a href="/about">about</a>'
    result = await extract_all_links(html=html)
    assert len(result["extracted_links"]) == 2


@pytest.mark.asyncio
async def test_extract_all_links_empty():
    result = await extract_all_links(html="")
    assert result == {}


@pytest.mark.asyncio
async def test_extract_all_links_bad_html():
    result = await extract_all_links(html="<<<<not html>>>>")
    assert result == {} or "extracted_links" in result


# ── get_pipeline registers built-in hooks ──


def test_get_pipeline_registers_extract_all_links():
    p = get_pipeline()
    hooks = p.list_hooks()
    assert "extract_all_links" in hooks["after_response"]
