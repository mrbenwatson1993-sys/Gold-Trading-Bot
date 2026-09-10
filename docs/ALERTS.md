# Getting the alerts on your phone

The indicator does the watching. You do the clicking.

## One-time setup

1. Open a **5-minute** chart of the pair you want (he backtested GBPUSD).
2. **Pine Editor** → paste `indicator/session_sweep_mss_618.pine` → **Add to chart**.
3. Check the session boxes line up with your broker's day. The defaults are UTC:
   Asia `0000-0800`, London `0800-1300`, New York `1300-2100`. If your chart is in
   another timezone the boxes will look shifted — change *Session timezone*, not the
   session strings.
4. Click the **alarm clock** icon → **Create Alert**:

   | Field | Set it to |
   |---|---|
   | Condition | `Session Sweep → MSS → 0.618` |
   | Trigger | **`Any alert() function call`** |
   | Frequency | **`Once Per Bar`** |
   | Expiration | as far out as your plan allows |
   | Notifications | **Push notification** (needs the TradingView mobile app, logged into the same account) |

   Leave the message box alone — the indicator writes the whole message itself.

5. **Create**. Alerts run on TradingView's servers, so you can close the chart and
   your laptop.

One alert covers one pair. For four pairs you need four alerts, each created from a
chart of that pair.

## What you'll receive

**👀 SWEEP** *(off by default)* — the previous session's high or low has been taken.
Nothing to do yet; this is just a heads-up that the pair is in play.

**🔻 SETUP ARMED** — this is the one that matters. Structure has shifted and the fib
is drawn. Place your order:

```
🔻 SETUP ARMED · SHORT GBPUSD 5
New York swept London HIGH · structure shifted
Entry (0.618): 1.27345
Stop:          1.27612
Target (2R):   1.26811
Risk:          26.7 pips
```

Place a **limit** at the entry, a stop at the stop, a take profit at the target. Then
leave it alone.

**LEVEL MOVED** — the leg kept running after the shift, so the 0.618 has moved. Your
resting order is now at the wrong price; amend it to the new numbers. This is what a
manual trader does when they redraw the fib on a leg that extends, and it is why the
alert exists rather than leaving you with a stale order.

If you would rather the level be frozen the moment structure shifts, turn off
*"Redraw the fib while the leg keeps running"* and these alerts stop.

**ENTRY TAPPED** — price reached the 0.618. If your limit was resting, you're in. If
you prefer to enter manually on the tap, this is your cue.

**✅ TARGET / ❌ STOP** — the outcome. Useful for keeping your own R tally, which is
the only statistic this method actually runs on.

## Things that will trip you up

**The level-moved alerts can be chatty** on a strong leg. Raise *"only re-alert if the
level moved more than (pips)"* from 1.0 to 3–5 to quieten it.

**Alerts expire.** Depending on your plan, somewhere between a few weeks and a few
months. Put a recurring reminder in your calendar — a dead alert is indistinguishable
from a quiet market.

**Sweep direction on a two-sided bar.** If a single 5-minute candle takes both the
previous session's high *and* low, nobody can tell from the candle which went first.
The indicator assumes a down-closing bar ran the high first and vice versa, and marks
the sweep accordingly. On those bars, check the 1-minute chart before you trust it.

**Confirmation.** *"Confirm structure signals on bar close"* is on by default, so a
shift is only called on a closed candle — matching the video's insistence on a **body
close**. Turning it off will give you earlier signals that sometimes un-print.

**One setup per session** by default. Raise *Max setups per session* if you want the
indicator to re-arm after a result.

## Before you size up

The video shows a handful of hand-picked examples and reports 3 wins / 2 losses across
them. That is a demonstration, not evidence. The "years of backtested data" he offers
is behind a Discord join, and you have not seen it.

Log your own alerts for a month without trading them, count the R, and compare it to
what you were told. At 2:1 you need better than a **33% win rate** just to break even
before spread and commission — and on a 5-minute forex chart, spread is not a rounding
error.
