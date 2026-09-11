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

## Always in the market

Price under the descending line is a short. It breaks up, so that exits and
flips long. It breaks back through the ascending line, which exits and flips
short. The exit and the next entry are one event — you are never flat, you are
just trading the trend. `--flat` waits for a fresh setup instead.

It roughly triples the trade count, and it is not free:

| timeframe | flat between trades | always in |
|---|---|---|
| 5m (342 / 858) | +3.9%, 9.7% DD, PF 1.05 | **+28.6%**, 20.4% DD, PF 1.12 |
| 15m (392 / 960) | −18.0%, 21.8% DD, PF 0.83 | −8.5%, 26.3% DD, PF 0.97 |
| 1h (171 / 470) | +3.4%, 9.3% DD, PF 1.07 | +7.6%, 14.2% DD, PF 1.05 |
| 4h (108 / 268) | **+26.5%**, 5.2% DD, PF 1.80 | +9.6%, 13.0% DD, PF 1.09 |

Always-in wins on the fast timeframes and loses badly on 4H, where being
forced into every flip gives back most of the edge. Drawdown roughly doubles
everywhere. It is the default because it is the strategy as described, but on
4H the evidence says stay flat between setups.

### Always-in mostly trades young lines

Worth knowing before trusting a grade. Each reversal adopts the line that just
broke as its new Action Line, and those are Safety Lines — drawn from fresh
structure, so usually only 2 touches. On 4H, 248 of 268 always-in trades are
flips and the touch mix is 231 two-touch against 37 of three or more.

So always-in and "only take the A+ 3-touch setup" pull against each other: the
first forces you into every flip regardless of quality. `fresh_breaks` and
`reversals` are reported separately so the two never get conflated.

## Does the 3-touch rule hold?

Measured on genuine line breaks only (flips excluded, since a flip inherits
its touch count from a Safety Line and would poison the comparison):

| timeframe | 2 touches (B) | 3+ touches (A+) |
|---|---|---|
| 5m | −0.084R (n=201) | **+0.088R** (n=141) |
| 15m | −0.027R (n=209) | **+0.248R** (n=183) |
| 1h | **+0.236R** (n=76) | +0.038R (n=95) |
| 4h | **+0.307R** (n=42) | +0.240R (n=66) |

**Partial support.** The A+ setup clearly beats the two-touch version on 5m and
15m, and clearly does not on 1h and 4h. Exactly three touches is the sweet spot
on the fast timeframes (+0.15R on 5m, +0.44R on 15m) while four and five
degrade — more touches is not monotonically better.

This is one instrument over a few months. Treat it as "not yet contradicted on
fast timeframes", not as confirmation.

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

### The stop trails the line

The Safety Line slopes, so the stop rides *along* it and moves every bar,
rather than stepping only when a new swing confirms. Measured three ways:

| timeframe | stepped at pivots | trailing the line |
|---|---|---|
| 4H (106/108 trades) | +0.226R, PF 1.62, 5.7% DD | **+0.266R, PF 1.80, 5.2% DD** |
| 1H (168/171 trades) | +0.107R, PF 1.05, 9.6% DD | **+0.126R, PF 1.07, 9.3% DD** |
| daily (9 trades) | +0.488R, PF 1.97 | **+0.641R, PF 2.42** |

Better expectancy, better profit factor and *lower* drawdown in all three.
It does not cut winners: average win barely moves (+1.32R to +1.28R on 4H)
while win rate rises, so it is trimming losers rather than capping runners.

**But read the exit mix before accepting it.** Trailing flips which rule
actually closes trades:

```
stepped:   safety line 54%   failed break 25%   hard stop 22%
trailing:  hard stop 60%     failed break 24%   safety line 16%
```

Because the stop now rests just under the line, price reaches it intrabar
before a close can confirm. That quietly converts a close-based structural
exit into an intrabar trailing stop — better numbers here, but no longer
"let the close decide". `--step-stop` restores the original behaviour.

The distance the stop rests under the line is a genuinely unstable parameter:
0.25 ATR is best on 4H (+0.266R vs +0.247R at 0.10), while 0.10 ATR is best on
1H (+0.202R vs +0.126R) and on daily. The optimum moves with the timeframe,
which means it is fitting noise. It is left at 0.25 ATR everywhere rather than
tuned per timeframe, and should be treated as arbitrary.

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

## Deep grid: touch count x higher-timeframe alignment

80 backtests: every timeframe, crossed with how many touches the line had
before it broke, crossed with how much higher-timeframe agreement is demanded.
Run in flat mode, because always-in confounds the question -- each reversal
inherits its touch count from the Safety Line that broke, not from a line that
was tested three times. Reproduce with `analysis/research.py`.

### Touch count on its own decides nothing

