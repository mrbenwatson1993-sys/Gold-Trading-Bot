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

## One line, one stop -- and how close the stop can sit

The model, as the method actually works:

  * There is **no second trendline**. There is the line price broke -- fixed at
    the break and only extended, never redrawn -- and price is above it or
    below it.
  * The **stop follows price on the far side of that line**, close enough that
    price crossing back through the line runs straight into it.
  * The stop being hit **is** the exit. Nothing else closes a trade: no target,
    no separate line to close through.
  * Risk is fixed on entry and the stop only ever moves in the trade's favour,
    so a trade cannot lose more than it was sized for.

(The green line labelled "safety line" on a chart of this is the trailing stop
drawn as it follows price, not a second trendline.)

With that in place, holds go to ~50 bars -- eight days on a 4H chart -- which
is the timescale the method is described at, rather than the 9 bars the older
two-line version produced.

### How the stop should trigger

Three options, and the "worst" column is the one that decides between them --
it is the largest single loss in R, so it says whether the risk cap survived.

  * **intrabar** -- the stop always fills on a touch. Risk is capped, but a
    spike ends winners that structure never invalidated.
  * **hybrid** -- intrabar while the stop is still below entry (the real risk
    cap), close-confirmed once it has trailed to breakeven or better. A wick
    cannot take a winning trade; the worst case on that side is giving back
    open profit.
  * **close** -- always waits for a close beyond the stop. Kills wick-outs
    entirely, and the risk cap with them.

16 years of 4H gold, 3+ touches:

| trigger | dist | trades | hold | wick% | expectancy | PF | **worst** | return | max DD |
|---|---|---|---|---|---|---|---|---|---|
| intrabar | 0.10 | 476 | 48.2 | 38.7% | +0.153R | 1.14 | −1.18R | +54.0% | 29.4% |
| intrabar | 0.50 | 444 | 51.2 | 28.2% | +0.259R | 1.30 | −1.18R | +114.1% | 22.7% |
| hybrid | 0.10 | 442 | 51.9 | 19.9% | +0.239R | 1.26 | **−1.09R** | +103.1% | 23.7% |
| **hybrid** | **0.50** | 415 | 54.4 | **14.9%** | **+0.293R** | **1.39** | **−1.09R** | **+134.6%** | **21.7%** |
| close | 0.10 | 425 | 61.2 | 0.0% | +0.233R | 1.20 | **−2.31R** | +70.9% | 20.4% |
| close | 0.50 | 409 | 63.7 | 0.0% | +0.251R | 1.26 | **−5.25R** | +84.8% | 17.2% |

**The hybrid wins on every measure and keeps the guarantee.** It more than
halves the wick-out rate against intrabar (28.2% to 14.9%), lifts expectancy
from +0.259R to +0.293R and return from +114% to +135%, lowers drawdown, and
the worst single loss is −1.09R -- the overshoot being gap risk on the open,
which no stop prevents.

Waiting for a close on *every* stop looks tempting because wick-outs go to
zero, but the worst trade becomes −2.31R at a tight stop and **−5.25R** at a
wide one. It buys a cleaner exit statistic with the one thing that must not be
sold.

Silver replicates the wick-out reduction (38.7% to 23.2% at 0.10 ATR, 17.9% at
0.50) but not the profit: returns stay modest either way, and close-only is a
disaster there -- −36.6% with a −5.80R worst trade. The mechanism travels; the
payoff does not.

### The cost of a close stop, measured

"wick%" is the share of exits where the stop was hit intrabar **and that same
candle closed back on the correct side of the line** -- structure never broke,
the trade was ended by a spike. `analysis/stop_distance.py`.

