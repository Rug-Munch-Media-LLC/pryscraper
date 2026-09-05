"""Player intelligence — lineups, live props, recent stats, streaks, matchups.

The bettor-facing layer on top of the raw odds/props engines. Answers the
questions that decide a player-prop bet *before* the price matters:

* **Who's starting?** — :func:`get_lineups` pulls the ESPN game summary for
  a team's next event and splits the rotation into starters / bench /
  probable pitchers, plus the injury report (questionable / doubtful / out)
  and a per-player minutes projection (season MPG, adjusted down for
  players coming back from injury).
* **What are the lines right now?** — :func:`get_player_props_live` scans
  The Odds API player markets across books for one player and derives a
  cross-book movement signal (``up`` / ``down`` / ``steady``) by comparing
  each book's line against the consensus median.
* **How has he been playing?** — :func:`get_player_recent_stats` pulls the
  ESPN game log for the last N games with per-game stats, averages, and a
  hot/cold trend versus the season average.
* **Is he on a streak?** — :func:`get_player_streaks` condenses the game
  log into a current streak (type, length), average-vs-season deltas, and
  an over/under prop trend.
* **Whole-team board** — :func:`get_team_player_props` aggregates every
  player prop on a team's next event into one list.
* **Matchup context** — :func:`get_props_vs_matchup` returns props for both
  teams in a matchup annotated with how the opponent defends each prop
  type (defensive ranking context from ESPN team stats when available).

Contract
--------
Every public function is async, never raises, and returns its documented
shape (``[]`` / ``{}`` on failure). HTTP goes through :mod:`httpx` with the
shared retry config from :mod:`sports_data.props_http`. Sources:

* **ESPN public APIs** (``site.api.espn.com`` / ``site.web.api.espn.com``)
  — no key, no quota: scoreboard, game summary, rosters, athlete search,
  game logs, team stats.
* **The Odds API** (``api.the-odds-api.com``) — real bookmaker player
  props; requires the ``PRY_ODDS_API_KEY`` env var (free tier). Without a
  key the props functions fall back to ESPN season-average estimates
  (``book="ESPN Estimate"``, no odds) exactly like :mod:`sports_data.props`.

Sport names match :mod:`sports_data.odds` (``nba``, ``nfl``, ``mlb``, ...).

Implementation lives in focused submodules:

* :mod:`datasets.sports_data.player_common` — shared ESPN transport,
  constants, team/event resolution.
* :mod:`datasets.sports_data.player_lineups` — lineups + injuries.
* :mod:`datasets.sports_data.player_props` — live props + team boards.
* :mod:`datasets.sports_data.player_stats` — game logs + streaks.
* :mod:`datasets.sports_data.player_matchup` — matchup defensive context.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.sports_data.player_lineups import (
    get_lineups as get_lineups,
)
from datasets.sports_data.player_matchup import (
    get_props_vs_matchup as get_props_vs_matchup,
)
from datasets.sports_data.player_props import (
    get_player_props_live as get_player_props_live,
    get_team_player_props as get_team_player_props,
)
from datasets.sports_data.player_stats import (
    get_player_recent_stats as get_player_recent_stats,
    get_player_streaks as get_player_streaks,
)

__all__ = [
    "get_lineups",
    "get_player_props_live",
    "get_player_recent_stats",
    "get_player_streaks",
    "get_props_vs_matchup",
    "get_team_player_props",
]