| timeframe | exactly 2 | exactly 3 | exactly 4 |
|---|---|---|---|
| 4H | +0.296R | +0.147R | +0.039R |
| 1H | +0.210R | −0.036R | +0.034R |
| 15m | −0.059R | +0.392R | +0.175R |

No ordering survives across timeframes. Three touches beats two on 15m and
loses to it on 4H and 1H. **Touch count alone is not the edge.**

### Higher-timeframe alignment is the strongest signal found

On 4H, requiring that nothing above opposes the trade ("soft") roughly doubles
expectancy and halves drawdown — and it does so in *every* touch bucket:

| 4H | no filter | soft | majority |
|---|---|---|---|
| any 2+ | +0.266R, PF 1.80, DD 5.2% | **+0.577R, PF 3.27, DD 2.4%** | +0.094R |
| exactly 2 | +0.296R | +0.378R | +0.115R |
| exactly 3 | +0.147R | +0.555R, PF 4.08 | **+0.750R, PF 5.73, DD 1.4%** |
| exactly 4 | +0.039R | +0.265R | +0.436R |

And it holds in both regimes, split at gold's top:

| 4H window | exactly 3, no filter | soft | majority |
|---|---|---|---|
| bull (+65%, 1978 bars) | +0.092R | +0.707R | **+1.095R, PF 8.50** |
| top/chop (−14%, 1255 bars) | +0.228R | +0.492R | **+0.840R, PF 5.37** |

**Three touches only pays once the higher timeframes agree.** Alone it is
+0.147R; with majority agreement it is +0.750R. That is the combination, and
it is what the strategy actually claims.

### But it does not replicate below 4H

| any 2+ | no filter | soft | majority |
|---|---|---|---|
| 4H | +0.266R | **+0.577R** | +0.094R |
| 1H | +0.126R | −0.087R | −0.137R |
| 15m | +0.101R | +0.098R | −0.251R |

On 1H alignment *costs* money. The obvious explanation — that daily and weekly
are too slow to parent an hourly trade — was tested by using the two adjacent
timeframes (4h/1d) instead, and it did not rescue it (−0.087R to −0.049R, still
negative). So the effect is real on 4H, absent on 15m, and harmful on 1H, and
there is currently no explanation for why.

### What this is worth

The best cell (4H, exactly 3 touches, majority agreement) is **+0.750R at
PF 5.73 over 16 trades**. Sixteen. A profit factor of 5.7 on a sample that
small is not evidence of anything, and searching an 80-cell grid guarantees
some cell looks spectacular by chance.

What keeps it interesting rather than dismissible is the internal consistency:
on 4H the filter improves *every* touch bucket and *both* regimes, which a pure
fluke would not do. That is a hypothesis worth testing properly on real GC
futures over a decade — not a result.

## Real COMEX gold futures, 2008-2018

Everything above this ran on 18 months of a spot proxy in one bull market.
`data/GC_futures_daily.csv` is genuine GC daily OHLC across three regimes: the
2008-2011 bull (+153%), the 2011-2015 bear (-44%), and the 2016-2018 range.
Reproduce with `analysis/futures.py` and `analysis/best_config.py`.

**Read the data caveat first.** 13.4% of the source rows had a close outside
their own high-low range -- the close column and the OHLC columns were plainly
sourced differently. `validate()` repairs this by widening the range to contain
the open and close, which averages 0.154 ATR, inside the 0.45 ATR touch
tolerance, so it should not move trendline detection much. It is still repaired
data, and the repair lands exactly on the extremes the strategy draws from.

### Swing strength dominates everything else

A 65-configuration sweep put strength 5 in every top-ten result and strength 2
in every bottom one. It matters far more than touch count or alignment:

| swing strength | trades | expectancy | PF | return |
|---|---|---|---|---|
| 2 | 159 | −0.157R | 0.60 | −21.7% |
| 3 (old default) | 158 | +0.047R | 1.07 | +3.8% |
| **5** | 96 | **+0.241R** | **1.62** | **+21.3%** |
| 8 | 99 | −0.044R | 0.85 | −4.1% |

At strength 2 the detector calls every wiggle a pivot; at 5 it marks only
structure a person would actually draw. **Every earlier test in this README ran
at 3, which was hiding the result.** But note the peak is narrow and falls away
on both sides — that is what a fitted parameter looks like.

### Both of the strategy's own claims survive, at strength 5

From the same sweep: three touches beats any-2+ (+0.317R against +0.202R), and
soft higher-timeframe agreement beats no filter (+0.317R against +0.205R). Both
effects point the same way they did on 4H spot, which is the first thing in
this project to replicate across instrument, timeframe and decade.

### And it still fails out of sample

Best config: always-in, swing 5, 3+ touches, soft agreement.

