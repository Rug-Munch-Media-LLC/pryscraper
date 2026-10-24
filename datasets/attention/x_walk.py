"""Breadth-first lookup of the nearest X user node."""

from __future__ import annotations

from typing import Any

MAX_WALK_DEPTH = 3
MAX_WALK_NODES = 300

__all__ = ["nearest_user"]


def _user_hit(current: Any) -> dict[str, Any] | None:
    """Return a node's own user result, if present."""
    if not isinstance(current, dict):
        return None
    users = current.get("user_results")
    if isinstance(users, dict) and isinstance(users.get("result"), dict):
        return users["result"]
    return None


def _enqueue_children(current: Any, depth: int, queue: list[tuple[Any, int]]) -> None:
    """Add a node's children when the walk has depth left."""
    if depth >= MAX_WALK_DEPTH:
        return
    if isinstance(current, dict):
        queue.extend((child, depth + 1) for child in current.values())
    elif isinstance(current, list):
        queue.extend((child, depth + 1) for child in current)


def nearest_user(node: dict[str, Any]) -> dict[str, Any]:
    """Breadth-first search for the nearest ``user_results.result`` node."""
    queue: list[tuple[Any, int]] = [(node, 0)]
    visited = 0
    while queue and visited < MAX_WALK_NODES:
        current, depth = queue.pop(0)
        visited += 1
        hit = _user_hit(current)
        if hit is not None:
            return hit
        _enqueue_children(current, depth, queue)
    return {}
