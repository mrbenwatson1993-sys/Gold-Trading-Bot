import sys
from dataclasses import replace
from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)

def line(label, r):
    s = r.stats
    if not s.get("trades"):
        return f"  {label:<20}  no trades"
    pf = s["profit_factor"]
    pf = "inf" if pf == float("inf") else f"{pf:.2f}"
    skipped = sum(r.skipped.values())
    return (f"  {label:<20} {s['trades']:>5} {s['win_rate']:>6.1f} "
            f"{s['expectancy_r']:>+8.3f} {pf:>6} {s['avg_win_r']:>+7.2f} "
            f"{s['avg_loss_r']:>+7.2f} {s['return_pct']:>+8.1f} "
            f"{s['max_drawdown_pct']:>7.1f} {skipped:>6}")

HDR = (f"  {'mode':<20} {'n':>5} {'win%':>6} {'exp R':>8} {'PF':>6} {'avgW':>7} "
       f"{'avgL':>7} {'ret%':>8} {'maxDD%':>7} {'skip':>6}")

for path in sys.argv[1:]:
    candles = load_csv(path)
    bs = bar_seconds(candles)
    base = simple().for_timeframe(bs)
    print(f"\n{'='*100}")
    print(f"{path}  {len(candles)} bars of {timeframe_name(bs)}  "
          f"({candles[0].dt:%Y-%m-%d} .. {candles[-1].dt:%Y-%m-%d})")
    print('='*100)
    print(HDR)
    runs = {}
    for label, cfg in [
        ("flat between trades", replace(base, always_in=False)),
        ("always in (reverse)", replace(base, always_in=True)),
    ]:
        r = run(candles, cfg, RISK)
        runs[label] = r
        print(line(label, r))

    r = runs["always in (reverse)"]
    s = r.stats
    if s.get("trades"):
        print(f"  {'-'*96}")
        print("  always-in, split by touch count:")
        for n in sorted(s["by_touches"]):
            v = s["by_touches"][n]
            tag = "A+" if n >= 3 else ("B" if n == 2 else "C")
            print(f"     {n} touches ({tag:>2})  n={v['n']:<5} "
                  f"win {v['wins']/v['n']*100:>5.1f}%  avg {v['r']/v['n']:>+7.3f}R  "
                  f"total {v['r']:>+8.1f}R  net ${v['net']:>10,.0f}")
