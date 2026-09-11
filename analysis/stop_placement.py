"""Where should the stop actually sit?

Two readings of "the stop moves up with price":

  line   -- the stop rides the Safety Line itself, which keeps rising past the
            swing it was anchored to, so it sits close under price.
  prev HL-- the stop steps up to the previous higher low and waits there.
            Because the line rises above that swing, this is the looser of the
            two and gives the trade more room.

In both cases a candle CLOSING back through the line still ends the trade; the
stop only decides how much room price has before that close arrives.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("SILVER", "data/silver_4h.csv", "SIL")]

print(f"  {'market':<7} {'stop at':<9} {'tch':<3} {'n':>5} {'hold':>6} {'expR':>8} "
      f"{'PF':>6} {'avgW':>7} {'best':>7} {'>=5R':>6} {'>=10R':>6} "
      f"{'ret%':>9} {'DD%':>6}")
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", stop_on_close_only=False,
                   swing_strength=3, safety_swing_strength=12)
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    for stop_label, follows in (("line", True), ("prev HL", False)):
        for tch in (3, 5):
            cfg = replace(base, stop_follows_safety=follows,
                          min_touches=tch, max_touches=99)
            r = run(cs, cfg, risk)
            s = r.stats
            if not s.get("trades"):
                print(f"  {name:<7} {stop_label:<9} {tch:<3}  -- none"); continue
            ts = r.trades
            rs = [t.r_multiple for t in ts]
            n = len(ts)
            hold = sum(t.exit_index - t.entry_index for t in ts) / n
            pc = lambda x: f"{sum(1 for v in rs if v >= x)/n*100:>5.1f}%"
            print(f"  {name:<7} {stop_label:<9} {tch:<3} {n:>5} {hold:>6.1f} "
                  f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
                  f"{s['avg_win_r']:>+7.2f} {max(rs):>+7.1f} {pc(5)} {pc(10)} "
                  f"{s['return_pct']:>+9.1f} {s['max_drawdown_pct']:>6.1f}",
                  flush=True)
    print(flush=True)
