"""Is platinum actually the best market for this method?

Tori recommends it. Testing that needs a like-for-like comparison, which is
the part that is easy to get wrong: platinum intraday history is short, so
comparing 2 years of platinum against 16 years of gold would say more about
the eras than about the metals.

So both comparisons here are same-symbol-source, same-window:
  * 4H over the last two years (Yahoo PL=F / GC=F / SI=F, 1H resampled)
  * daily over the last ten years (same three symbols)

All three are sized as SPOT/CFD (1 unit = 1 point, fractional size) because
that is how Vantage/MT5 trades them -- and because whole-contract rounding on
three metals of very different point values would otherwise distort the
comparison rather than inform it.

Caveat the numbers cannot show: CFD spreads. Gold spot typically quotes a few
cents wide; platinum is far thinner and routinely 1-3 dollars. The R-multiples
below charge almost nothing for that, so platinum is flattered here relative
to what a real Vantage ticket would cost.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, recommended

SETS = [
    ("4H, last 2 years", [("PLATINUM", "data/platinum_4h_2y.csv"),
                          ("GOLD", "data/goldfut_4h_2y.csv"),
                          ("SILVER", "data/silverfut_4h_2y.csv")]),
    ("daily, last 10 years", [("PLATINUM", "data/platinum_1d_10y.csv"),
                              ("GOLD", "data/goldfut_1d_10y.csv"),
                              ("SILVER", "data/silverfut_1d_10y.csv")]),
]
SYM = {"PLATINUM": "SPOT", "GOLD": "SPOT", "SILVER": "SPOT"}

for title, markets in SETS:
    print(f"\n  {title}")
    print("  %-9s %6s %7s %8s %7s %8s %8s" % (
        "market", "bars", "trades", "avg R", "PF", "win%", "best"))
    print("  " + "-" * 56)
    for name, path in markets:
        cs, rep = validate(load_csv(path))
        cfg = recommended().for_timeframe(bar_seconds(cs))
        r = run(cs, cfg, RiskConfig(symbol=SYM[name], starting_equity=250_000.0,
                                    risk_pct=1.0, compound=False))
        rs = [t.r_multiple for t in r.trades]
        if not rs:
            print("  %-9s %6d %7s" % (name, len(cs), "none"))
            continue
        w = sum(x for x in rs if x > 0); l = -sum(x for x in rs if x < 0)
        print("  %-9s %6d %7d %+8.3f %7.2f %7.1f%% %+7.2fR" % (
            name, len(cs), len(rs), sum(rs) / len(rs), (w / l) if l else 99,
            100 * sum(1 for x in rs if x > 0) / len(rs), max(rs)), flush=True)
