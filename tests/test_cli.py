"""Tests for cli.py — Pry command-line interface.
Tests helpers, command functions, and Click CLI group.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch

import httpx
import pytest
import respx

import pry.misc.cli as cli
from pry.misc.cli import (
    BOLD,
    GREEN,
    NC,
    RED,
    VERSION,
    YELLOW,
    _api,
    _print_usage,
    _req,
    _spinner,
    cmd_batch,
    cmd_crawl,
    cmd_migrate,
    cmd_open,
    cmd_parse,
    cmd_screenshot,
    cmd_watch,
)

# ── Helpers ──


def test_api_default():
    with patch.dict("os.environ", clear=True):
        assert _api() == "http://localhost:8005"


def test_api_from_env():
    with patch.dict("os.environ", {"PRY_URL": "http://custom:9000"}):
        assert _api() == "http://custom:9000"


def test_version():
    assert VERSION == "3.0.0"


def test_colors():
    assert NC == "\033[0m"
    assert BOLD == "\033[1m"
    assert RED == "\033[91m"
    assert GREEN == "\033[92m"
    assert YELLOW == "\033[93m"


@respx.mock
def test_req_get():
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.get(f"{api_url}/v1/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        result = _req("GET", "/v1/health")
        assert result["status"] == "ok"


@respx.mock
def test_req_post():
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/scrape").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        result = _req("POST", "/v1/scrape", {"url": "http://x.com"})
        assert result["success"] is True


def test_req_connect_error():
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}), pytest.raises(SystemExit):
        _req("GET", "/v1/health")


@respx.mock
def test_req_http_429():
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.get(f"{api_url}/v1/health").mock(
            return_value=httpx.Response(429, text="Rate limited")
        )
        with pytest.raises(SystemExit):
            _req("GET", "/v1/health")


@respx.mock
def test_req_http_500():
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.get(f"{api_url}/v1/health").mock(
            return_value=httpx.Response(500, text="Server Error")
        )
        with pytest.raises(SystemExit):
            _req("GET", "/v1/health")


def test_print_usage():
    _print_usage()


def test_spinner():
    gen = _spinner("test spinner")
    assert gen is not None
    # _spinner returns a stop function; call it so the daemon thread does not
    # leak past the test and deadlock interpreter shutdown.
    gen()


# ── cmd_* functions ──


@respx.mock
@patch("builtins.print")
def test_cmd_open(mock_print):
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/scrape").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"markdown": "# Hello\n\nWorld", "method": "direct"},
                },
            )
        )
        cmd_open("http://example.com")
        mock_print.assert_called()


@respx.mock
@patch("builtins.print")
def test_cmd_open_with_schema(mock_print):
    api_url = "http://localhost:8005"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"fields": ["title"]}, f)
        schema_path = f.name
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/scrape").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"markdown": "data", "method": "schema"},
                },
            )
        )
        cmd_open("http://example.com", schema_path=schema_path)
        mock_print.assert_called()
    os.unlink(schema_path)


@respx.mock
@patch("builtins.print")
def test_cmd_open_empty(mock_print):
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/scrape").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"markdown": "", "method": "direct"},
                },
            )
        )
        cmd_open("http://example.com")
        mock_print.assert_called()


@respx.mock
@patch("builtins.print")
def test_cmd_watch(mock_print):
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/watch").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"status": "registered", "version": 1},
                },
            )
        )
        cmd_watch("http://example.com", webhook="http://hook.com")
        mock_print.assert_called()


@respx.mock
@patch("builtins.print")
def test_cmd_watch_fail(mock_print):
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/watch").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": False,
                    "error": "Watch failed",
                },
            )
        )
        cmd_watch("http://example.com")
        mock_print.assert_called()


@respx.mock
@patch("builtins.print")
def test_cmd_crawl(mock_print):
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/crawl").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "pages": [
                            {"title": "Page 1", "method": "direct"},
                            {"title": "Page 2", "method": "direct"},
                        ]
                    },
                },
            )
        )
        cmd_crawl("http://example.com", max_pages=2)
        mock_print.assert_called()


@respx.mock
@patch("builtins.print")
def test_cmd_crawl_with_output(mock_print):
    api_url = "http://localhost:8005"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as _tf:
        outfile = _tf.name
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/crawl").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"pages": [{"title": "Page", "method": "direct"}]},
                },
            )
        )
        cmd_crawl("http://example.com", output=outfile)
        mock_print.assert_called()
        assert os.path.exists(outfile)
        os.unlink(outfile)


@respx.mock
@patch("builtins.print")
def test_cmd_crawl_many_pages(mock_print):
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        pages = [{"title": f"Page {i}", "method": "direct"} for i in range(10)]
        respx.post(f"{api_url}/v1/crawl").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"pages": pages},
                },
            )
        )
        cmd_crawl("http://example.com", max_pages=10)
        mock_print.assert_called()


def test_cmd_batch_file_not_found():
    with patch("builtins.print"), pytest.raises(SystemExit):
        cmd_batch("/nonexistent/file.json")


@respx.mock
@patch("builtins.print")
def test_cmd_batch(mock_print):
    api_url = "http://localhost:8005"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("http://example.com\nhttp://test.com\n")
        batch_path = f.name
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/batch-file").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "results": [
                            {"url": "http://example.com", "status": "ok"},
                            {"url": "http://test.com", "status": "ok"},
                        ]
                    },
                },
            )
        )
        cmd_batch(batch_path)
        mock_print.assert_called()
    os.unlink(batch_path)


@respx.mock
@patch("builtins.print")
def test_cmd_batch_with_errors(mock_print):
    api_url = "http://localhost:8005"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("http://x.com\nhttp://y.com\nhttp://z.com\n")
        batch_path = f.name
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/batch-file").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "results": [
                            {"url": "http://x.com", "status": "ok"},
                            {"url": "http://y.com", "status": "ok"},
                            {"url": "http://z.com", "status": "error"},
                        ]
                    },
                },
            )
        )
        cmd_batch(batch_path)
        mock_print.assert_called()
    os.unlink(batch_path)


@respx.mock
@patch("builtins.print")
def test_cmd_parse(mock_print):
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/parse").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"text": "parsed text", "format": "pdf", "pages": 3},
                },
            )
        )
        cmd_parse("http://example.com/doc.pdf")
        mock_print.assert_called()


@respx.mock
@patch("builtins.print")
def test_cmd_screenshot(mock_print):
    import base64

    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/screenshot").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"screenshot": base64.b64encode(b"fake-img-data").decode()},
                },
            )
        )
        cmd_screenshot("http://example.com")
        mock_print.assert_called()


@respx.mock
@patch("builtins.print")
def test_cmd_screenshot_no_data(mock_print):
    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/screenshot").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"screenshot": ""},
                },
            )
        )
        with pytest.raises(SystemExit):
            cmd_screenshot("http://example.com")


@respx.mock
@patch("builtins.print")
def test_cmd_screenshot_to_file(mock_print):
    import base64

    api_url = "http://localhost:8005"
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as _tf:
        outfile = _tf.name
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/screenshot").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"screenshot": base64.b64encode(b"img-data").decode()},
                },
            )
        )
        cmd_screenshot("http://example.com", output=outfile)
        mock_print.assert_called()
        assert os.path.exists(outfile)
        os.unlink(outfile)


@patch("builtins.print")
def test_cmd_migrate(mock_print):
    """cmd_migrate delegates to db.run_migrations."""
    with patch("pry.core.db.run_migrations") as mock_migrations:
        cmd_migrate()
    mock_migrations.assert_called_once()


@patch("builtins.print")
def test_cmd_completions(mock_print):
    """Shell completions prints argcomplete setup instructions (no subprocess)."""
    import pry.misc.cli as cli_mod

    cli_mod.cmd_completions("bash")
    assert mock_print.called


@patch("builtins.print")
def test_cmd_completions_unknown_shell(mock_print):
    """Unknown shells print a friendly message, not an error."""
    import pry.misc.cli as cli_mod

    cli_mod.cmd_completions("powershell")
    assert mock_print.called


# ── Click CLI group ──


@pytest.mark.skipif("click" not in dir(), reason="click not installed")
def test_cli_group():
    from pry.misc.cli import main

    assert main is not None


def test_main_imports():

    assert cli.__doc__ is not None
    assert hasattr(cli, "main")
