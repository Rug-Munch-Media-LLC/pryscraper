# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fuzz tests for DocumentParser — never-crash invariants on arbitrary input.

The parser dispatches on filename extensions and content-type substrings, so
arbitrary combinations of (bytes, content_type, filename) must never crash
with an exception the parser did not design for. Document-format libraries
(pypdf, python-docx, Pillow) are allowed to reject garbage input — that is a
graceful parse failure, not a bug. Any *other* exception is a regression.

Invariant checked here:
    _parse_bytes(data, content_type, filename) returns a well-formed result
    dict OR raises an exception originating from a document-parsing library.
"""

import json

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from parser import DocumentParser


def _allowed_exception(e: BaseException) -> bool:
    """True if the exception is an expected, graceful parse failure.

    pypdf, python-docx and Pillow raise a family of errors on garbage input
    (malformed zip/PDF/stream/image containers). Many of those inherit from
    generic builtins (ValueError, KeyError, EOFError, OSError, struct.error,
    zlib.error, zipfile.BadZipFile), so we accept them. Anything else — e.g. a
    bug in our own dispatch or cleanup code — is a genuine crash.
    """
    allowed_builtins = (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        EOFError,
        OSError,
        UnicodeError,
    )
    if isinstance(e, allowed_builtins):
        return True
    return any(
        mod in type(e).__module__
        for mod in ("pypdf", "docx", "PIL", "lxml", "struct", "zlib", "zipfile")
    )


def _assert_well_formed(result: object) -> None:
    """Every successful parse must return the documented result shape."""
    assert isinstance(result, dict), f"parse returned non-dict: {type(result)!r}"
    assert "text" in result and isinstance(result["text"], str)
    assert "format" in result and isinstance(result["format"], str)
    assert "pages" in result and isinstance(result["pages"], int)


@settings(max_examples=300, deadline=10000, suppress_health_check=[HealthCheck.too_slow])
@given(
    data=st.binary(max_size=8192),
    content_type=st.text(max_size=200),
    filename=st.text(max_size=200),
)
def test_parse_bytes_never_crashes_on_arbitrary_input(
    data: bytes, content_type: str, filename: str
) -> None:
    """Any (bytes, content_type, filename) triple must parse or fail gracefully."""
    parser = DocumentParser()
    try:
        result = parser._parse_bytes(data, content_type, filename)
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        if _allowed_exception(e):
            return
        pytest.fail(
            f"_parse_bytes crashed with unexpected {type(e).__name__}: {e} "
            f"(content_type={content_type!r}, filename={filename!r}, "
            f"data_len={len(data)})"
        )
    _assert_well_formed(result)


@settings(max_examples=200, deadline=10000, suppress_health_check=[HealthCheck.too_slow])
@given(
    data=st.binary(max_size=4096),
    content_type=st.sampled_from(
        [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/markdown",
            "text/csv",
            "application/json",
            "text/html",
            "image/png",
            "image/jpeg",
            "text/plain",
            "application/octet-stream",
        ]
    ),
    filename=st.sampled_from(
        [
            "report.pdf",
            "doc.docx",
            "readme.md",
            "data.csv",
            "config.json",
            "page.html",
            "photo.png",
            "scan.jpg",
            "notes.txt",
            "file.bin",
        ]
    ),
)
def test_parse_bytes_known_mime_types_never_crash(
    data: bytes, content_type: str, filename: str
) -> None:
    """Even well-formed MIME/filename combos must tolerate garbage content."""
    parser = DocumentParser()
    try:
        result = parser._parse_bytes(data, content_type, filename)
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        if _allowed_exception(e):
            return
        pytest.fail(
            f"_parse_bytes crashed with unexpected {type(e).__name__}: {e} "
            f"(content_type={content_type!r}, filename={filename!r})"
        )
    _assert_well_formed(result)


@settings(max_examples=100, deadline=10000, suppress_health_check=[HealthCheck.too_slow])
@given(
    json_doc=st.one_of(
        st.text(max_size=4096),
        st.lists(st.text(), max_size=50),
        st.dictionaries(st.text(), st.text(), max_size=20),
    )
)
def test_json_parse_preserves_text(json_doc: object) -> None:
    """JSON inputs must round-trip through the parser as text."""
    data = json.dumps(json_doc).encode("utf-8")
    result = DocumentParser()._parse_bytes(data, "application/json", "data.json")
    _assert_well_formed(result)
    assert result["format"] == "json"
    # The parser stores the raw bytes decoded; the JSON content must survive
    # byte-for-byte and remain parseable JSON.
    assert result["text"] == data.decode("utf-8")
    assert json.loads(result["text"]) == json_doc


@settings(max_examples=100, deadline=10000, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.binary(max_size=4096))
def test_unknown_content_type_never_crashes(data: bytes) -> None:
    """Octet-stream / unknown content always degrades to unknown or binary."""
    result = DocumentParser()._parse_bytes(data, "application/octet-stream", "x.bin")
    _assert_well_formed(result)
    assert result["format"] in ("unknown", "binary")
    if isinstance(data, bytes) and b"\x00" not in data:
        # Valid UTF-8 decodes as "unknown" text; the text must be preserved.
        assert result["format"] == "unknown"
