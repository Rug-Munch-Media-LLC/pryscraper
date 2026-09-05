"""Re-export prediction_markets functions for the sports dispatcher.

The sports dispatcher (call_sports_tool) imports modules as
``sports_data.{module_name}``, so prediction market tools need a
re-export here even though the real module lives in
``datasets.prediction_markets``.
"""

from __future__ import annotations

from datasets.prediction_markets import (
    get_prediction_market,
    get_prediction_markets,
)

__all__ = ["get_prediction_market", "get_prediction_markets"]
