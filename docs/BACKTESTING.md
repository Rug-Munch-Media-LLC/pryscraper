# Backtesting in Pry

There are **two different things called "backtest"** in this repo. They measure
different questions and must not be quoted interchangeably.

| Surface | Path | What it actually computes | Trust |
|---|---|---|---|
| Strategy backtest | `scripts/backtest_strategy.py` (+ `backtest_core`, `backtest_data`) | Walk-forward P&L of a betting signal on settled events, with costs and honest metrics | Measured; synthetic data unless you supply CSV |
| Scrape-ladder "backtest" | `scripts/backtest_ladder.py`, `ladder_backtest.py`, `ladder_aggregate.py` | Success rate and latency of the scrape tier chain against 10 labelled sources | Measured against a **deployed** Pry; not a P&L backtest |
| Historical odds fetch | `datasets/sports_data/historical.py` | Pulls closing-line snapshots (paid API) | Data only — computes nothing |
| CLV / EV / Kelly helpers | `datasets/sports_data/{clv,ev,bankroll}.py` | Per-bet math on live quotes | Correct primitives, never joined to outcomes |

Nothing in the repo previously joined **odds at bet time** to **settled
outcomes**. `historical.py` says "backtesting data" but returns snapshots with no
results, so no P&L could be computed from it. The strategy backtest closes that
gap; it is new code and is explicit about what it does not model.

---

## Strategy backtest

### Run

```bash
# Deterministic synthetic market (default). Same args -> same fingerprint.
python3 scripts/backtest_strategy.py --events 2000 --signal model --seed 7

# Only bet when the model's edge clears costs.
python3 scripts/backtest_strategy.py --signal model --min-edge 0.02

# Kelly staking (quarter Kelly, capped at 2% of bankroll).
python3 scripts/backtest_strategy.py --signal model --sizing kelly

# Blind baseline: bet every price. Expected ROI is about -margin.
python3 scripts/backtest_strategy.py --signal market --min-edge -1

# Prove the causality guard works: this MUST exit 1, never print a number.
python3 scripts/backtest_strategy.py --signal lookahead

# A real series (see CSV schema below).
python3 scripts/backtest_strategy.py --csv series.csv --train 300 --test 100

# Machine-readable.
python3 scripts/backtest_strategy.py --json
```

Exit codes: `0` measured and clean, `1` measured but flagged (or the signal read
the future), `2` unmeasurable (no data / series too short). A run that cannot
measure never returns `0`.

### Method

- **Causality.** Signals receive a `MarketView` containing only `event_id`, `ts`,
  `odds`, and pre-event `features`. `won`, `outcome` and `closing_odds` raise
  `LookaheadError` on access. The closing line is future information: it is used
  only for the post-hoc CLV metric.
- **Walk-forward.** Rolling folds of `train → purge → embargo → test`
  (defaults 400 / 5 / 10 / 200). The purge drops the last 5 training events; the
  embargo skips the next 10, so no test outcome can reach a training window.
  Training data is never shuffled.
- **Costs.** Defaults are non-zero: 2% commission on net winnings and 25 bps of
  price slippage. `Costs.net_odds()` is strictly below the quoted price whenever
  either is non-zero.
- **Sizing.** `flat` (1% of bankroll) or `kelly` (quarter Kelly, capped at 2%),
  and no bet is placed below `--min-edge` (default 0.0 — negative-EV bets are
  refused).
- **Reproducibility.** The synthetic generator is seeded; every run prints a data
  fingerprint. `--json` carries the seed, fingerprint and per-fold split.

### Metrics (definitions, because they are where backtests lie)

| Metric | Definition |
|---|---|
| `roi` | `sum(pnl) / sum(stake)` — stake-weighted, not the mean of per-bet ROIs |
| `hit_rate` | wins / bets |
| `CLV` | mean of `bet_odds / closing_odds - 1` across placed bets |
| `brier` | mean of `(signal_prob - outcome)^2` — calibration of the signal |
| `max_drawdown` | peak-to-trough of the equity path, as a fraction of the peak |
| `sharpe.per_bet` | mean / stdev of **portfolio return per event** (`pnl / equity_before`) |
| `sharpe.annualised` | `per_bet * sqrt(bets_per_year)`, where `bets_per_year` is **observed** from the timestamp span |

