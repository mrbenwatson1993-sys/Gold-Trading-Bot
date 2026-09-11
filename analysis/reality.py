"""Is there an edge, and does it actually catch the big moves?"""
import sys
from dataclasses import replace
from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name
from tori.config import RiskConfig, simple

EQ = 250_000.0
R = lambda eq=EQ, **kw: RiskConfig(symbol="MGC", starting_equity=eq, **kw)

def show(candles, cfg, label, tf):
    r = run(candles, cfg, R())
    s = r.stats
    if not s.get("trades"):
        print(f"  {label}: no trades"); return
    ts = r.trades
    rs = sorted(t.r_multiple for t in ts)
    wins = [t.r_multiple for t in ts if t.r_multiple > 0]
    losses = [t.r_multiple for t in ts if t.r_multiple <= 0]
    rr = (sum(wins)/len(wins)) / abs(sum(losses)/len(losses)) if wins and losses else 0

    # how much of the available move did we actually keep?
    captured = [t.r_multiple / t.mfe_r for t in ts if t.mfe_r > 0.5]
    cap = sum(captured)/len(captured) if captured else 0

    big3 = sum(rs[-3:]); total = sum(rs)
    top10pct = sum(rs[-max(1, len(rs)//10):])
    over = lambda x: sum(1 for v in rs if v >= x)

    print(f"  {label}")
    print(f"     avg win {sum(wins)/len(wins):+.2f}R   avg loss "
          f"{sum(losses)/len(losses):+.2f}R   reward:risk {rr:.2f}:1   "
          f"win rate {len(wins)/len(ts)*100:.1f}%")
    print(f"     runners: >=3R {over(3):>4}  >=5R {over(5):>4}  >=10R {over(10):>4}   "
          f"biggest {rs[-1]:+.1f}R")
    print(f"     top 10% of trades = {top10pct/total*100 if total else 0:.0f}% of all profit; "
          f"best 3 alone = {big3/total*100 if total else 0:.0f}%")
    print(f"     capture: keeps {cap*100:.0f}% of the best price the trade ever saw "
          f"(avg peak {sum(t.mfe_r for t in ts)/len(ts):+.2f}R vs exit "
          f"{total/len(ts):+.2f}R)")

for path in sys.argv[1:]:
    candles = load_csv(path)
    bs = bar_seconds(candles); tf = timeframe_name(bs)
    base = simple().for_timeframe(bs)
    print(f"\n{'='*90}\n{tf}   {len(candles)} bars   "
          f"{candles[0].dt:%Y-%m-%d} .. {candles[-1].dt:%Y-%m-%d}\n{'='*90}")
    show(candles, replace(base, always_in=True), "always in", tf)
    show(candles, replace(base, always_in=False), "flat between setups", tf)

    first, last = candles[0].close, candles[-1].close
    peak, worst = first, 0.0
    for c in candles:
        peak = max(peak, c.high); worst = max(worst, (peak - c.low)/peak*100)
    print(f"  {'-'*86}")
    print(f"  BENCHMARK  buy & hold gold {(last-first)/first*100:+.1f}%  "
          f"(max DD {worst:.1f}%)")
    for lab, cfg in (("always in", replace(base, always_in=True)),
                     ("flat     ", replace(base, always_in=False))):
        s = run(candles, cfg, R()).stats
        if s.get("trades"):
            print(f"             strategy {lab}  {s['return_pct']:+.1f}%  "
                  f"(max DD {s['max_drawdown_pct']:.1f}%, PF {s['profit_factor']:.2f})")

    half = len(candles)//2
    for lab, cfg in (("always in", replace(base, always_in=True)),
                     ("flat     ", replace(base, always_in=False))):
        out = []
        for nm, seg in (("1st", candles[:half]), ("2nd", candles[half:])):
            s = run(seg, cfg, R()).stats
            out.append(f"{nm} {s['expectancy_r']:+.3f}R PF{s['profit_factor']:.2f} n={s['trades']}"
                       if s.get("trades") else f"{nm} none")
        print(f"  OUT-OF-SAMPLE {lab}   " + "  |  ".join(out))

    cells = []
    for slip in (0.0, 1.0, 2.0, 4.0):
        s = run(candles, replace(base, always_in=True), R(slippage_ticks=slip)).stats
        cells.append(f"{slip:.0f}tk {s['return_pct']:+7.1f}%" if s.get("trades") else "--")
    print("  COST SENSITIVITY      " + "  ".join(cells))
