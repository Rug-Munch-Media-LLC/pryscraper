"""Eval-local pytest config: register the live marker without touching repo config."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: hits the public internet; skipped unless SCRAPE_MATRIX_LIVE=1"
    )
