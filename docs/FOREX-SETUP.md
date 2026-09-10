# Running it on EURUSD and GBPUSD

## ⚠ Read this first: the two pairs are the same trade

EURUSD and GBPUSD typically run a **+0.85 to +0.90 correlation**. Both are quoted
against the dollar, and most of what moves them is the dollar, not the euro or the
pound.

Two consequences, and neither is optional:

**1. Simultaneous setups are one position, not two.** When both pairs sweep their lows
and shift bullish in the same London session — which is exactly what happens, because
the same dollar move caused both — taking 1% on each is not two 1% trades. It is a
single 2% bet on the dollar falling, wearing a disguise. When it's wrong, both stops
go together.

Cap your **total open risk**, not your per-trade risk. If both fire, take 0.5% each, or
take the cleaner setup only and skip the other.

**2. Backtesting both is not two tests.** If the model shows an edge on both pairs,
that is roughly *one* piece of evidence repeated, not independent confirmation. To
actually corroborate, test something uncorrelated — USDJPY, AUDNZD, or a non-FX
instrument.

---

## Settings

Both pairs, both tools:

| Input | Value |
|---|---|
| Chart timeframe | **5 minutes** |
| Session timezone | `Europe/London` |
| Asia | `0000-0800` |
| London | `0800-1300` |
| New York | `1300-2100` |
| Fractal strength | `2` (classic 5-bar Williams) |
| Require BODY close | **on** |
| Fib entry | `0.618` |
| Take profit | `2.0` R |
| Max setups per session | `1` |

### Alert tool — position size

| Input | Value |
|---|---|
| Work out the lot size for me | on |
| Account balance | yours, **in USD** — see the note below |
| Risk per trade | `1.0`% (`0.5`% if you're running both pairs) |
| Units per standard lot | `100000` |
| Lot step | `0.01` (micro lots) |

The alert then arrives ready to execute:

```
🔻 SETUP ARMED · SHORT GBPUSD 5
London swept Asia HIGH · structure shifted
Entry (0.618): 1.27345
Stop:          1.27612
Target (2R):   1.26811
Risk:          26.7 pips
Size:          0.37 lots   (100.00 USD at risk)
```

**Account currency.** Both pairs are quoted in USD, so profit, loss and the risk figure
are all in **USD**. If your account is in GBP, enter your balance converted to USD, or
read the risk figure as approximate at the current rate. The lot size itself is correct
either way — it's derived from the stop distance, not from your account currency.

### Backtest — sizing

| Input | Value |
|---|---|
| Position size step | `1000` (one micro lot) |
| Minimum position size | `1000` |
| Skip if minimum exceeds risk budget | **on** |
| Risk per trade | `Fixed cash` while you're judging the edge |

Forex quantity on TradingView is in **units of the base currency**: 1,000 units = 0.01
lots = one micro lot. These are now the defaults.

---

## Costs, which decide this strategy

Set **Properties → Slippage** in ticks. On a 5-digit feed **1 pip = 10 ticks**.

| Pair | Typical spread | Use |
|---|---|---|
| EURUSD | 0.1 – 0.8 pip | `5` ticks (0.5 pip) |
| GBPUSD | 0.4 – 1.5 pips | `10` ticks (1.0 pip) |

Widen both during Asia and around news. On a 25 pip stop, a 1 pip spread is 4% of your
risk and it comes out of the win side only — over 200 trades that alone can flip a
marginal edge negative. GBPUSD's wider spread is the reason to test it separately from
EURUSD rather than assuming what works on one works on the other.

## Daylight saving

`Europe/London` shifts with BST, so the London session stays correct year-round — the
right choice for these two pairs. The trade-off is that Asia and New York drift by an
hour twice a year relative to their own local clocks, and the US and UK change dates
don't line up, so there are two or three weeks each year where the boxes are an hour
out.

If that bothers you, run `UTC` and accept that London open moves instead. There is no
setting that keeps all three sessions perfectly anchored.

## Running all three sessions, every day

All three toggles ship **on**, so there is nothing to switch — just confirm *Trade
Asia / London / New York* are all ticked. With *Max setups per session* at 1 that is up
to **3 setups per pair per day**.

Two guards were added specifically because you're running the full schedule:

**Stale previous range.** *Previous range goes stale after (hours)* — default **12**.
Without it, Monday's Asia session sweeps **Friday New York's** range: a level roughly 51
hours old with a weekend gap sitting in the middle of it. 12 hours clears every normal
handover (the longest is the 3-hour quiet spell before Asia opens) and rejects the
weekend carry-over. The status panel shows `prev range stale - skipping` when it bites,
so you'll know why Monday's first session was quiet. Set it to 0 if you'd rather take
those.

**Weekend flat.** *Close any open trade before the weekend* — default **on** in the
backtest. A stop does not protect you across a Sunday gap; that's how a −1R becomes
−4R. It closes anything still open when Friday's New York session ends. It will change
your results, and that is the point — leave it on unless you can explain why holding
through a gap is worth it.

### The arithmetic to look at before you start

Three sessions × two pairs = **up to 6 setups a day**. At 1% each that is 6% of the
account at risk daily — and per the correlation warning at the top, those six positions
are mostly one bet on the dollar wearing six hats.

Concretely: London sweeps the Asia low on both EURUSD and GBPUSD, both shift bullish,
both fill. That's 2% on "the dollar falls this morning". If New York then does the same
thing, you're at 4% on the same idea before lunch.

Decide a **daily risk cap** now, while it's arithmetic rather than a losing morning.
Something like: 1% per trade, 3% total open, stop for the day at −3R. The backtest's
*worst losing streak* row will tell you whether that cap would have cut off trades that
later won — run it and find out before you pick the number, not after.

## Two things worth testing before you commit

**Turn Asia off.** EUR and GBP liquidity is thin during Asian hours, so the Asia session
sweeping the previous New York range is the weakest of the three on these pairs — a
hypothesis, not a fact, which is what the per-session breakdown in the backtest panel
is for. Run it with all three on, read the split, then decide.

The classic version of this setup is **London sweeping the Asia range** — a narrow
overnight range taken out and reversed on the London open. If the model has an edge on
these pairs, expect to find it concentrated there.

**Check the news calendar.** Both pairs move violently on 13:30 UK time US data and on
BoE/Fed decisions. A 5-minute structure shift into an NFP print is not a setup, it's a
coin flip with a spread attached. Neither tool knows what day it is — that filter is
yours to apply.
