"""Why does a faster entry chart degrade, and is it fixable?

Two candidates, with very different implications:

1. Costs. A faster chart takes several times as many trades, each paying a
   round turn. If that is the whole story, better execution or a larger
   contract fixes it.
2. Noise. The higher-timeframe line predicts a multi-day move; a stop placed
   at 15-minute scale is inside the noise of that move and gets hit before the
   move happens. If that is the story, nothing about execution helps.

Also removes a confound: the 15m series starts in 2015, which is precisely
gold's weakest era, so part of its poor showing may be the sample rather than
the timeframe. Each entry chart is therefore also run over the period they all
share.
"""
from dataclasses import replace
from datetime import datetime, timezone

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, recommended

SETS = [("GOLD", "MGC", [("4h", "data/gold_4h_16y.csv"),
                         ("1h", "data/gold_1h_deep.csv"),
                         ("15m", "data/gold_15m_deep.csv")]),
        ("GBPUSD", "M6B", [("4h", "data/gbpusd_4h.csv"),
                           ("1h", "data/gbpusd_1h.csv"),
                           ("15m", "data/gbpusd_15m.csv")])]
START = datetime(2015, 9, 3, tzinfo=timezone.utc).timestamp()

print("COSTS -- same runs with slippage and commission removed\n", flush=True)
print(f"  {'market':<7} {'entry':<5} {'n':>5} {'PF real':>8} {'PF free':>8} "
      f"{'ret real':>9} {'ret free':>9}  {'cost drag':>10}", flush=True)
for name, sym, files in SETS:
    for label, path in files:
        cs, _ = validate(load_csv(path))
        cfg = replace(recommended().for_timeframe(bar_seconds(cs)))
        real = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=250_000,
                                       risk_pct=1.0)).stats
        free = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=250_000,
                                       risk_pct=1.0, slippage_ticks=0.0)).stats
        if not real.get("trades"):
            continue
        print(f"  {name:<7} {label:<5} {real['trades']:>5} "
              f"{real['profit_factor']:>8.2f} {free['profit_factor']:>8.2f} "
              f"{real['return_pct']:>+9.1f} {free['return_pct']:>+9.1f}  "
              f"{free['return_pct']-real['return_pct']:>+9.1f}%", flush=True)
    print(flush=True)

print("\nSAMPLE -- every entry chart over the same period (2015-09 on)\n", flush=True)
print(f"  {'market':<7} {'entry':<5} {'n':>5} {'/yr':>5} {'win%':>6} {'RR':>5} "
      f"{'expR':>8} {'PF':>5} {'ret%':>8} {'DD%':>6}", flush=True)
for name, sym, files in SETS:
    for label, path in files:
        cs, _ = validate(load_csv(path))
        seg = [c for c in cs if c.ts >= START]
        if len(seg) < 3000:
            print(f"  {name:<7} {label:<5}  -- too little data", flush=True)
            continue
        bs = bar_seconds(seg)
        cfg = replace(recommended().for_timeframe(bs))
        r = run(seg, cfg, RiskConfig(symbol=sym, starting_equity=250_000,
                                     risk_pct=1.0))
        s = r.stats
        if not s.get("trades"):
            print(f"  {name:<7} {label:<5}  -- no trades", flush=True); continue
        years = (seg[-1].ts - seg[0].ts) / (365.25 * 86400)
        rr = abs(s["avg_win_r"] / s["avg_loss_r"]) if s["avg_loss_r"] else 0
        print(f"  {name:<7} {label:<5} {s['trades']:>5} {s['trades']/years:>5.1f} "
              f"{s['win_rate']:>6.1f} {rr:>5.2f} {s['expectancy_r']:>+8.3f} "
              f"{s['profit_factor']:>5.2f} {s['return_pct']:>+8.1f} "
              f"{s['max_drawdown_pct']:>6.1f}", flush=True)
    print(flush=True)