| window | n | win% | expectancy | PF | return | max DD | buy & hold |
|---|---|---|---|---|---|---|---|
| bull 08-11 | 20 | 45.0 | **+1.060R** | 4.94 | +20.9% | 2.0% | +152.9% |
| bear 11-15 | 37 | 37.8 | +0.124R | 1.34 | +3.6% | 5.0% | −43.8% |
| range 16-18 | 46 | 26.1 | −0.030R | 0.85 | −2.3% | 8.6% | +17.0% |
| **1st half 08-13** | 43 | 46.5 | **+0.592R** | 2.82 | +25.0% | 2.3% | +62.6% |
| **2nd half 14-18** | 66 | 22.7 | **−0.067R** | 0.77 | −4.8% | 8.6% | +2.0% |
| ALL | 96 | 36.5 | +0.241R | 1.62 | +21.3% | 8.5% | +66.3% |

The entire ten-year result is the 2008-2011 bull run. The second half is
negative. The profile is coherent for a trend system -- strong in trends,
breakeven in bears, losing in ranges -- but "profitable only when gold trends
hard" is a description of the regime, not of an edge.

Costs are not the problem here: +22.2% at zero slippage against +18.9% at four
ticks. Ninety-six trades in a decade is cheap to run.

## Is this profitable? Not on this evidence.

The best configuration found (4H, flat between setups) returns +26.5% with a
5.2% drawdown and a 1.80 profit factor over 108 trades. Four tests say do not
trust it.

**Buy and hold beat it.** Gold went +41.2% over the same window. The strategy
made +26.5%. It wins on risk-adjusted terms — 5.2% drawdown against 30.0% —
but a trend system underperforming the raw trend in a bull market is a warning,
not a result.

**The profit is three trades.** Best 3 of 108 = 96% of all profit; the top 10%
of trades = 154% of it, meaning everything else loses money net. That is a
lottery ticket, not an edge, and live you will not get those three.

**The edge halves out of sample.** Splitting 4H down the middle: first half
+0.473R with PF 2.59, second half **+0.047R with PF 1.07**. Nearly all
performance came from the first half.

**It does not catch big moves.** Only 4 of 108 trades exceeded 3R; two
exceeded 5R. The average trade peaks at +1.15R and exits at +0.27R, giving
back roughly three quarters of every favourable excursion.

That last one looks like an exit problem, so the exit was slowed down — the
Safety Line drawn from major swings instead of minor ones:

| swing strength | trades | >=3R | best | avg peak | expectancy |
|---|---|---|---|---|---|
| 2 | 133 | 6 | +18.1R | +1.18R | +0.238R |
| 3 (default) | 108 | 4 | +15.3R | +1.15R | +0.266R |
| 5 | 95 | 4 | +10.6R | +1.15R | +0.182R |
| 8 | 61 | 1 | +10.6R | +0.93R | +0.033R |
| 16 | 27 | 1 | +3.5R | +1.30R | +0.149R |

Slowing the exit makes runners **rarer**, not commoner, and average peak
excursion sits near 1.15R at every setting. The moves are not being cut off
early; in this sample they are not there. Reward:risk is a healthy 2.6:1, but
it comes from many small wins against smaller losses — not from catching
trends.

**Costs:** 4H tolerates them (+10.6% at zero slippage, +9.6% at 1 tick, +1.6%
at 4 ticks). Faster timeframes will not — 5m always-in takes 858 round turns.

### What would change the answer

- Real GC futures data over 10+ years and several regimes, not 18 months of a
  spot proxy in one bull market.
- The same test on instruments that are not gold. If the edge is really
  "trendlines", it should not be fussy about the symbol.
- An explanation for the out-of-sample decay before, not after, trusting it.
- A profit distribution that survives deleting the best three trades.

Until then this is a working research engine for an idea that is **not yet
supported**, and the honest reading of every number above is "no signal", not
"small edge".

## Limitations

- One instrument, one regime, ~1.5 years, 106 trades. Not enough to conclude
  an edge exists.
- Strongly long-biased sample.
- Commissions are placeholders; slippage is a flat tick assumption, and real
  fills around a break are worse than that.
- R-multiples and dollars can disagree, badly. The 15m always-in run shows
  +0.146R expectancy alongside a −8.5% return and a profit factor of 0.97.
  Whole-contract rounding is why: a wide-stop trade rounds down to fewer
  contracts and therefore risks less than the nominal 1%, so its R does not
  convert into proportional money. **Trust the dollar column over the R
  column** on any instrument where one contract is a large fraction of the
  risk budget.
- The 5m and 15m windows are 35 and 103 days. That is one market condition,
  not a sample.
- Intrabar order is unknowable; a bar that touches the stop is assumed to have
  stopped out even when it closed well beyond.
- Nothing here is financial advice or a live trading system. It is a research
  engine for testing an idea.
