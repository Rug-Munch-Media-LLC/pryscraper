"""Tests for pipeline hook system."""

from pipeline import HOOK_POINTS, Pipeline


def test_pipeline_init() -> None:
    p = Pipeline()
    assert len(p.list_hooks()) == len(HOOK_POINTS)


def test_pipeline_register() -> None:
    p = Pipeline()

    def my_hook(**kwargs: object) -> dict[str, object]:
        return {"custom": "value"}

    p.register("before_scrape", my_hook)
    hooks = p.list_hooks()
    assert "my_hook" in list(hooks["before_scrape"])


def test_pipeline_clear() -> None:
    p = Pipeline()

    def my_hook(**kwargs: object) -> dict[str, object]:
        return {}

    p.register("before_scrape", my_hook)
    p.clear("before_scrape")
    assert len(p.list_hooks()["before_scrape"]) == 0


def test_pipeline_clear_all() -> None:
    p = Pipeline()

    def my_hook(**kwargs: object) -> dict[str, object]:
        return {}

    p.register("before_scrape", my_hook)
    p.clear()
    for point in HOOK_POINTS:
        assert len(p.list_hooks()[point]) == 0


def test_pipeline_invalid_hook_point() -> None:
    p = Pipeline()
    import pytest

    def my_hook(**kwargs: object) -> dict[str, object]:
        return {}

    with pytest.raises(ValueError, match="Unknown hook point"):
        p.register("invalid_point", my_hook)
