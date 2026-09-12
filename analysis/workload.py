"""How much hands-on work does each entry timeframe actually demand?

The strategy is managed by hand, so the deciding question for a timeframe is
not only "does it make money" but "how often must I be at the screen, and how
long do I get to act". Three numbers answer that:

  * signals/month   -- how often a decision lands
  * median hold     -- in bars AND in wall-clock time
  * stop moves/day  -- the stop rides the line, so it is re-set once per bar
                       while a position is open

Entry is at the next bar's open, so the reaction window for placing a trade is
one bar. That is the number that decides whether you are rushing.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, recommended

TFS = [("4H", "data/gold_4h_16y.csv"), ("1H", "data/gold_1h_deep.csv"),
       ("15m", "data/gold_15m_deep.csv"), ("5m", "data/gold_5m.csv"),
       ("3m", "data/gold_3m.csv"), ("1m", "data/gold_1m.csv")]


def fmt(seconds):
    if seconds < 3600:
        return "%dm" % (seconds / 60)
    if seconds < 86400:
        return "%.1fh" % (seconds / 3600)
    return "%.1fd" % (seconds / 86400)


print("%-5s %7s %7s %9s %11s %10s %9s" % (
    "tf", "years", "trades", "per mo", "react win", "med hold", "stop/day"))
print("-" * 64)
for label, path in TFS:
    try:
        cs, _ = validate(load_csv(path))
    except FileNotFoundError:
        print("%-5s  (no data)" % label)
        continue
    bs = bar_seconds(cs)
    cfg = recommended().for_timeframe(bs)
    r = run(cs, cfg, RiskConfig(symbol="MGC", starting_equity=250_000.0,
                                risk_pct=1.0, compound=False))
    ts = r.trades
    if not ts:
        print("%-5s  (no trades)" % label)
        continue
    years = (cs[-1].ts - cs[0].ts) / 31_557_600
    holds = sorted(t.bars_held for t in ts)
    med = holds[len(holds) // 2]
    # bars per trading day, from the data itself rather than assuming 24h
    days = len({c.ts // 86400 for c in cs})
    bars_per_day = len(cs) / days
    rs = [t.r_multiple for t in ts]
    w = sum(x for x in rs if x > 0); l = -sum(x for x in rs if x < 0)
    print("%-5s %7.1f %7d %9.1f %11s %10s %9.1f   (%+.3fR pf%.2f)" % (
        label, years, len(ts), len(ts) / (years * 12), fmt(bs),
        fmt(med * bs), bars_per_day, sum(rs) / len(rs), (w / l) if l else 99),
        flush=True)
