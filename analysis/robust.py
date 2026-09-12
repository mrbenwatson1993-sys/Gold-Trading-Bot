"""Find the one parameter set that suits the most markets.

The discipline that matters here: a config is scored by applying it UNCHANGED
to every market. Picking the best settings per market is how a backtest lies.
A set that works on six markets at a mediocre level is worth far more than one
tuned to be spectacular on two, because only the first has any chance of
holding up on the seventh.

Scored by how many markets clear a profit factor of 1.2, then by the median
profit factor across all of them, then by the worst market -- so a config that
wins big somewhere and blows up elsewhere ranks below one that is merely
adequate everywhere.
"""
import statistics
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC"),
           ("SILVER", "data/silver_4h.csv", "SIL"),
           ("S&P", "data/spx500_4h.csv", "MES"),
           ("NASDAQ", "data/nas100_4h.csv", "MNQ"),
           ("BRENT", "data/brent_4h.csv", "MCL"),
           ("EURUSD", "data/eurusd_4h.csv", "M6E"),
           ("GBPUSD", "data/gbpusd_4h.csv", "M6B"),
           ("USDJPY", "data/usdjpy_4h.csv", "M6J"),
           ("AUDUSD", "data/audusd_4h.csv", "M6A")]

GRID = []
for tfs in (("1d", "1w"), ("1d", "1w", "1M")):
    for touches in (2, 3):
        for trail in (0.25, 0.50):
            GRID.append((f"{'+'.join(tfs)} t{touches} b{trail:.2f}",
                         dict(line_timeframes=tfs, min_touches=touches,
                              trail_buffer_atr=trail)))

DATA = {}
for name, path, sym in MARKETS:
    cs, _ = validate(load_csv(path))
    DATA[name] = (cs, sym)

results = {}
for label, kw in GRID:
    row = {}
    for name, path, sym in MARKETS:
        cs, sym = DATA[name]
        cfg = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                      htf_align="none", exit_on_stop_only=True,
                      stop_follows_safety=True, safety_line_redraw=False,
                      stop_on_close_only=False, stop_close_confirm_in_profit=True,
                      swing_strength=3, safety_swing_strength=12,
                      max_touches=99, **kw)
        s = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=250_000,
                                    risk_pct=1.0)).stats
        row[name] = (s.get("profit_factor", 0.0), s.get("return_pct", 0.0),
                     s.get("expectancy_r", 0.0), s.get("max_drawdown_pct", 0.0),
                     s.get("trades", 0))
    results[label] = row
    good = sum(1 for v in row.values() if v[0] >= 1.2)
    pfs = sorted(v[0] for v in row.values())
    print(f"  {label:<22} markets PF>=1.2: {good}/{len(row)}  "
          f"median PF {statistics.median(pfs):.2f}  worst PF {pfs[0]:.2f}  "
          f"mean ret {statistics.fmean(v[1] for v in row.values()):+.1f}%",
          flush=True)

print("\n\nBEST CONFIGS, market by market\n", flush=True)
ranked = sorted(results.items(), key=lambda kv: (
    -sum(1 for v in kv[1].values() if v[0] >= 1.2),
    -statistics.median([v[0] for v in kv[1].values()]),
    -min(v[0] for v in kv[1].values())))
for label, row in ranked[:3]:
    print(f"  === {label} ===", flush=True)
    print(f"     {'market':<7} {'n':>5} {'PF':>6} {'expR':>8} {'ret%':>9} {'DD%':>6}",
          flush=True)
    for name in sorted(row, key=lambda k: -row[k][0]):
        pf, ret, exp, dd, n = row[name]
        print(f"     {name:<7} {n:>5} {pf:>6.2f} {exp:>+8.3f} {ret:>+9.1f} {dd:>6.1f}",
              flush=True)
    print(flush=True)
