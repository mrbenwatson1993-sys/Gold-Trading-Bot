# Rule-by-rule mapping

Every rule in the bot traced to what is actually said in the video, and the input that
controls it. Quotes are from the transcript of
[youtube.com/watch?v=-_MwsLDQHCk](https://www.youtube.com/watch?v=-_MwsLDQHCk).

---

## Step 1 — the 15-minute fair value gap

> *"Step one is for me to find what's called a 15-minute fair value gap. And that's
> basically a series of three candles where the first candle and the third candle's
> wick don't overlap, which leaves this space in between … And what I want to see is
> price pull into one of these fair value gaps and then start to have a response
> respecting this area."*

**Detection.** Over three consecutive 15m candles `c1, c2, c3`:

```
bullish gap  ⇔  low(c3) > high(c1)      zone = [ high(c1), low(c3) ]
bearish gap  ⇔  high(c3) < low(c1)      zone = [ high(c3), low(c1) ]
```

The higher-timeframe series is requested at offsets `[1]` and `[3]`, so the bot only
ever reads **closed** 15m bars. Nothing repaints.

**"Pulls in and responds."** A gap stays live until a chart bar *closes* through its far
edge, or it ages out. The response requirement is: price traded inside a live gap
within the last N chart bars.

| Input | Default | Meaning |
|---|---|---|
| `Require a 15m FVG response` | on | Step 1 on/off |
| `Context timeframe` | `15` | |
| `Minimum 15m gap size (× 15m ATR)` | `0.15` | Discards cosmetic gaps |
| `Price must have tapped the gap within N bars` | `60` | 60 × 1m = one hour |
| `Discard a 15m gap after N 15m bars` | `96` | ~1 trading day |

---

## Step 2 — the change of character

> *"What I'm doing is waiting for the 9:30 a.m. New York open … a change of character
> is basically where price starts to break out of the previous trend … if price is
> trending down this way and then all of a sudden we have a new high that's higher than
> all of these other points, that is going to be my change of character area."*

Swing points come from `ta.pivothigh` / `ta.pivotlow` with an adjustable strength.

```
bullish CHoCH  ⇔  close crosses above the last confirmed swing high
                  AND that swing high was lower than the one before it
```

The second clause is the *"price is trending down this way"* part — without it a
"CHoCH" is just a breakout in an existing uptrend. It can be switched off.

When a CHoCH fires, the bot records the **leg**: origin = the swing low that started
the move, and a high that keeps extending as price runs. The leg dies if price closes
back through its origin or it exceeds its bar limit.

| Input | Default |
|---|---|
| `Swing pivot strength` | `3` |
| `Require the prior structure to be opposing` | on |
| `CHoCH leg stays valid for N bars` | `45` |
| Session window | `0930-1130` New York |

---

## Steps 3 & 4 — the 1-minute gap and the fib zone

> *"What I want to see happen … is for a one minute fair value gap to form somewhere in
> this change of character. And I want to take particular note of the exact middle of
> this fair value gap … take what's called a Fibonacci and drag from the beginning of
> the move to where we are currently and make sure that this gap is somewhere between
> the 50 and the 61.8 value."*

Three conditions, all required:

1. The gap formed **at or after the leg origin** (it is *inside* the CHoCH).
2. It is **unfilled** — no close through its far edge.
3. Its **midpoint** sits inside the retracement zone, measured on the live leg:

```
bullish:  0.5   level = legHigh − 0.500 × (legHigh − legLow)
          0.618 level = legHigh − 0.618 × (legHigh − legLow)
          require   fib0.618 ≤ midpoint ≤ fib0.5
```

The fib is re-measured every bar, because the video draws it *"to where we are
currently"* — so as the leg extends, the zone moves with it and a gap can drop out of
qualification. That is faithful to the method, and it means the armed entry can appear
and disappear. The orange band on the chart is the live zone.

If more than one gap qualifies, the bot takes the **most recent**.

| Input | Default |
|---|---|
| `Minimum 1m gap size (× 1m ATR)` | `0.10` |
| `Require the gap midpoint inside the fib zone` | on |
| `Fib zone — shallow / deep edge` | `0.500` / `0.618` |
| `Zone tolerance (× leg range)` | `0.0` |
| `Discard a 1m gap after N bars` | `45` |

---

## Step 5 — entry, stop, target

> *"I'm going to set my position up just above the midpoint of this fair value gap.
> Place my −1 unit of R outside of this fair value gap producing sequence and target
> between three and four risk factors."*

**Entry** — a resting limit at the gap midpoint. `Entry offset from midpoint (ticks)`
defaults to `0` (the chart walkthrough says *"the exact midpoint"*); a few ticks
reproduces *"just above."* The order is only placed while price is still on the far
side of it, so the bot waits for the pullback instead of chasing.

**Stop** — *"outside the fair value gap producing sequence"* means beyond the extreme of
**all three** candles that made the gap, not merely the gap edge. That is the default.

| `Stop loss reference` | Placement (long) |
|---|---|
| `FVG-producing sequence` *(default)* | `min(low of the 3 gap candles) − buffer` |
| `Gap far edge` | `gap bottom − buffer` |
| `CHoCH leg origin` | `leg low − buffer` |

**Target** — `Target (risk factors)`, default `4.0`. The target is recomputed from the
**actual fill price**, so a fill that slips still produces a true 4R target rather than
a silently degraded one.

There are no partial exits. The video's simplified model is one entry, one stop, one
target, and adding scale-outs would make the R statistics incomparable to his. An
optional breakeven move exists and is **off** by default for the same reason.

---

## The risk model

### R factors

> *"A 1:1 risk-reward ratio requires a 50% win rate in order to break even … 1:2
> requires only a 40% win rate … 1:4, even being right two out of 10 times, we're able
> to become break even traders. And if we're able to edge that up into say 30 to 40%
> win rate, and that's currently where I sit …"*

Break-even win rate for a given R:R is `1 / (1 + R)`. The dashboard shows this next to
your live win rate, so you can see immediately whether the strategy is above water on
its own terms:

| Target | Break-even WR |
|---|---|
| 1:1 | 50% |
| 1:2 | 33.3% |
| 1:3 | 25% |
| **1:4** | **20%** |

(The video's table quotes 40% for 1:2 and 30% for 1:3, which builds in a costs margin
over the raw 33.3% / 25%. The bot reports the raw figure.)

### Percentage scaling

> *"As we start to lose, we're proportionally risking less and less of our account so
> that we don't end up driving ourselves into the ground … Once I make it to $1,000,
> now I'm going to use 5% of the account per trade."*

Risk is recomputed from **current equity** on every trade, so it compounds up and
de-risks down automatically. The step-down tiers are editable:

| Input | Default |
|---|---|
| `Risk % of current balance` | `10.0` |
| `Step risk down as the account grows` | on |
| Tier 1 — balance ≥ `1000` → risk | `5.0%` |
| Tier 2 — balance ≥ `10000` → risk | `2.0%` |

### Position size

> *"We need to take our entry price, subtract that by our stop-loss, and then divide
> that by the desired dollar amount we're trying to risk."*

He states it backwards on the audio but computes it correctly on screen (192 units on a
13-point stop). The bot uses the correct form:

```
size = risk$ / ( |entry − stop| × pointValue )     rounded DOWN to the size step
```

`pointValue` comes from the symbol, so this is already correct for futures contracts
(*"risk per contract is going to be $14.50, and if we use two contracts, that's
approximately $25 of risk"*), for spot gold, and for shares.

If the rounded size lands below your instrument's minimum, the trade is **skipped** by
default rather than taken at an over-sized minimum.

### Brakes not in the video

| Input | Default | Why |
|---|---|---|
| `Max trades per day` | `3` | The model is a morning-session setup, not a grind |
| `Stop for the day after losing N R` | `3.0` | Caps a bad morning at −3R |
| `Flatten any open trade at session end` | on | No unmanaged positions past the window |

---

## Reading the dashboard

| Row | Meaning |
|---|---|
| `state` | Where in the five steps you are — right through to `SETUP ARMED` |
| `15m context` | Whether step 1 is currently satisfied |
| `risk / trade` | Live cash risk and the tier percentage producing it |
| `size` | Size for the armed setup, or the live position |
| `R today` / `R total` | Realised R — the unit the whole method is measured in |
| `win rate` vs `break-even WR` | Green when the edge is positive at your configured R:R |

> *"6.7R × $25 is $168 a week … if you can get that process really well established and
> you add another zero to that …"*

`R total` divided by weeks tested is the number that matters. Get that positive and
stable first; the dollar figure is just that number times your risk.
