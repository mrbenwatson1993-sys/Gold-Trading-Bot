"""The real forward test: does it still work after the data I built it on?

Every result in this project comes from series ending 2023-09-11. XAUT runs to
today, so the period from 2023-09-12 onward was never seen while any of these
choices were being made -- not by the parameter search, not by the market
selection, not by me.

The engine runs over the whole series so lines can form from earlier
structure, exactly as it would live; only the trades entered after the cutoff
are scored.
"""
import statistics
from dataclasses import replace
from datetime import datetime, timezone

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, recommended

CUT = datetime(2023, 9, 12, tzinfo=timezone.utc).timestamp()
SERIES = [("XAUT gold", "data/recent_xaut_4h.csv", "MGC"),
          ("PAXG gold", "data/recent_gold_4h.csv", "MGC")]


def report(label, trades, years):
    if not trades:
        print(f"  {label:<22}  -- no trades", flush=True); return
    rs = [t.r_multiple for t in trades]
    wins = [t for t in trades if t.net > 0]
    gw = sum(t.net for t in wins)
    gl = abs(sum(t.net for t in trades if t.net <= 0))
    pf = gw / gl if gl else float("inf")
    eq, peak, dd = 0.0, 0.0, 0.0
    for t in trades:
        eq += t.net
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    rr = 0.0
    losses = [r for r in rs if r <= 0]
    if wins and losses:
        rr = statistics.fmean([t.r_multiple for t in wins]) / abs(statistics.fmean(losses))
    print(f"  {label:<22} {len(trades):>5} {len(trades)/years/12:>6.1f} "
          f"{len(wins)/len(trades)*100:>6.1f} {rr:>5.2f} {max(rs):>+7.1f} "
          f"{statistics.fmean(rs):>+8.3f} {pf:>6.2f} {eq:>+11,.0f}", flush=True)


print(f"  {'window':<22} {'n':>5} {'/mo':>6} {'win%':>6} {'RR':>5} {'best':>7} "
      f"{'expR':>8} {'PF':>6} {'net $':>11}", flush=True)
for name, path, sym in SERIES:
    cs, _ = validate(load_csv(path))
    cfg = replace(recommended().for_timeframe(bar_seconds(cs)))
    r = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=250_000,
                                risk_pct=1.0, compound=False))
    before = [t for t in r.trades if t.entry_ts < CUT]
    after = [t for t in r.trades if t.entry_ts >= CUT]
    yrs = lambda ts: max(0.01, (cs[-1].ts - ts) / (365.25 * 86400))
    span_all = (cs[-1].ts - cs[0].ts) / (365.25 * 86400)
    print(f"\n  {name}  ({cs[0].dt:%Y-%m-%d} .. {cs[-1].dt:%Y-%m-%d})", flush=True)
    report("  all data", r.trades, span_all)
    if before:
        report("  up to 2023-09 (seen)", before,
               max(0.01, (CUT - cs[0].ts) / (365.25 * 86400)))
    report("  AFTER 2023-09 (unseen)", after, yrs(CUT))
