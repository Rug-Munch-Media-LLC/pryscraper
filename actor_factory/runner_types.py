"""Runner value types shared by the actor factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol


class ActorLike(Protocol):
    """Structural subset of the Apify SDK Actor used by the runner."""

    async def get_input(self) -> dict[str, Any] | None: ...

    async def push_data(
        self, item: dict[str, Any], *, charged_event_name: str | None = None
    ) -> Any: ...

    async def charge(self, event_name: str) -> Any: ...

    def on(self, event: Any, handler: Any) -> Any: ...

    async def exit(self) -> Any: ...


@dataclass
class RunPlan:
    """Normalised actor input (urls, options, crawl limits)."""

    urls: list[str]
    options: dict[str, Any]
    max_depth: int = 0
    crawl_enabled: bool = False
    page_cap: int | None = None


@dataclass
class ActorRunConfig:
    primary_event: str
    default_output_format: str = "markdown"
    max_items: int = 10_000  # hard runaway cap independent of user limits
    processor_name: str | None = None  # actor_factory.processors registry key


@dataclass
class RunStats:
    pushed_ok: int = 0
    pushed_error: int = 0
    limit_reached: bool = False
    aborted_flushed: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
