"""Healthcare data package — clinical trials, drug pricing, insurance.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`healthcare_data.clinical_trials` — clinicaltrials.gov API v2
  (free, no-auth): keyword search + NCT lookup.
* :mod:`healthcare_data.drug_pricing` — NADAC public files + best-effort
  GoodRx scrape for US drug prices.
* :mod:`healthcare_data.insurance` — insurance quote feasibility probe
  (car/home, captcha-gated → documented ``available: False``) + public
  aggregate rate tables.

Sibling modules owned by other agents are re-exported automatically when
present; this package always works standalone with just these three.

Example:
    >>> from healthcare_data import search_trials, get_drug_price
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import pkgutil

from datasets.healthcare_data.clinical_trials import get_trial, search_trials
from datasets.healthcare_data.drug_pricing import get_drug_price
from datasets.healthcare_data.insurance import get_insurance_quotes, get_insurance_rate_table

__all__ = [
    "get_drug_price",
    "get_insurance_quotes",
    "get_insurance_rate_table",
    "get_trial",
    "search_trials",
]

# ── Re-export public callables from sibling submodules ───────────────────
# The lead spec calls for the package to expose "the 3 modules' public
# functions". clinical_trials / drug_pricing / insurance (owned by this
# agent) are imported statically above; any sibling modules created in
# parallel (e.g. by other agents) are imported and their public callables
# re-exported here. Names already in __all__ are never overwritten, so the
# canonical interface stays stable.
_STATIC_MODULES = ("clinical_trials", "drug_pricing", "insurance")
for _module_info in pkgutil.iter_modules(__path__):
    if _module_info.name.startswith("_") or _module_info.name in _STATIC_MODULES:
        continue
    _mod = importlib.import_module(f"{__name__}.{_module_info.name}")
    for _attr in dir(_mod):
        if _attr.startswith("_") or _attr in __all__:
            continue
        _obj = getattr(_mod, _attr)
        if callable(_obj) and str(getattr(_obj, "__module__", "")).startswith(__name__):
            globals()[_attr] = _obj
            __all__.append(_attr)