| stop distance | trades | hold | **wick%** | expectancy | PF | return | max DD |
|---|---|---|---|---|---|---|---|
| 0.05 ATR | 477 | 48.0 | **40.5%** | +0.169R | 1.16 | +60.0% | 28.4% |
| 0.10 ATR | 476 | 48.2 | 38.7% | +0.153R | 1.14 | +54.0% | 29.4% |
| 0.25 ATR | 453 | 50.5 | 32.9% | +0.240R | 1.27 | +105.7% | 27.0% |
| **0.50 ATR** | 444 | 51.2 | 28.2% | **+0.259R** | **1.30** | **+114.1%** | 22.7% |
| 0.75 ATR | 433 | 52.5 | 24.2% | +0.255R | 1.30 | +106.0% | **21.6%** |
| 1.00 ATR | 426 | 53.3 | 23.2% | +0.224R | 1.27 | +83.3% | 25.5% |
| 1.50 ATR | 410 | 55.5 | 23.2% | +0.190R | 1.24 | +80.5% | 23.9% |

**Getting wicked out is expensive and unavoidable.** At the tightest setting
two exits in five are noise. Widening the stop cuts that to roughly one in
four and nearly doubles the return, but it never goes away -- past 0.75 ATR
the wick rate stops falling while returns decline, because the stop is now so
far from the line that it gives back real profit on the exits that *are*
genuine.

The sweet spot on gold is 0.50-0.75 ATR: +0.259R at PF 1.30 with 22.7%
drawdown, against +0.169R at PF 1.16 for a stop hugging the line.

Silver agrees on the wick rate (41.9% down to 27.0%) but **not** on the sweet
spot -- it prefers the tight end (+0.115R at 0.10 ATR) and goes negative at
0.50. So the wick-out *effect* replicates; the optimal distance does not, and
should be treated as per-market rather than a constant.

## Does it work on other markets? Metals yes, everything else no.

A claim about trendlines should not care what the symbol is. Same engine,
same settings, 10-16 years of 4H data each, 1% risk, no HTF filter, always in,
stop trailing the Safety Line. `analysis/instruments.py`.

| market | 2 tch | 3 tch | 4 tch | 5 tch | buy & hold |
|---|---|---|---|---|---|
| **GOLD** GC | +15.3% | +47.3% | +32.9% | **+73.7%** | +198.5% |
| **SILVER** SI | +75.9% | **+156.5%** | +35.7% | +102.3% | −25.3% |
| S&P ES | −48.2% | −16.0% | −38.8% | −14.7% | +171.1% |
| NASDAQ NQ | −69.5% | −72.4% | −65.0% | −53.8% | +405.3% |
| BRENT CL | −68.6% | −35.7% | −44.2% | −50.4% | −11.0% |

Profit factor tells the same story: gold 1.03-1.27 and silver 1.14-1.41, all
positive; against 0.72-0.94 on the S&P, **0.50-0.71** on the NASDAQ and
0.64-0.87 on Brent. Every one of the twenty non-metal configurations loses
money.

The silver result is the strongest single finding in the project: **+156.5% at
PF 1.26 over a decade in which silver itself fell 25%.** Making money while the
underlying declines is what a two-sided trend system is supposed to do, and it
is not something curve-fitting to gold would produce for free.

But three markets out of five lose badly, and the NASDAQ numbers are a
wipeout. So this is not a general property of trendlines. It works on precious
metals and fails on equity indices and crude, and **there is no tested reason
why.** A plausible story -- indices have a strong upward drift that punishes
the short side of an always-in system -- is contradicted by gold, which rose
just as hard and still paid. Until that is explained rather than narrated,
"works on metals" is an observation, not a rule.

One measurement trap visible in the table: the S&P 3-touch row shows +0.137R
expectancy alongside a **−16.0% return**, because a single +174R outlier drags
the R average up while the dollars stay negative. Read the return column.

### Does the engine actually do what the chart shows?

`analysis/trace.py` prints real trades in the chart's own terms. The sequence
matches exactly -- three touches listed with dates and prices, the Action Line
break with the close and the line value, entry on the next bar, the Safety
Line drawn from the breakout low up to each new higher low, and the exit when
price comes back through it.

What did not match at first was how long trades ran. With the Safety Line read
at the same sensitivity used to detect trendline touches, every three-bar dip
counted as a higher low, so the line ratcheted up under price and capped
winners near 1R. Reading it at coarser structure (`safety_swing_strength`)
is what lets price decide the profit:

