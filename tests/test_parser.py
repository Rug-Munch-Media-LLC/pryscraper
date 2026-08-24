# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from pry.engine.parser import DocumentParser


def test_parse_bytes_text() -> None:
    p = DocumentParser()
    result = p._parse_bytes(b"Hello world", "text/plain", "hello.txt")
    assert result["format"] == "text"
    assert "Hello" in result["text"]


def test_parse_bytes_json() -> None:
    p = DocumentParser()
    result = p._parse_bytes(b'{"key": "value"}', "application/json", "data.json")
    assert result["format"] == "json"
    assert "key" in result["text"]


def test_parse_bytes_csv() -> None:
    p = DocumentParser()
    result = p._parse_bytes(b"a,b,c\n1,2,3", "text/csv", "data.csv")
    assert result["format"] == "csv"


def test_parse_bytes_markdown() -> None:
    p = DocumentParser()
    result = p._parse_bytes(b"# Hello\n\nWorld", "text/markdown", "readme.md")
    assert result["format"] == "markdown"


def test_parse_bytes_unknown() -> None:
    p = DocumentParser()
    result = p._parse_bytes(b"some random data", "application/octet-stream", "data.bin")
    assert result["format"] in ("unknown", "binary")


def test_parse_bytes_html_fallback() -> None:
    p = DocumentParser()
    html = b"<html><body><p>Hello world</p></body></html>"
    result = p._parse_bytes(html, "text/html", "page.html")
    assert result["format"] == "html"
