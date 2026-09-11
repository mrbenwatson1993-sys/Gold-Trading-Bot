"""Most trades and most profit are the same question, via drawdown.

Adding markets lowers the trade count per market but lowers portfolio drawdown
faster, because the markets take turns failing. Drawdown is what actually caps
position size, so the portfolio that draws down least is the one that can be
risked hardest -- and therefore the one that makes the most, not just the one
that trades the most.

So each portfolio is scaled to a common 20% drawdown budget and the resulting
return compared on equal risk terms. Scaling is linear because sizing is
fixed-fractional and not compounded.
"""
import itertools
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, recommended

MARKETS = [("GOLD", "MGC", "data/gold_4h_16y.csv"),
           ("S&P", "MES", "data/spx500_4h.csv"),
           ("GBPUSD", "M6B", "data/gbpusd_4h.csv"),
           ("SILVER", "SIL", "data/silver_4h.csv"),
           ("EURUSD", "M6E", "data/eurusd_4h.csv"),
           ("NASDAQ", "MNQ", "data/nas100_4h.csv"),
           ("BRENT", "MCL", "data/brent_4h.csv")]
EQUITY = 250_000.0
DD_BUDGET = 20.0
MAX_SLEEVE_RISK = 2.0     # never risk more than this per trade on one market

STREAMS = {}
for name, sym, path in MARKETS:
    cs, _ = validate(load_csv(path))
    cfg = replace(recommended().for_timeframe(bar_seconds(cs)))
    r = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=EQUITY,
                                risk_pct=1.0, compound=False))
    STREAMS[name] = [(t.exit_ts, t.r_multiple) for t in r.trades]
    print(f"  loaded {name}: {len(r.trades)} trades", flush=True)


def curve(names, sleeve_pct):
    stream = sorted(itertools.chain.from_iterable(STREAMS[n] for n in names))
    per = EQUITY * sleeve_pct / 100.0
    eq, peak, dd, wins = EQUITY, EQUITY, 0.0, 0
    for _, r in stream:
        eq += r * per
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak * 100)
        wins += 1 if r > 0 else 0
    span = (stream[-1][0] - stream[0][0]) / (365.25 * 86400)
    return (len(stream), len(stream) / span / 12, wins / len(stream) * 100,
            (eq - EQUITY) / EQUITY * 100, dd, span)


print(f"\n  Each portfolio scaled to a {DD_BUDGET:.0f}% drawdown budget "
      f"(sleeve risk capped at {MAX_SLEEVE_RISK:.0f}%)\n", flush=True)
print(f"  {'portfolio':<44} {'/mo':>6} {'sleeve%':>8} {'DD%':>6} {'ret%':>9} "
      f"{'%/yr':>7}", flush=True)
order = [m[0] for m in MARKETS]
best = None
for k in range(1, len(order) + 1):
    combo = order[:k]
    n, per_mo, win, ret1, dd1, span = curve(combo, 1.0 / k)
    scale = DD_BUDGET / dd1 if dd1 else 1.0
    sleeve = min(MAX_SLEEVE_RISK, (1.0 / k) * scale)
    n, per_mo, win, ret, dd, span = curve(combo, sleeve)
    annual = ((1 + ret / 100) ** (1 / span) - 1) * 100
    print(f"  {'+'.join(combo):<44} {per_mo:>6.1f} {sleeve:>7.2f}% {dd:>6.1f} "
          f"{ret:>+9.1f} {annual:>+6.1f}%", flush=True)
    if best is None or annual > best[0]:
        best = (annual, combo, sleeve, per_mo, dd, ret)

print(f"\n  best risk-adjusted: {'+'.join(best[1])}", flush=True)
print(f"     {best[3]:.1f} trades/month, {best[2]:.2f}% risk per trade per market, "
      f"{best[4]:.1f}% max drawdown, {best[0]:+.1f}%/yr", flush=True)
