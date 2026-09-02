# Aurum Edge — XAUUSD intraday research

A gold trading system built from measurement rather than chart intuition, plus
the research machinery used to test it.

This repository exists because the predecessor (`Aurum_Edge_V1_9_3.pine`, a
1,851-line TradingView strategy with 91 inputs) had a promising core idea and
three fatal problems: it modelled **zero trading costs**, it was fitted to a
**7.5-week window**, and it contained rules — such as a module that traded
setups scoring *exactly one point* below its own threshold — that were
discovered by bucketing backtest results rather than by any mechanism.

The goal here is not another strategy that looks good in a backtest. It is to
find out what is actually true about gold intraday, and to build only what
survives.

---

## What the research found

Every claim below is measured on ~4.7 years of XAUUSD tick data with real
historical bid/ask spreads. Details and reproduction commands follow.

### 1. Costs are the whole game

On 15-minute gold with conventional stop sizes, the round-trip cost is
**0.13–0.25 R per trade**. Several signals have a genuine positive gross edge
and still lose money net:

| Signal | Gross E[R] | Net E[R] | Cost drag |
|---|---|---|---|
| Trend pullback | **+0.247** | −0.008 | 0.255 |
| Stretch fade | +0.128 | −0.010 | 0.138 |
| NY opening range | +0.079 | −0.058 | 0.137 |

Cost drag equals `round_trip_cost / stop_distance`, so **the stop size is a
first-class risk parameter**, not a detail. The predecessor's minimum stop of
0.05 × ATR on the reaction module permitted stops of roughly **12 cents** —
smaller than the spread. Those trades book free 2R winners in a backtest and
are unconditionally unprofitable live.

### 2. Gold does not trend intraday

Lag-1 return autocorrelation is **negative at every timeframe tested**
(−0.018 to −0.035 across 5m/15m/30m/60m) and the Lo-MacKinlay variance ratio
is **0.95** — below 1, meaning mean reversion. Breakout logic fights the
process. Opening-range breakout on London tested at **−0.43 R/trade
(t = −3.77)**.

Most retail gold bots are breakout bots. This is why.

### 3. Limit-at-retrace entries lose more than they save

They earn half the spread instead of paying it — worth roughly 0.03–0.05 R —
but they only fill when price retraces, which selects for moves that are
already failing. Market-on-close confirmation beat limit entries at every
timeframe and stop size tested. The predecessor used limit entries everywhere.

### 4. No hour of the day has a directional edge

Across 24 simultaneous tests, **none** survives Bonferroni correction. Session
filtering is still justified — but by *liquidity*, not direction:

| UTC hour | avg 1m range | median spread | movement / cost |
|---|---|---|---|
| 13:00 | $1.34 | $0.38 | **3.5** |
| 08:00 | $0.80 | $0.39 | 2.1 |
| 04:00 | $0.40 | $0.41 | 1.0 |
| 22:00 | $0.37 | $0.51 | **0.7** |

Spread is roughly flat all day; movement varies 3.6×. Trading the Asian
session means paying close to the entire bar range in spread.

---

## What was kept from V1.9.3

Two ideas were good and survive in rebuilt form:

**Trend pullback** (your "Candidate B" core) has the strongest gross edge of
anything tested, at +0.247 R. Stripped of the 15-point score, the pattern zoo
and the RSI band — none of which were derived from data — the mechanism itself
holds up.

**Neutral reaction zones**, where a level's role is inferred from which side
price is currently accepting rather than being permanently stamped "supply" or
"demand", is a genuinely better formulation than the standard supply/demand
indicator. Rebuilt in `reaction_zone_retest` with three bugs fixed:

* age counted in **bars**, not wall-clock milliseconds (the original expired
  every Friday level over the weekend, since 250 × 15m = 62.5 hours of wall
  clock and the gold weekend is ~47);
* eviction by **importance**, not arrival order (the original discarded a
  5-touch level to make room for a fresh 1-touch pivot);
* the flip-retest timeout can no longer disable itself by nulling the very
  variable its guard depends on.

---

## Layout

```
aurum/
  data/dukascopy.py     tick download -> 1m bars with real bid/ask spread
  data/bars.py          resampling and causal feature construction
  engine/backtest.py    path-accurate simulator (see below)
  engine/costs.py       spread + slippage + commission, three presets
  engine/metrics.py     bootstrap p-values, deflated Sharpe, required-n
  engine/walkforward.py rolling train/test folds
  strategies/library.py nine falsifiable hypotheses
  research/explore.py   market-structure measurement
  research/hypotheses.py hypothesis screen with held-out test set
  research/validate.py  walk-forward validation + cost sensitivity
  live/signals.py       live signal generation sharing backtest logic
pine/AurumEdge_V2.pine  TradingView strategy
tests/                  engine correctness tests
```

### The backtester

Signals are generated on a decision timeframe (15m) but **every fill is
resolved by walking the 1-minute path**. This matters: on a 15m bar it is
common for price to touch both a 1R stop and a 2R target, and a bar-level
backtester simply picks one. At 1-minute resolution the true sequence is
almost always visible — in practice the residual ambiguity rate is **0%** on
the configurations tested — and where it isn't, the engine resolves
pessimistically and *counts* the occurrence.

Signal resolution and portfolio constraints are deliberately separate, so a
strategy that looks good only because a concurrency filter happened to skip its
losers cannot hide.

### Costs

Spread comes from the **actual Dukascopy quote history**, minute by minute,
not a flat assumption. Three presets bracket the answer:

| Preset | Spread markup | Stop slippage | Commission/side |
|---|---|---|---|
| `TIGHT` | 1.0× | $0.02 | $0.00 |
| `REALISTIC` | 2.0× | $0.05 | $0.00 |
| `HARSH` | 3.0× | $0.10 | $0.015 |

Results are reported at all three. A strategy that only survives at `TIGHT` is
not deployable.

---

## Reproducing

```bash
python3 -m venv .venv && .venv/bin/pip install numpy pandas pyarrow scipy requests pytest

# 1. Data (~30k hourly tick files -> monthly parquet; resumable, run shards in parallel)
for i in 0 1 2 3; do
  .venv/bin/python -m aurum.data.dukascopy \
    --start 2022-01-01 --end 2026-09-01 --shard $i --shards 4 &
done; wait

# 2. Measure the market
.venv/bin/python -m aurum.research.explore

# 3. Screen hypotheses against a held-out test set
.venv/bin/python -m aurum.research.hypotheses

# 4. Walk-forward validation with cost sensitivity
.venv/bin/python -m aurum.research.validate --tf 15min

# 5. Engine tests
.venv/bin/python -m pytest tests/ -q
```

---

## Honest limitations

* **Spot gold has no consolidated tape.** Dukascopy is one ECN's view. Your
  broker's fills will differ; recalibrate `CostModel` before trusting sizing.
* **No news filter.** Gold's worst days cluster around CPI, NFP and FOMC. The
  daily-loss circuit breaker limits the damage but does not avoid it.
* **Walk-forward is not live trading.** It removes look-ahead in parameter
  selection; it does not capture liquidity you consume, weekend gap risk, or
  broker-side execution quality.
* **Trade frequency and edge quality trade against each other.** See
  `reports/` for the measured curve rather than a chosen point on it.
