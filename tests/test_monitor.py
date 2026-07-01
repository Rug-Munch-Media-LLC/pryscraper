"""Tests for content monitors."""

from monitor import ChangeJudger


async def _judge(previous: str, current: str, goal: str = "") -> dict:
    j = ChangeJudger()
    return await j.judge(previous, current, goal)


def test_judger_no_goal_no_change() -> None:
    import asyncio

    result = asyncio.run(_judge("same content", "same content"))
    assert result["meaningful"] is False


def test_judger_no_goal_with_change() -> None:
    import asyncio

    result = asyncio.run(_judge("old content", "new content"))
    assert result["meaningful"] is True


def test_judger_with_goal_relevant() -> None:
    import asyncio

    result = asyncio.run(
        _judge("Company has 10 employees", "Company has 500 employees", goal="employee count")
    )
    assert result["meaningful"] is True


def test_judger_with_goal_irrelevant() -> None:
    import asyncio

    result = asyncio.run(
        _judge("Company has 10 employees", "Company is located in NY", goal="employee count")
    )
    assert result["meaningful"] is False


def test_judger_empty_previous() -> None:
    import asyncio

    result = asyncio.run(_judge("", "New content here"))
    assert result["meaningful"] is True