| safety strength | trades | hold | avg win | best | >=10R | return | max DD |
|---|---|---|---|---|---|---|---|
| 3 (same as detection) | 1229 | 8.9 bars | +1.27R | +14.4R | 0.4% | +77.5% | 31.6% |
| 12 | 1152 | **20.3 bars** | **+2.04R** | +39.2R | **1.0%** | **+106.8%** | **23.3%** |
| 24 | 852 | 28.2 bars | +2.83R | +47.0R | 1.3% | +73.6% | 28.2% |

Longer holds, larger average wins, more genuine runners *and* lower drawdown.
Note strength 8 is an outlier at −62.8% and PF 0.83, so the relationship is
not monotonic and the setting should not be trusted precisely.

## Touch count, tested the way the method actually describes it

No higher-timeframe filter -- the monthly and weekly are used to place the
lines accurately, not to veto trades. A fixed stop on every trade sized to risk
a set % of the account, trailing up with price along the Safety Line, never
moving back. Always in the market, flipping on each break.
`analysis/touch_grid.py` and `analysis/touch_eras.py`.

**A third inert-filter bug had to be fixed first.** The touch rule was checked
only in `find_signal()`, and in always-in mode nearly every trade is a
reversal that simply adopts whichever line just broke. Two-touch and
three-touch runs returned byte-identical results -- 2,873 trades either way.
The rule now governs the flip too: fail it and the position closes rather than
reversing onto a line that was never tested enough to mean anything.

(Two-touch is the geometric floor. A straight line needs two points, so "0
touches" and "1 touch" cannot define a trendline; the 2-touch row *is* the
zero-extra-touches case.)

### More touches is better on every single measure

16.5 years, 4H gold, 1% risk:

| touches | trades | win% | expectancy | PF | return | max DD |
|---|---|---|---|---|---|---|
| 2 (0 extra) | 2033 | 30.5 | +0.031R | **1.00** | +2.7% | 32.3% |
| 3 (1 extra) | 804 | 33.0 | +0.065R | 1.08 | +22.3% | 18.7% |
| 4 (2 extra) | 597 | 31.3 | +0.108R | 1.33 | +67.5% | 16.1% |
| **5 (3 extra)** | 343 | 35.3 | **+0.162R** | **1.47** | +55.2% | **9.3%** |
| unlimited 2+ | 2873 | 30.9 | +0.046R | 1.05 | +70.6% | 33.1% |

Expectancy, profit factor and drawdown all improve monotonically with every
touch added. **The two-touch break has a profit factor of exactly 1.00 -- no
edge whatsoever.** Everything the strategy earns comes from lines price has
tested repeatedly, which is precisely the claim the method makes.

Taking every break regardless ("unlimited") buys the highest raw return by
brute force -- 2,873 trades at 33% drawdown -- while the 5-touch filter earns
almost as much from an eighth of the trades at a third of the drawdown.

### Position size confirms the edge is real

At 2% risk instead of 1%, the configurations separate by whether they have an
edge to compound:

| touches | 1% risk | 2% risk |
|---|---|---|
| 2 | +2.7% (32.3% DD) | **−1.0%** (49.0% DD) |
| 3 | +22.3% (18.7% DD) | +1.9% (36.3% DD) |
| 4 | +67.5% (16.1% DD) | +78.5% (25.4% DD) |
| **5** | +55.2% (9.3% DD) | **+118.1%** (16.8% DD) |

Doubling risk roughly doubles the 5-touch return, because there is a real edge
to scale. It pushes the 2-touch version *negative*, because volatility drag on
a zero-edge system compounds against you. That asymmetry is a useful test in
its own right.

The risk cap holds: the worst single trade across 2,873 is −1.77R, and the
overshoot past 1R is gap risk on the open, which no stop can prevent.

### Per-era it is noisier than the aggregate suggests

Expectancy by touch count, 1% risk:

| era | 2 touch | 3 touch | 4 touch | 5 touch |
|---|---|---|---|---|
| 2007-2010 | −0.060 (442) | +0.068 (205) | **−0.095** (141) | +0.308 (81) |
| 2011-2014 | +0.084 (429) | +0.150 (187) | +0.348 (131) | +0.184 (76) |
| 2015-2018 | +0.088 (414) | +0.070 (195) | +0.113 (154) | **−0.011** (88) |
| 2019-2023 | +0.013 (728) | **−0.031** (212) | +0.108 (163) | +0.170 (92) |
| **ALL** | +0.031 | +0.065 | +0.108 | **+0.162** |

