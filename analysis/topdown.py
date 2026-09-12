"""Top-down lines: drawn on the higher timeframes, traded on this one.

Every earlier result drew its lines from the traded chart's own swings. This
draws them the way the method prescribes -- on the daily, weekly and monthly --
projects them onto the 4-hour chart and trades the break there.

The reason to expect this to matter: the only detector change that produced a
real signal was the one that made lines rarer and more significant (760 S&P
breaks down to 50). Higher-timeframe structure is a principled way to get that
selectivity instead of a tuned threshold.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("S&P", "data/spx500_4h.csv", "MES"),
           ("NASDAQ", "data/nas100_4h.csv", "MNQ"),
           ("BRENT", "data/brent_4h.csv", "MCL"),
           ("EURUSD", "data/eurusd_4h.csv", "M6E"),
           ("SILVER", "data/silver_4h.csv", "SIL")]
VARIANTS = [("own 4h", ()), ("daily", ("1d",)),
            ("daily+wk", ("1d", "1w")), ("d+w+monthly", ("1d", "1w", "1M"))]

print(f"  {'market':<7} {'lines from':<12} {'n':>5} {'win%':>6} {'expR':>8} "
      f"{'PF':>6} {'avgW':>7} {'best':>7} {'worst':>7} {'ret%':>9} {'DD%':>6}",
      flush=True)
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    base = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                   htf_align="none", exit_on_stop_only=True,
                   stop_follows_safety=True, safety_line_redraw=False,
                   stop_on_close_only=False, stop_close_confirm_in_profit=True,
                   trail_buffer_atr=0.50, swing_strength=3,
                   safety_swing_strength=12, min_touches=3, max_touches=99)
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    for label, tfs in VARIANTS:
        r = run(cs, replace(base, line_timeframes=tfs), risk)
        s = r.stats
        if not s.get("trades"):
            print(f"  {name:<7} {label:<12}  -- no trades", flush=True); continue
        rs = [t.r_multiple for t in r.trades]
        print(f"  {name:<7} {label:<12} {s['trades']:>5} {s['win_rate']:>6.1f} "
              f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
              f"{s['avg_win_r']:>+7.2f} {max(rs):>+7.1f} {min(rs):>+7.2f} "
              f"{s['return_pct']:>+9.1f} {s['max_drawdown_pct']:>6.1f}", flush=True)
    print(flush=True)
