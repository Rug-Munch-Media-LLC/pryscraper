"""Circuit-breaker open/half-open state survives a store reload.

Split out of ``test_tier_health_scope.py`` (concern + 200-line cap): breaker
persistence shares the store's TTL, not the tier-health policy.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import time
from typing import Any

from pry.engine.resilience import ResilienceRegistry
from pry.engine.resilience_circuit import CircuitState


def test_circuit_breaker_open_state_survives_store_reload(tmp_path: Any) -> None:
    """Breaker open/half-open state persists with the same TTL as tier health.

    ``last_failure_at`` + ``recovery_seconds`` are serialized together, so a
    restart does not resurrect a tripped service: the remaining cooldown is
    identical to the one the previous process would have enforced.
    """
    path = tmp_path / "resilience_state.json"
    before = ResilienceRegistry(persist_path=path, method_stats=False)
    cb = before.breaker("openrouter")
    cb.state = CircuitState.OPEN
    cb.failures = 7
    cb.last_failure_at = time.time()
    cb.recovery_seconds = 120.0
    assert before.save() is True

    after = ResilienceRegistry(persist_path=path, method_stats=False)
    restored = after.breaker("openrouter")
    assert restored.state == CircuitState.OPEN
    assert restored.failures == 7
    assert restored.recovery_seconds == 120.0
    # TTL is still in force: the cooldown did not reset on reload.
    assert restored.is_allowed() is False


def test_circuit_breaker_half_open_state_survives_reload(tmp_path: Any) -> None:
    path = tmp_path / "resilience_state.json"
    before = ResilienceRegistry(persist_path=path, method_stats=False)
    cb = before.breaker("ollama")
    cb.state = CircuitState.HALF_OPEN
    cb.half_open_attempts = 1
    assert before.save() is True

    restored = ResilienceRegistry(persist_path=path, method_stats=False).breaker("ollama")
    assert restored.state == CircuitState.HALF_OPEN
    assert restored.half_open_attempts == 1
