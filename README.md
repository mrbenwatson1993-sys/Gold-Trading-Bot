# TradingView Trading Tools

Two mechanical trading models from YouTube, implemented in Pine Script v6.

| File | What it is | Use it for |
|---|---|---|
| `indicator/session_sweep_mss_618.pine` | **Session sweep → MSS → 0.618 alerts** | **Alerts you act on manually** |
| `strategy/session_sweep_mss_618_backtest.pine` | The same model, backtestable | Checking the edge before you trade it |
| `strategy/percoco_50_morning_model.pine` | Percoco 15m FVG → 1m CHoCH model | Backtesting, auto-execution |

---

# 1 · Session Sweep → MSS → 0.618  ·  alert tool

From **"The 5-Minute Scalping Strategy I Use Every Single Day"**. A 5-minute forex
model in three mechanical steps. This one is an **indicator**, not a strategy: it
watches the chart and sends you a ticket with the entry, stop and target so you place
the order yourself.

**Setup guide: [docs/ALERTS.md](docs/ALERTS.md)** — read this one, it's the whole
workflow. **[docs/BACKTESTING.md](docs/BACKTESTING.md)** covers the backtest twin,
which shares the detection logic line for line and breaks results down per session.
**[docs/FOREX-SETUP.md](docs/FOREX-SETUP.md)** has ready-to-use settings for EURUSD and
GBPUSD — and why running both at once is one position, not two.

### The three steps

| # | Step | What the tool does |
|---|---|---|
| 1 | **Session sweep** — wait for the previous session's box high or low to be taken, whichever goes **first** | Draws Asia / London / New York boxes itself (no third-party indicator needed), freezes each range, watches the next session for the sweep |
| 2 | **Market structure shift** — a **body close** through the last fractal | Williams fractals with adjustable strength; wick-throughs are rejected, as the video insists |
| 3 | **Fib on the leg that made the shift** — enter **0.618**, stop at the leg extreme, TP at **2:1** | Draws the leg, prices the 0.618, and sends entry / stop / target |

Sweep the **high** → hunt shorts. Sweep the **low** → hunt longs.

### What it sends

```
🔻 SETUP ARMED · SHORT GBPUSD 5
New York swept London HIGH · structure shifted
Entry (0.618): 1.27345
Stop:          1.27612
Target (2R):   1.26811
Risk:          26.7 pips
```

Plus optional alerts for the sweep, for the tap on the 0.618, for the outcome, and —
the one that saves you from a stale order — **LEVEL MOVED**, when the leg extends
after the shift and the 0.618 relocates.

### Worth knowing

- **Sessions are drawn internally.** The video uses LuxAlgo *Sessions* and *Fractals by
  Rachel T*; neither is required here. Session windows and fractal strength are inputs.
- **Two-sided sweep bars are a guess.** If one candle takes both sides of the previous
  session, no candle can tell you which went first. The tool assumes a down-closing bar
  ran the high first. Check a lower timeframe on those.
- **The evidence is thin.** The video shows a handful of examples (3 wins, 2 losses)
  and puts the "years of backtested data" behind a Discord join. At 2:1 you need better
  than a 33% win rate to break even before spread. Log the alerts for a month before
  you trade them.

---

# 2 · Percoco $50 Morning Model  ·  strategy

