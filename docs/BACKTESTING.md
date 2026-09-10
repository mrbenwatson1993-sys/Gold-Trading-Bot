# Backtesting the sweep → MSS → 0.618 model

`strategy/session_sweep_mss_618_backtest.pine` is the same detection logic as the
alert indicator, wired to TradingView's backtester. What you measure here is what the
alert tool will send you.

## Run it

1. 5-minute chart, the pair you actually intend to trade.
2. Pine Editor → paste → Add to chart.
3. **Properties tab — do this before reading anything:**

   | Setting | Why |
   |---|---|
   | **Commission** | Your broker's real commission |
   | **Slippage** | Your typical spread, in ticks. On a 5-digit pair, 1 pip = **10 ticks** |
   | Initial capital | Something realistic |
   | Order size | Ignore it — the script sizes every trade itself from your risk input |

   A 1 pip spread against a 25 pip stop is **4% of your risk on every trade**, and it
   only ever comes out of the win side. Backtests with zero costs are how strategies
   look profitable right up until they aren't.

4. Set **Risk per trade** to `Fixed cash`. Every trade then risks exactly 1R, so net
   profit ÷ risk reads straight off as total R with no compounding distortion. Switch
   to percent-of-equity later, once you know whether there's an edge at all.

## The panel

```
SESSION     TRADES  WINS   WIN%      R
Asia            41    16  39.0%   +2.3R
London          63    24  38.1%   +9.0R
New York        58    17  29.3%   -6.9R
TOTAL          162    57  35.2%   +4.4R

break-even win rate            33.3%
expectancy per trade          +0.03R
worst losing streak                9
```

(Illustrative numbers, not results — run it yourself.)

**Break-even win rate** is `1 / (1 + R)` — at 2:1 that's **33.3%**. Below it you are
losing money no matter how good the screenshots looked.

**Expectancy per trade** is the number that matters. `+0.03R` over 162 trades is
statistically indistinguishable from zero; it is not an edge, it is noise with a
positive sign. You want something you'd still believe after another 200 trades.

**Worst losing streak** tells you what you actually have to sit through. At a 35% win
rate, a run of 9 losses is unremarkable. If that would make you abandon the system or
double your size, the system is not tradeable by you at that risk level.

**The per-session split is the point of this panel.** He says he tracked "my entry
times, my days". If one session carries all the profit and another bleeds, that is far
more useful than the total — turn the losing session off and re-run, then ask whether
that's a real effect or you just curve-fitted to 40 trades.

## Reading it honestly

**Sample size.** Under ~100 trades per session, conclusions are guesses. Run several
years, and check the pair you'll actually trade — an edge on GBPUSD is not an edge on
XAUUSD.

**Intrabar ambiguity.** On 5-minute bars TradingView cannot see whether the entry or
the stop came first inside a candle that touched both. Those trades are resolved by
assumption. Nothing you do fixes this; it just means the number is softer than it
looks. If results hinge on a handful of trades, they aren't real.

**Don't tune until it looks good.** Every input you adjust while watching the total R
is a way of fitting the past. Change one thing, have a reason, re-run, keep notes. If
you need the fractal strength at exactly 3 and the Asia session off and the fib at
0.65 to get profit, you have found nothing.

**Then forward-test.** Log the live alerts for a month without trading them and compare
that R to the backtest. If the live number is much worse, the backtest was optimistic —
usually costs, usually intrabar fills.

## The comparison worth making

The video shows five trades — three wins, two losses — and calls the strategy
"absolutely unbelievable." Five trades at a 2:1 target tells you nothing; that exact
result has better than a one-in-three chance of occurring from a coin flip.

Run a few thousand bars and see what number comes back. That's the whole reason this
file exists.
