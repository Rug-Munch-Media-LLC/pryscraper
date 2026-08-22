"""Fuzz tests for HTML parsing — catches crashes on malformed input."""

import json

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st


@given(html=st.text())
@settings(
    max_examples=500,
    deadline=2000,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_schema_extraction_never_crashes(html: str) -> None:
    """SchemaExtractor should never crash, regardless of HTML input."""
    try:
        from schema_extraction import SchemaExtractor

        extractor = SchemaExtractor()
        extractor.extract_jsonld(html)
        extractor.extract_all(html)
    except ImportError:
        pytest.skip("schema_extraction module not available")
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    except Exception as e:  # noqa: BLE001 - fuzz: any unexpected crash must fail the test
        pytest.fail(f"SchemaExtractor crashed on input: {e}")


@given(html=st.text())
@settings(
    max_examples=500,
    deadline=2000,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_network_extractors_never_crash(html: str) -> None:
    """Network-level HTML extraction functions should handle any input."""
    try:
        from network import (
            extract_api_calls_from_html,
            extract_json_ld,
            extract_nextjs_props,
            extract_nuxt_state,
        )

        extract_api_calls_from_html(html)
        extract_json_ld(html)
        extract_nextjs_props(html)
        extract_nuxt_state(html)
    except ImportError:
        pytest.skip("network module not available")
    except (ValueError, TypeError, IndexError, KeyError):
        pass
    except Exception as e:  # noqa: BLE001 - fuzz: any unexpected crash must fail the test
        pytest.fail(f"Network extractor crashed on input: {e}")


@given(html=st.text())
@settings(
    max_examples=500,
    deadline=3000,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_jsoncss_extraction_never_crashes(html: str) -> None:
    """JsonCssExtractionStrategy should handle any HTML gracefully."""
    try:
        from extraction import JsonCssExtractionStrategy

        strategy = JsonCssExtractionStrategy({"name": "fuzz", "base_selector": "", "fields": []})
        strategy.extract(html)
    except ImportError:
        pytest.skip("extraction module not available")
    except (ValueError, TypeError):
        pass
    except Exception as e:  # noqa: BLE001 - fuzz: any unexpected crash must fail the test
        pytest.fail(f"JsonCssExtractionStrategy crashed on input: {e}")


@given(url=st.text(min_size=1, max_size=2000))
@settings(max_examples=200, deadline=3000)
def test_url_parser_never_crashes(url: str) -> None:
    """url_guard.validate_url must never CRASH on any input.

    Malformed URLs are routine in scraping. The guard's documented contract is
    to reject unsafe/malformed input with InvalidRequestError — only an
    unexpected exception (TypeError, IndexError, ...) is a real bug.

    Note: the previous version of this test fuzzed stdlib urlparse directly and
    asserted it never raises — an impossible property (CPython raises
    ValueError on '//['). Fuzz the production guard instead.
    """
    import contextlib

    from errors import InvalidRequestError
    from url_guard import validate_url

    # safe rejection — the documented contract; anything else propagates
    with contextlib.suppress(InvalidRequestError):
        validate_url(url, resolve_dns=False)  # no DNS in fuzzing