A mechanical Pine Script v6 implementation of the trading model Craig Percoco
teaches in **"If You Only Have $50 To Trade With, Do This Every Morning"**
([youtube.com/watch?v=-_MwsLDQHCk](https://www.youtube.com/watch?v=-_MwsLDQHCk), Sep 2026).

It reproduces the five steps he lays out, his stop and target placement, and his
R-factor / percentage-scaling risk model — as a backtestable, alertable strategy.

Rules mapped to source quotes: [docs/STRATEGY.md](docs/STRATEGY.md).
Webhook automation: [docs/AUTOMATION.md](docs/AUTOMATION.md).

---

## The model

> *"My strategy is using two time frames. One is the 15-minute time frame … and then
> I'm executing my actual trade entries on a 1-minute chart."*

| # | Step | What the bot does |
|---|------|-------------------|
| 1 | **15m fair value gap** — three candles where wick 1 and wick 3 don't overlap; price pulls in and responds off it | Tracks unfilled 15m FVGs from *closed* 15m bars only, and requires price to have traded into one recently |
| 2 | **1m change of character** after the **9:30 NY open** — price breaks out of the previous trend | Pivot-based swing structure; a bullish CHoCH is a close above the last swing high while the structure was making lower highs |
| 3 | **1m FVG inside that CHoCH leg**, still unfilled; note its **exact midpoint** | Tracks 1m FVGs, keeps only those formed at/after the leg origin and not yet violated |
| 4 | **Fibonacci** from the start of the move to now — the gap must sit **between 0.5 and 0.618** | Re-measures the leg every bar and checks the gap midpoint against the zone |
| 5 | Limit at the **midpoint**, stop **outside the FVG-producing sequence**, target **3–4R** | Resting limit order, stop beyond the low/high of all three gap candles, target default **4R** |

And the risk half, which he spends the first seven minutes on:

- **Everything is measured in R.** At 1:4, break-even is a 20% win rate; he runs 30–40%.
- **Percentage scaling** — risk a fixed % of the *current* balance, so risk shrinks
  automatically through a drawdown and grows as the account grows.
- **Step-downs as it scales** — *"once I make it to $1,000, now I'm going to use 5%."*
- **Size = $ risk ÷ (entry − stop) ÷ point value**, rounded down to a tradeable step.

---

## Install

1. TradingView → **Pine Editor** → paste `strategy/percoco_50_morning_model.pine` → **Add to chart**.
2. Set the chart to **1 minute**. Leave *Context timeframe* at **15**.
3. Set *Session timezone* to `America/New_York` and the window to `0930-1130`.
4. Open **Properties** and set **Initial capital**, **Commission** and **Slippage**
   to your broker's real numbers before you read a single backtest figure.

### Sizing settings that actually matter

`Position size step` and `Minimum position size` must match your instrument, or the
sizing maths is fiction:

| Instrument | Step | Min |
|---|---|---|
| Gold (XAUUSD spot/CFD, micro lots) | `0.01` | `0.01` |
| Futures (MNQ, MES, MGC — contracts) | `1` | `1` |
| Crypto perps | `0.001` | `0.001` |
| Stocks (whole shares) | `1` | `1` |

Leave **"Skip the trade if minimum size exceeds the risk budget"** ON. With it off,
a $50 account silently takes trades risking far more than you told it to — which is
precisely how small accounts die.

---

## About the risk default

The risk input ships at **10%**, because that is the plan in the video: a $250 account
risking $25 a trade, scaling to 5% at $1,000.

Understand what that means before you run it. At 10%, five losses in a row — routine
at a 30–40% win rate — takes $50 down to about $30. He is explicit that this is a
deliberate, aggressive small-account ramp and that **1–2% is the standard**. If you
are not testing a hypothesis with money you can lose entirely, set it to 1–2%.

The bot also enforces two brakes he doesn't mention: **max trades per day** (3) and a
**daily stop after −3R**.

---

## Honest limits

- **Backtest fidelity.** On 1-minute bars TradingView cannot see intrabar order of
  events. A bar that touches both stop and target is resolved by assumption, not fact.
  Treat the equity curve as indicative, never as a track record.
- **The CHoCH definition is mine.** The video demonstrates it visually rather than
  defining it numerically. This bot uses "close beyond the last confirmed swing point,
  against the prior structure," with an adjustable pivot strength. Tune `Swing pivot
  strength` until the CHoCH labels match where you'd mark them by hand.
- **The 15m "response" is quantified as a tap.** The video's phrasing is
  *"price pulls into one of these fair value gaps and then starts to have a response."*
  This is implemented as "price traded into a live 15m gap within N bars."
- **He says the public model is simplified.** *"There are a bunch of other things that
  I'm looking at on my chart, including proprietary indicators … things I don't share
  on YouTube."* This is the model as taught, not whatever he actually trades.

Forward-test on paper for a month before this touches real money. Nothing here is
financial advice.
