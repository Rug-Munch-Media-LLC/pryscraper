"""Pay-per-event charging helpers for the actor runner."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BillingMixin:
    """push + charge with the primary event, and the aborting flush."""

    async def push_and_charge(self, actor: Any, item: dict[str, Any]) -> bool:
        """Push one item with the primary event attached.

        Returns False when the user spending limit says stop.
        """
        # SDK v4: event charging is keyword-only (positional broke at runtime:
        # "push_data() takes 2 positional arguments but 3 were given").
        charge_result = await actor.push_data(item, charged_event_name=self.config.primary_event)
        # push_data returns a ChargeResult when an event name is given.
        if charge_result is not None and getattr(
            charge_result, "event_charge_limit_reached", False
        ):
            self.stats.limit_reached = True
            return False
        if item.get("status") == "ok":
            self.stats.pushed_ok += 1
        else:
            self.stats.pushed_error += 1
        return True

    def on_aborting(self) -> None:
        """Flush completed-but-unbilled work inside the 30s window."""
        flushed = len(self._pending)
        self._pending.clear()
        self.stats.aborted_flushed += flushed
        logger.warning(
            "ppe_aborting_flush",
            extra={"flushed": flushed, "stats_pushed_ok": self.stats.pushed_ok},
        )
