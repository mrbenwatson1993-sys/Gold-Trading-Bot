# Gold Trading Bot — Tori Trades trendline strategy

A price-action-only trendline engine, built for futures.

No indicator stack. Swing points, trendlines, and two rules:

```
price breaks the trendline        ->  ACTION LINE  ->  enter
price breaks back through
the opposite trendline            ->  SAFETY LINE  ->  exit
```

There is **no profit target**. The only fixed quantity in the system is the
initial risk; the reward is whatever price hands you before it breaks back
through the opposing line. Price decides the entry and price decides the exit.

## Quick start

```bash
python3 -m tori scan     data/gold_4h.csv              # where are we right now?
python3 -m tori signals  data/gold_4h.csv              # every break in the file
python3 -m tori backtest data/gold_4h.csv --symbol MGC --equity 250000
python3 -m tori contracts                              # known futures specs
```

Pure Python 3.11+, standard library only. No dependencies to install.

## The strategy

1. **Top-down.** Monthly → weekly → daily → 4H. The same lines, refined as
   finer bars reveal where the swings actually sat.
2. **Two kinds of line.** Bearish connects lower highs (dynamic resistance).
   Bullish connects higher lows (dynamic support).
3. **Don't draw a line wherever you can.** A candidate survives only if price
   never closed through it while it formed, its touches are spaced out, it has
   enough bars behind it, it is not near-vertical, and it spans a move that
   actually happened rather than chop.
4. **Count the touches.** Three or more is the A+ structure; two is weaker.
5. **Wait.** Do nothing until price reaches the line.
6. **Wait for the close.** A wick through is not a break. Never anticipate.
7. **Enter.** The broken line is now the Action Line.
8. **Draw the Safety Line** from the new structure — the opposing trendline.
9. **Let it breathe.** A pullback is not an exit.
10. **Exit** when a candle closes back through the Safety Line.

Both lines stay extended forever and cross over, which is what lets you see
price come back through the opposite one.

### The apex

Because every trendline stores its anchor as a *timestamp* and its slope *per
second*, a weekly line can be evaluated on a 5-minute chart with no conversion.
Lines from every timeframe live in one price/time space, and `scan` reports
what that overlay shows: a descending line from above and an ascending line
from below, converging, with price compressed inside. A triangle waiting to
break either way. When it breaks, the line it broke is the Action Line and the
other one — already drawn, already extended — is the Safety Line.

```
   1w  ranging  1 live line(s)
        / 3-touch support    @   4100.45  (-211.41 from price)
   1d  ranging  5 live line(s)
        \ 2-touch resistance @   4611.45  (+299.59 from price)
   4h  ranging  2 live line(s)
        \ 6-touch resistance @   4403.25  (+91.39 from price)
```

## What the data says

1.5 years of 4H gold, micro gold futures (MGC), 1% risk, $250k account,
1 tick slippage and commission charged both ways:

```
trades 106   win rate 39.6%
expectancy +0.226R    profit factor 1.62
avg win +1.32R        avg loss -0.49R      best +14.77R
equity $250,000 -> $301,703 (+20.7%)       max drawdown 5.7%
```

The shape is the point: **you lose small and often, and win rarely and big.**
That is what removing the profit target buys, and it only works if you can sit
through a 60% loss rate.

### Three findings worth more than the headline

**The quality filters were worthless.** A ten-criterion A+ grading rubric,
break-displacement filters, S/R location scoring and clean-space gates were
built, then measured against the plain version:

| | trades | expectancy | profit factor |
|---|---|---|---|
| simple (lines only) | 106 | +0.226R | 1.62 |
| filtered (all of it) | 100 | +0.248R | 1.65 |

All that machinery bought +0.02R. Worse, the grades were anti-predictive: A+
was 3 trades and all losers, A broke exactly even, and plain B carried the
entire +26.6R. **The filters are off by default.** Grading still prints as a
label so you can inspect a setup; it never blocks a trade. `--filtered` turns
the gates back on if you want to test them yourself.

**Position sizing silently cherry-picks trades.** The first run showed a
glorious +0.797R expectancy on 18 trades — and had skipped 154 setups for
"stop too wide to size". At $25k with 1% risk, one MGC contract only covers a
~25 point stop, while gold's structural stops run 40–80 points. The backtest
had quietly kept only the tightest-stop trades. Sizing rejections are now
reported on every run. **Watch that number**; if it is large relative to the
trade count, the results are a selection effect, not an edge.

