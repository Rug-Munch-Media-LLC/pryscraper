"""Pry — X402Handler hook registries (``StateMixin`` slice).

Registration only: the hooks themselves are invoked from verify/settle.
"""

from __future__ import annotations

from typing import Any


class HooksMixin:
    """Hook registries for the x402 verify/settle pipeline."""

    _pre_settle_hooks: list[Any]
    _post_settle_hooks: list[Any]
    _pre_verify_hooks: list[Any]
    _post_verify_hooks: list[Any]
    _on_verify_failure_hooks: list[Any]

    def on_pre_settle(self, hook: Any) -> None:
        """Register a hook executed before settlement. Can abort by returning {"abort": True, "reason": "..."}."""
        self._pre_settle_hooks.append(hook)

    def on_post_settle(self, hook: Any) -> None:
        """Register a hook executed after successful settlement."""
        self._post_settle_hooks.append(hook)

    def on_pre_verify(self, hook: Any) -> None:
        """Register a hook executed before verification. Can abort by returning {"abort": True, "reason": "..."}."""
        self._pre_verify_hooks.append(hook)

    def on_post_verify(self, hook: Any) -> None:
        """Register a hook executed after successful verification."""
        self._post_verify_hooks.append(hook)

    def on_verify_failure(self, hook: Any) -> None:
        """Register a hook executed when verification fails (router error or unverified result)."""
        self._on_verify_failure_hooks.append(hook)
