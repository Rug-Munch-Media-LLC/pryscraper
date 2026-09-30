# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Helpers that make environment-sensitive assertions mean what they say.

Two pieces of ambient state leak into settings-backed reads and make a suite
report on the machine instead of on the code:

* **LLM provider API keys.** ``_llm_capability()`` enumerates every provider
  with a truthy ``settings.<x>_api_key`` and joins the NAMES into its detail
  string, and ``register_default_providers()`` registers a provider per truthy
  key. An operator's exported ``OPENAI_API_KEY`` therefore appends "openai" to
  a report a test asserts is exactly "openrouter", and adds a provider to a
  fallback chain a test asserts was filtered down to one entry. Neither test
  was wrong about the product; both were reporting the host's env.

* **The persistent tier-health store.** ``tier_health`` records every tier
  attempt to a JSON file that survives the process, and then skips tiers with
  zero wins over ``MIN_EVIDENCE_ATTEMPTS``. A test that drives
  ``UltimateScraper.scrape`` writes to that file and reads its own writes back
  on the next run, so after three runs a mocked-failing tier is silently
  dropped from the chain and the assertions that it IS attempted start
  failing. The autouse ``pry_tier_health_isolation`` fixture in ``conftest``
  handles that one suite-wide; this module is the settings-side equivalent.

These are DI seams, not workarounds: every provider key is a field on the
``settings`` singleton, and the tier-health path is a module global that both
``record()`` and ``should_skip()`` resolve at call time (so nothing depends on
import order).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pry.core.settings import settings

if TYPE_CHECKING:
    import pytest

#: Every provider key ``register_default_providers`` consults, in the same
#: order as the registration map in ``llm/providers/defaults.py``.
LLM_PROVIDER_KEY_FIELDS: tuple[str, ...] = (
    "openai_api_key",
    "anthropic_api_key",
    "gemini_api_key",
    "cohere_api_key",
    "mistral_api_key",
    "openrouter_api_key",
    "kilocode_api_key",
    "deepseek_api_key",
    "groq_api_key",
    "kimi_api_key",
    "nvidia_api_key",
    "nous_api_key",
    "zai_api_key",
    "cerebras_api_key",
    "minimax_api_key",
    "siliconflow_api_key",
    "opencode_zen_api_key",
)

#: The subset ``_llm_capability()`` reports on (capabilities/services.py).
#: Kept separate from the full list because that function reads exactly these
#: four — a capability report cannot mention a provider it never looks at.
LLM_CAPABILITY_KEY_FIELDS: tuple[str, ...] = (
    "openrouter_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "cohere_api_key",
)


def clear_llm_keys(monkeypatch: pytest.MonkeyPatch, fields: tuple[str, ...]) -> None:
    """Zero every named provider key so only what a test sets is visible."""
    for field in fields:
        monkeypatch.setattr(settings, field, "")


def set_llm_keys(monkeypatch: pytest.MonkeyPatch, fields: tuple[str, ...], **keys: str) -> None:
    """Set exactly the named provider keys, zeroing the rest of ``fields``.

    Zeroing first is the point: both readers enumerate every key they can find,
    so a test that sets one key while the box exports another sees both and
    fails for a reason unrelated to the behaviour under test.
    """
    clear_llm_keys(monkeypatch, fields)
    for field, value in keys.items():
        monkeypatch.setattr(settings, field, value)


def only_openrouter_llm(monkeypatch: pytest.MonkeyPatch, key: str = "fake-key-openrouter") -> None:
    """Make openrouter the single reported LLM provider.

    A capability report asserts an exact provider list, so the other keys must
    be zeroed rather than inherited from whatever the host exports.
    """
    set_llm_keys(monkeypatch, LLM_CAPABILITY_KEY_FIELDS, openrouter_api_key=key)


def no_llm_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report no LLM provider at all, whatever the host exports."""
    clear_llm_keys(monkeypatch, LLM_CAPABILITY_KEY_FIELDS)