**Almost all of the edge is long.** Longs +28.9R over 48 trades, shorts −5.0R
over 58. This sample is a gold bull market, so a meaningful part of what looks
like strategy may be direction. Do not skip this caveat.

## Faithful vs. added

Kept honest because it matters for tuning:

| Tori's rules | Our mechanical additions |
|---|---|
| three-touch break is the A+ setup | 6-bar minimum spacing between touches |
| close through the line, never anticipate | 60-bar minimum line age |
| opposing trendline is the exit | slope cap, minimum spanned move |
| no fixed RR, risk only | a resting stop for gap protection |
| lines stay extended and cross | ATR-scaled tolerances |

Two deliberate departures, both documented in code:

- **Age is counted in bars, not calendar days.** The same lines are drawn on
  the monthly and refined down to the 5-minute, so "3 weeks" is meaningless on
  a 5m chart. The widely-quoted "3+ weeks" refinement would have rejected
  Tori's own worked 4H example, which runs touch 1 → break in 84 bars.
- **A resting stop sits at the structural invalidation.** The Safety Line is a
  *close*-based exit, and a gap straight through it — a Sunday open, a CPI
  print — is an unbounded loss on leveraged futures. The Safety Line decides
  when the trend is over; the resting stop only decides how bad a gap may get.

### The Safety Line anchor

The single largest improvement in the build. Anchoring the line to the last two
swings makes it steeper as the trend ages until it knifes through healthy
pullbacks. Anchoring it at the **breakout low** — where the new trend began —
and swinging the far end up to each new higher low keeps it shallow:

| | expectancy | profit factor | best trade |
|---|---|---|---|
| last two swings | +0.149R | 1.38 | +7.99R |
| breakout low | **+0.248R** | **1.65** | **+14.77R** |

## Futures

Sizing is in whole contracts against real specs, never fractional units:

```python
gc  = get_contract("GC")    # $100/point -> $1,250 risk on a 12.5pt stop
mgc = get_contract("MGC")   # $10/point  -> $125 risk on the same stop
```

If one contract would exceed the risk budget the trade is **skipped**, not
taken at higher risk. GC, MGC, SI, HG, CL, MCL, NG, ES, MES, NQ, MNQ, YM, MYM,
RTY, M2K, ZB, ZN, 6E, 6J are registered; commissions are placeholder retail
numbers and should be set to your broker's.

## Data

`data/*.csv` is 4H/1H/daily **PAXG/USDT** — tokenised spot gold, used as
development data because gold futures history is not freely reachable. It is
real gold price action, not synthetic, but it is not your contract: no
settlement, no roll, no pit session, crypto-hours liquidity.

**For real work, import your own.** Export 4H GC or MGC candles from your
broker or TradingView and point the engine at the file. The CSV reader takes
unix or ISO timestamps and matches column names case-insensitively.

```bash
python3 -m tori backtest ~/exports/GC_4h.csv --symbol GC --equity 100000
```

## Layout

```
tori/
  contracts.py   futures specs, contract sizing, costs
  candles.py     OHLC loading, resampling, ATR
  swings.py      pivot detection with honest confirmation lag
  trendlines.py  line construction and the validity rules
  breaks.py      the close through the Action Line
  structure.py   trend vs. range, the top-down read
  levels.py      horizontal S/R and clean space
  quality.py     the A+ scorecard (reporting only by default)
  mtf.py         the timeframe ladder and apex detection
  strategy.py    the state machine: scan -> break -> enter -> safety -> exit
  backtest.py    event-driven engine, pessimistic on every ambiguity
  report.py      human-readable output
  cli.py         command line
```

## Testing

```bash
python3 -m unittest discover -s tests -t .
```

54 tests. The one that matters most asserts **no lookahead**: run the backtest
over the first N bars of real gold, then over all of them, and every trade that
settled before the cut must be identical. If any decision peeked at a future
bar, the two runs would disagree.

## Limitations

- One instrument, one regime, ~1.5 years, 106 trades. Not enough to conclude
  an edge exists.
- Strongly long-biased sample.
- Commissions are placeholders; slippage is a flat tick assumption, and real
  fills around a break are worse than that.
- Intrabar order is unknowable; a bar that touches the stop is assumed to have
  stopped out even when it closed well beyond.
- Nothing here is financial advice or a live trading system. It is a research
  engine for testing an idea.