**No individual era shows a clean 2 < 3 < 4 < 5 ladder.** The monotonicity is
an aggregate property. What does hold per era is the direction: 4- and 5-touch
are positive in three eras of four, their positive eras are far larger
(+0.348, +0.308) and their negative era is far smaller (−0.095, −0.011) than
the 2-touch case. Cells hold 76-212 trades, so individual numbers are noisy
while the pattern across them is not.

This is the most robust finding in the project, and it is the strategy's own
core claim rather than anything added to it.

## Also holds: always in WITH the trend, flat against it

Two bugs were hiding this, both found by asking why the trade count was so low
for a strategy that is supposed to be in the market all the time.

**Bug 1 -- "always-in" was flat 35% of the time.** When a flip was signalled
but the structural pivot that defines risk sat on the wrong side of price
(17.4% of attempts), `reversal()` gave up and the engine went flat, then needed
a *fresh* qualifying setup to re-enter. One gap ran 588 bars -- three months out
of the market. A volatility-scaled fallback stop fixes it: exposure went from
59.2% to 91.6% and flat gaps from 73 to zero. (The residual 8.4% is exactly the
one-bar lag between an exit and the next-open entry.)

**Bug 2 -- the higher-timeframe filter was inert.** Only `find_signal()`
checked alignment, and in always-in mode almost every trade is a reversal, so
the filter touched 10 trades out of 2,223. Every "alignment does nothing on 16
years" conclusion above was measuring a filter that was not running.

With alignment actually governing the flips -- close the long when the
ascending line breaks, but do not *sell* into a market that is bullish on every
timeframe above -- over 26,630 bars:

| HTF filter | trades | expectancy | PF | return | max DD |
|---|---|---|---|---|---|
| none | 2223 | +0.047R | 1.04 | +51.7% | **52.8%** |
| **soft** | 347 | **+0.194R** | **1.54** | **+75.7%** | **7.9%** |
| majority | 133 | +0.115R | 1.32 | +12.9% | 7.1% |
| all | 19 | +0.139R | 1.42 | +2.0% | 2.1% |

Four times the expectancy, better return, and drawdown collapsing from 53% to
8%. Refusing to trade against the higher timeframes is the single most valuable
rule found in this project.

### And unlike everything else, it survives out of sample

| era | n | expectancy | PF | return | max DD | buy & hold |
|---|---|---|---|---|---|---|
| 2007-2010 | 80 | −0.039R | 0.87 | −3.6% | 10.0% | +118.0% |
| 2011-2014 | 100 | **+0.394R** | 1.74 | **+30.8%** | 5.0% | **−15.2%** |
| 2015-2018 | 124 | +0.104R | 1.20 | +8.4% | 8.8% | +7.7% |
| **2019-2023** | 115 | **+0.199R** | **1.49** | **+21.4%** | 7.8% | +50.3% |
| ALL | 347 | +0.194R | 1.54 | +75.7% | 7.9% | +198.5% |

Three of four eras positive, **including the most recent** -- where the previous
best configuration lost 19.1%. It made +30.8% in 2011-2014 while gold fell
15.2%. No era draws down more than 10%.

Costs do not break it: +84.9% at zero slippage, +75.7% at one tick, +49.8% at
four (PF 1.35). 347 trades in 16 years is cheap to run.

**The honest caveats.** Raw return still trails buy-and-hold (+75.7% against
+198.5%) -- but at 7.9% drawdown against gold's ~45%, so risk-adjusted it is
roughly twice as good, and at 1% risk per trade there is room to size up.
2007-2010 is negative. 347 trades is a real sample but not a large one. And
this is one instrument: the next test that matters is whether it holds on ES,
CL and NQ, because a rule about trendlines should not care about the symbol.

## 16 years of 4-hour gold, 2007-2023 -- the definitive test

