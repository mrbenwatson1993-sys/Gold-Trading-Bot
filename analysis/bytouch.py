"""Touch count vs performance, using ONLY genuine trendline-break entries."""
import sys
from dataclasses import replace
from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)

for path in sys.argv[1:]:
    candles = load_csv(path)
    bs = bar_seconds(candles)
    cfg = replace(simple().for_timeframe(bs), always_in=False)
    r = run(candles, cfg, RISK)
    s = r.stats
    print(f"\n{path}  {timeframe_name(bs)}  --  {s.get('trades',0)} break entries")
    if not s.get("trades"):
        continue
    agg = {"2 touches (B)": {"n":0,"r":0.0,"w":0}, "3+ touches (A+)": {"n":0,"r":0.0,"w":0}}
    for t in r.trades:
        k = "2 touches (B)" if t.signal.brk.line.touch_count == 2 else "3+ touches (A+)"
        agg[k]["n"] += 1; agg[k]["r"] += t.r_multiple
        agg[k]["w"] += 1 if t.net > 0 else 0
    for k, v in agg.items():
        if v["n"]:
            print(f"   {k:<18} n={v['n']:<4} win {v['w']/v['n']*100:>5.1f}%  "
                  f"avg {v['r']/v['n']:>+7.3f}R  total {v['r']:>+7.1f}R")
    detail = s["by_touches"]
    print("   detail: " + "  ".join(
        f"{n}t:n={detail[n]['n']},{detail[n]['r']/detail[n]['n']:+.2f}R"
        for n in sorted(detail)))
