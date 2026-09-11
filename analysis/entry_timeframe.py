"""Same lines, faster entry chart.

The trendlines stay exactly where they are -- drawn on the monthly, weekly and
daily -- and only the chart the break is taken on changes. Two things should
follow: more trades, because a finer chart resolves more crossings of the same
line; and larger R multiples, because the stop sits closer in absolute terms
while the structural move being captured is unchanged.

The ladder rules are scaled from a fixed 4-hour reference rather than from the
entry chart, so the daily line is the same daily line in every row here. That
is what makes the comparison mean anything.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name, validate
from tori.config import RiskConfig, recommended

SETS = [
    ("GOLD", "MGC", [("4h", "data/gold_4h_16y.csv"),
                     ("1h", "data/gold_1h_deep.csv"),
                     ("15m", "data/gold_15m_deep.csv")]),
    ("S&P", "MES", [("4h", "data/spx500_4h.csv"),
                    ("1h", "data/spx500_1h.csv"),
                    ("15m", "data/spx500_15m.csv")]),
    ("GBPUSD", "M6B", [("4h", "data/gbpusd_4h.csv"),
                       ("1h", "data/gbpusd_1h.csv"),
                       ("15m", "data/gbpusd_15m.csv")]),
]

print(f"  {'market':<7} {'entry':<5} {'yrs':>4} {'n':>5} {'/yr':>5} {'/mo':>5} "
      f"{'win%':>6} {'avgW':>6} {'avgL':>6} {'RR':>5} {'best':>7} {'hold':>7} "
      f"{'expR':>8} {'PF':>5} {'ret%':>8} {'DD%':>6}", flush=True)
for name, sym, files in SETS:
    for label, path in files:
        cs, _ = validate(load_csv(path))
        bs = bar_seconds(cs)
        cfg = replace(recommended().for_timeframe(bs),
                      line_timeframes=("1d", "1w", "1M"))
        r = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=250_000,
                                    risk_pct=1.0))
        s = r.stats
        years = (cs[-1].ts - cs[0].ts) / (365.25 * 86400)
        if not s.get("trades"):
            print(f"  {name:<7} {label:<5} {years:>4.1f}  -- no trades", flush=True)
            continue
        ts = r.trades
        rs = [t.r_multiple for t in ts]
        n = len(ts)
        hold = sum(t.exit_index - t.entry_index for t in ts) / n * bs / 86400
        rr = abs(s["avg_win_r"] / s["avg_loss_r"]) if s["avg_loss_r"] else 0
        print(f"  {name:<7} {label:<5} {years:>4.1f} {n:>5} {n/years:>5.1f} "
              f"{n/years/12:>5.1f} {s['win_rate']:>6.1f} {s['avg_win_r']:>+6.2f} "
              f"{s['avg_loss_r']:>+6.2f} {rr:>5.2f} {max(rs):>+7.1f} "
              f"{hold:>6.1f}d {s['expectancy_r']:>+8.3f} "
              f"{s['profit_factor']:>5.2f} {s['return_pct']:>+8.1f} "
              f"{s['max_drawdown_pct']:>6.1f}", flush=True)
    print(flush=True)