`data/gold_4h_16y.csv` is 26,630 4H bars from 2007 to 2023: the 2008 crash,
the 2011 top, the 2011-2015 bear, the 2016-2019 range, the 2020 COVID spike
and the 2022 rate shock. Zero OHLC integrity violations, no gaps, ~1,600 bars
a year. This is 8x the earlier 4H sample and it is the timeframe every
promising result in this project lived on. Reproduce with `analysis/deep4h.py`.

**Nothing that looked good on 18 months survived it** -- though note that the
alignment rows in this section were measured with the filter inert (see the
section above), so they understate it badly.

### Higher-timeframe alignment: gone

On 18 months it took 4H from +0.266R/PF 1.80 to +0.577R/PF 3.27. Over 16 years
(always-in, swing 5):

| touches | no filter | soft | majority |
|---|---|---|---|
| any 2+ | +0.030R | +0.034R | +0.025R |
| 3 only | +0.045R | +0.039R | +0.003R |
| 3+ | +0.030R | +0.040R | — |

The effect is gone. What looked like the strongest signal in the project was
an artifact of 108 trades in one bull market.

### Three touches: a real but tiny edge

+0.045R against +0.030R for any-2+, on 1,801 trades. It points the way Tori
says it does, and it is nowhere near large enough to build on.

### Swing strength: fitted, not structural

| swing | trades | expectancy | PF | return | max DD |
|---|---|---|---|---|---|
| 2 | 2045 | +0.071R | 1.12 | +143.9% | 20.2% |
| 3 | 1945 | +0.084R | 1.14 | **+158.2%** | 20.6% |
| 5 | 1483 | +0.040R | 1.07 | +53.4% | 38.5% |
| 8 | 869 | +0.033R | 1.03 | +9.8% | 22.6% |
| 12 | 597 | +0.223R | 1.37 | +103.3% | 18.2% |

Non-monotonic and directly contradicting the GC daily sweep, where 5 dominated
and 3 was mediocre. A parameter whose optimum jumps between datasets is fitted
to the dataset.

### It fails in the most recent era

Always-in, swing 5, 3+ touches, soft agreement:

| era | n | expectancy | PF | return | max DD | buy & hold |
|---|---|---|---|---|---|---|
| 2007-2010 | 294 | +0.075R | 1.20 | +19.2% | 12.6% | +118.0% |
| 2011-2014 | 390 | **+0.140R** | 1.28 | **+47.6%** | 14.4% | **−15.2%** |
| 2015-2018 | 376 | +0.031R | 1.05 | +7.3% | 21.0% | +7.7% |
| **2019-2023** | 464 | **−0.028R** | **0.89** | **−19.1%** | 42.4% | +50.3% |
| ALL | 1483 | +0.040R | 1.07 | +53.4% | 38.5% | **+198.5%** |

One genuinely encouraging row: 2011-2014, the strategy returned +47.6% while
gold fell 15.2%. Making money in a bear market is what a trend-following
system is for, and it did it. But the most recent five years lose money, and
over the whole period +53.4% at 38.5% drawdown against buy-and-hold's +198.5%
is not a business.

Going flat between setups is better risk-adjusted than always-in (+0.085R,
PF 1.22, 7.3% drawdown against +0.040R, PF 1.07, 38.5%) at a fifth of the
trades and a quarter of the return.

### Is the spot proxy legitimate? Yes.

Deep intraday *futures* history is paywalled -- FirstRate's free GC sample is
two weeks, which is 67 4H bars. But that sample overlaps the PAXG series, so
the proxy is testable rather than assumed (`analysis/proxy_check.py`).

The first measurement said the two were uncorrelated (0.11), which is not
credible for the same metal. It was a timezone bug: the futures export is
stamped in exchange-local time. **At +4h, correlation is 0.9930.** With the
futures basis (+46.8 points, 1.30 ATR of pure carry) removed, high and low
disagreement is 0.171 and 0.194 ATR, with 92% of highs and 100% of lows inside
the 0.45 ATR touch tolerance.

So spot is a sound stand-in for trendline work — **but only once timestamps are
aligned.** If you import a broker CSV stamped in local time and the engine
treats it as UTC, the daily and weekly bars used for alignment are cut at the
wrong hour, and the higher-timeframe read is quietly wrong.

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
