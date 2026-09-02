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

Every claim below is measured on **1,588,196 one-minute bars of XAUUSD**
(Jan 2021 – Aug 2026) built from Dukascopy tick data, carrying the **real
historical bid/ask spread** minute by minute. Reproduce it all with
`./run_study.sh`.

### 1. The headline: intraday expectancy is zero

Walk-forward validation, ten rolling folds (12 months train / 3 months test),
48 configurations searched per fold, **out-of-sample segments only**:

Eighteen folds, 48 configurations searched per fold, fills resolved on the
5-minute path:

| Costs | n | E[R] per trade | bootstrap p | Trades needed for t=2 |
|---|---|---|---|---|
| `TIGHT` | 1,395 | +0.0593 | **0.035** | 1,680 |
| **`REALISTIC`** | **1,326** | **+0.0133** | **0.337** | **32,101** |

At realistic costs the intraday system is **statistically indistinguishable from
zero** — and the deflated Sharpe, which corrects for the configurations searched,
comes out at P(SR > 0) = 0.000.

The `TIGHT` row is the interesting one. The signal is identical; only the spread
changed, and that alone moves it from noise (p = 0.34) to marginally real
(p = 0.035). **Execution cost, not signal quality, is the binding constraint.**

Parameter selection was *stable*: sixteen of eighteen folds independently chose
the 12:00–16:00 UTC window with 2.5 ATR stops. The mechanism is consistent —
there is just very little left in it after costs.

Every one of the nine hypotheses tested is negative out-of-sample on the
held-out set, several significantly: opening-range breakout −0.202 (t = −2.93),
sweep reversal −0.294 (t = −4.32), VWAP reversion −0.149 (t = −3.10).

### 2. Costs are the whole game

Cost drag equals `round_trip_cost / stop_distance`, so **the stop size is a
first-class risk parameter**, not a detail:

| Horizon | Avg stop | Cost as % of risk | Gross E[R] | Net E[R] | p |
|---|---|---|---|---|---|
| 15 min | $10.10 | 8.3% | +0.032 | **−0.077** | — (t = −3.70) |
| 1 hour | $18.38 | 4.6% | +0.051 | −0.010 | 0.58 |
| 4 hour | $40.59 | 2.1% | +0.212 | **+0.180** | **0.014** |
| Daily | $107.59 | 0.8% | +0.274 | **+0.254** | **0.009** |

Same mechanism at every horizon; only the timeframe changes. Cost falls
tenfold, gross edge rises ninefold, and the two together take net expectancy
from significantly negative to significantly positive. **Frequency is not a
setting you tune — it is what you spend to get trades.**

The predecessor's minimum stop of 0.05 × ATR on the reaction module permitted
stops of roughly **12 cents** — smaller than the spread. Those trades book free
2R winners in a backtest and are unconditionally unprofitable live.

### 3. Intraday gold is a random walk; the edge lives at the daily horizon

Lo-MacKinlay variance ratios across horizons:

| Horizon | VR | z | Verdict |
|---|---|---|---|
| 5m | 0.989 | −2.05 | mildly mean-reverting (microstructure) |
| 15m | 0.990 | −1.09 | random walk |
| 1h | 0.989 | −0.56 | random walk |
| 4h | 1.001 | +0.04 | random walk |
| 1D | 0.890 | −1.32 | random walk |

At the timeframes an intraday bot operates on there is **no systematic trend or
reversion to harvest**. That is the root cause of every negative result below:
the mechanisms are not badly built, they are extracting from a process with
almost nothing in it, and then paying costs on top.

The same data says the opposite about the **daily** horizon, where simple trend
rules are consistently strong and hold up across parameters:

| Rule | Ann. return | Sharpe | Max DD |
|---|---|---|---|
| Buy & hold | 3.7% | 0.26 | −22.8% |
| Above/below 20d MA | 9.4% | 0.66 | −12.5% |
| **Above/below 50d MA** | **11.9%** | **0.83** | **−9.4%** |
| 20d momentum | 11.7% | 0.82 | −12.2% |

Daily rules trade 10–20 times a *year*, so costs are negligible — a $0.80 round
trip against a multi-week $60 move is ~1% of the move, versus 10–20% of risk
intraday. This is the same reason CTAs have traded gold this way for decades.

### 4. Limit-at-retrace entries lose more than they save

They earn half the spread instead of paying it — worth roughly 0.03–0.05 R —
but they only fill when price retraces, which selects for moves that are
already failing. Market-on-close confirmation beat limit entries at every
timeframe and stop size tested. The predecessor used limit entries everywhere.

### 5. No hour of the day has a directional edge

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

**Trend pullback** (the "Candidate B" core) has the strongest gross edge of
anything tested at every horizon, and it is the mechanism the daily strategy is
built on. Stripped of the 15-point score, the pattern zoo and the RSI band —
none of which were derived from data — the mechanism itself holds up.

Its intraday decay is worth recording, because it is exactly what a short test
window does to you: gross expectancy read **+0.247 R** on the first five months
of data, **+0.062 R** at 2.7 years, and **−0.009 R** at 2.9 years. The original
7.5-week validation window could only ever have measured the first of those.

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
  `reports/horizon_spectrum.csv` for the measured curve rather than a chosen
  point on it.
* **The daily result is directional, not proven.** It rests on 16–46 trades over
  a window containing a strong gold bull market, with t-statistics of 0.5–1.8.
  What raises it above noise is consistency across every parameter setting and
  agreement with a large external literature on commodity trend-following — not
  its own significance.
