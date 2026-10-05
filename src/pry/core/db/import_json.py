"""Pry - one-shot JSON store -> SQL importer.

Reads the legacy JSON/JSONL stores under ``$PRY_DATA_DIR`` and writes them
into the SQL tables. Idempotent: re-running with the same data is safe
(upsert-style pattern via the unique constraints on ``_id`` columns).

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pry.core.db.import_json_detail_steps import (
    add_actor_rows,
    add_referral_click_rows,
    add_referral_conversion_rows,
    add_referral_in_app_rows,
)

# File iterators and per-store steps live in sibling modules; both are
# re-exported here because callers and tests import them FROM THIS MODULE
# (identical objects, not copies).
from pry.core.db.import_json_iterators import (
    _iter_json_files,
    _iter_jsonl,
)
from pry.core.db.import_json_steps import (
    add_account_rows,
    add_agency_rows,
    add_intel_rows,
    add_monitor_rows,
    add_pipeline_rows,
    add_quality_rows,
    add_session_rows,
    add_structure_rows,
)
from pry.core.db.session import session_scope
from pry.core.paths import PRY_DATA_DIR

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Re-exported for callers/tests that import them FROM THIS MODULE.
__all__ = ["_iter_json_files", "_iter_jsonl", "import_json_stores"]


def import_json_stores(data_dir: Path | None = None) -> dict[str, int]:
    """One-shot importer: read all JSON stores and write to the SQL tables.

    Returns a dict of {store_name: row_count_imported}.

    Idempotent: re-running with the same data is safe (uses upsert-style
    pattern via the unique constraints on _id columns).
    """
    data_dir = data_dir or PRY_DATA_DIR
    counts: dict[str, int] = {}

    with session_scope() as s:
        counts["quality"] = add_quality_rows(s, data_dir)
        counts["intel"] = add_intel_rows(s, data_dir)
        counts["monitors"] = add_monitor_rows(s, data_dir)
        counts["accounts"] = add_account_rows(s, data_dir)
        counts["actors"] = add_actor_rows(s, data_dir)
        counts["pipelines"] = add_pipeline_rows(s, data_dir)
        counts["sessions"] = add_session_rows(s, data_dir)
        counts["agency"] = add_agency_rows(s, data_dir)
        counts["structure"] = add_structure_rows(s, data_dir)
        counts["referral_clicks"] = add_referral_click_rows(s, data_dir)
        counts["referral_conversions"] = add_referral_conversion_rows(s, data_dir)
        counts["referral_in_app_usage"] = add_referral_in_app_rows(s, data_dir)

    return counts
