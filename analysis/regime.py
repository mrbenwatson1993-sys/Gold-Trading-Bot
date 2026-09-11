"""Is the HTF-alignment effect about timeframe, or about regime?

The 4H series covers 18 months including gold's bull run; the 1H series only
the last 7 months, where it topped and chopped. So run 4H over *both* windows
and see which explanation survives.
"""
from dataclasses import replace
from datetime import datetime, timezone
from tori.backtest import run
from tori.candles import bar_seconds, load_csv
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)
cs = load_csv('data/gold_4h.csv')
bs = bar_seconds(cs)
base = replace(simple().for_timeframe(bs), always_in=False)
cut = int(datetime(2026, 2, 14, tzinfo=timezone.utc).timestamp())
early = [c for c in cs if c.ts < cut]
late = [c for c in cs if c.ts >= cut]

print(f"  early {early[0].dt:%Y-%m-%d}..{early[-1].dt:%Y-%m-%d}  "
      f"{len(early)} bars  gold {early[0].close:.0f}->{early[-1].close:.0f} "
      f"({(early[-1].close/early[0].close-1)*100:+.0f}%)")
print(f"  late  {late[0].dt:%Y-%m-%d}..{late[-1].dt:%Y-%m-%d}  "
      f"{len(late)} bars  gold {late[0].close:.0f}->{late[-1].close:.0f} "
      f"({(late[-1].close/late[0].close-1)*100:+.0f}%)")
print()
print(f"  {'window':<8} {'touches':<10} {'htf':<9} {'n':>4} {'expR':>8} {'PF':>6} {'ret%':>7}")
for wname, seg in (("early", early), ("late", late), ("all", cs)):
    for tlabel, lo, hi in (("any 2+", 2, 99), ("exactly 3", 3, 3)):
        for align in ("none", "soft", "majority"):
            cfg = replace(base, min_touches=lo, max_touches=hi, htf_align=align)
            s = run(seg, cfg, RISK).stats
            if not s.get("trades"):
                print(f"  {wname:<8} {tlabel:<10} {align:<9}   -- no trades"); continue
            print(f"  {wname:<8} {tlabel:<10} {align:<9} {s['trades']:>4} "
                  f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
                  f"{s['return_pct']:>+7.1f}")
        print()