There is no hard-coded `sqrt(252)`. An event-driven strategy does not trade 252
times a year, and using the trading-day constant inflates the ratio. The
`bets_per_year` value is printed so the annualisation can be checked by hand.

### What is NOT modelled

- **Real data.** Offline there is no committed settled-outcome dataset. Every
  number produced without `--csv` is from a simulation whose true probabilities
  are known; it validates the harness, not a strategy.
- **Settlement rules.** Pushes, voids, half-wins, dead heats and rule changes are
  absent. Each event is a binary win/loss.
- **Bet-time availability.** `ts` is treated as the bet timestamp; in reality the
  price you take exists for a finite window, and limits may cap the stake.
- **Market impact and book limits.** Stakes never move the price.
- **Survivorship / selection.** The CSV loader uses every row you give it. If you
  export only events that had a closing line, you have already selected.
- **Line movement and steam.** No pre-close price path — one price per event.
- **Correlated bets.** Same-game parlays and simultaneous events are treated as
  independent; Sharpe and drawdown will be optimistic for correlated books.
- **Multiple testing.** Running 50 parameter sets and quoting the best one is not
  prevented. Split once, or use a held-out final window.

### CSV schema

```csv
event_id,ts,odds,closing_odds,won,prob
evt-1,2026-01-01T18:00:00Z,2.05,1.98,1,0.57
evt-2,2026-01-01T20:30:00Z,1.72,1.75,0,0.51
```

`ts` is epoch seconds or ISO-8601. `won` accepts `1/0`, `true/false`, `win/loss`.
`prob` is optional and becomes the model's pre-event estimate (`features[0]`).
Duplicate `event_id` values are rejected; rows are sorted by `ts`.

### Tests

`tests/test_backtest_strategy.py` — 14 tests. The load-bearing ones:

- a signal that reads `won` or `closing_odds` raises (and the CLI exits `1`);
- a clean signal runs and produces finite metrics;
- train and test are separated by exactly `purge + embargo` events;
- costs strictly reduce ROI;
- Sharpe annualises from observed `bets_per_year`, not 252;
- a 100%-hit strategy is flagged, a 55%-hit one is not;
- blind betting on the synthetic market loses roughly the book margin
  (`-8% < ROI < -2%` with a 4.5% margin), which makes the generator falsifiable.

### Observed output (seed 7, 2000 events, 7 folds)

Model signal, flat 1%, costs on:

```text
== RESULT    bets=505 hit=46.5% turnover=5.3259 pnl=-0.0722 roi=-1.36%
== METRICS   CLV=-0.06% brier=0.205 max_dd=31.0%
== SHARPE    per_bet=-0.005 annualised=-0.07 bets_per_year=265
```

Blind market baseline (`--min-edge -1`): `bets=1400 roi=-3.24%`, which is the
book margin plus costs — the expected loss, not a discovery.

Lookahead canary: `LOOKAHEAD: signal read 'won'` and exit `1`.

These numbers are **trustworthy as measurements of this harness on this
simulation**. They are **not evidence of a profitable strategy**: the "model"
feature is a noisy estimate of a probability the generator knows, and even it
loses money after costs on this seed.

---

## Scrape-ladder backtest

```bash
python3 scripts/backtest_ladder.py                # live, against a deployed Pry
python3 scripts/backtest_ladder.py --compare      # diff vs committed baseline
python3 scripts/backtest_ladder.py --offline      # replay the fixture, no network
```

Exit codes: `0` measured and clean, `1` measured and regressed, `2` unmeasured
(Pry unreachable, or the fixture does not describe this source set). The median
of `--repeat` runs is the baseline, never a single lucky run.

**Known defect, fixed here:** the committed `data/ladder_baseline.json` is a
one-source placeholder (`a.example`, success 1.0), while `SOURCES` defines ten.
`--compare` against it would report a real 9/10 run as a "regression". The CLI
now refuses cross-source-set comparison and exits `2` with an explicit message.
Record a genuine baseline with `--update-baseline` against a live Pry before
using `--compare` as a gate.

## What would make the strategy numbers real

1. A settled-outcome dataset with **bet-time** prices and closing prices
   (not just closing snapshots). The Odds API historical endpoint is paid; export
   it once and commit the CSV.
2. Settlement rules per market/league, including pushes and voids.
3. A held-out final window never touched during development; report it once.
4. Correlation-aware staking for same-day/same-game exposure.
