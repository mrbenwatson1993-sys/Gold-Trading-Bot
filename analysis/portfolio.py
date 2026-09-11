"""Trading several markets at once with one parameter set.

No single market holds its edge across all three eras -- but they fail at
different times. Gold's strongest period is the S&P's worst and the other way
round. A portfolio is the only honest way to use a set of edges that are each
real-but-intermittent, and it is what the per-market tables cannot show.

Risk is fixed-fractional and NOT compounded, so each trade risks the same
dollar amount regardless of what the others are doing. That keeps the sleeves
independent and stops one market's run flattering the rest.
"""
import itertools
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, simple

# Each market on the fastest entry chart it tolerates. Gold and GBPUSD are
# indistinguishable on 1H and 4H over the same period but trade twice as
# often on 1H; the S&P collapses on 1H (PF 0.73 against 1.37) over an
# identical window, so it stays on 4H. That is a judgement from the data, not
# a tuned parameter -- the S&P failure is dramatic, not marginal.
MARKETS = [("GOLD", "data/gold_1h_deep.csv", "MGC"),
           ("S&P", "data/spx500_4h.csv", "MES"),
           ("GBPUSD", "data/gbpusd_1h.csv", "M6B"),
           ("EURUSD", "data/eurusd_4h.csv", "M6E"),
           ("SILVER", "data/silver_4h.csv", "SIL")]
EQUITY = 250_000.0


def trades_for(path, sym):
    cs, _ = validate(load_csv(path))
    cfg = replace(simple().for_timeframe(bar_seconds(cs)), always_in=True,
                  htf_align="none", exit_on_stop_only=True,
                  stop_follows_safety=True, safety_line_redraw=False,
                  stop_on_close_only=False, stop_close_confirm_in_profit=True,
                  swing_strength=3, safety_swing_strength=12,
                  line_timeframes=("1d", "1w", "1M"), min_touches=3,
                  max_touches=99, trail_buffer_atr=0.25, auto_gap_stop_pct=99.0)
    r = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=EQUITY,
                                risk_pct=1.0, compound=False))
    return [(t.exit_ts, t.r_multiple) for t in r.trades]


ALL = {}
for name, path, sym in MARKETS:
    ALL[name] = trades_for(path, sym)
    print(f"  loaded {name}: {len(ALL[name])} trades", flush=True)


def evaluate(names, risk_pct):
    """Equity curve from combining these markets, each risking risk_pct."""
    stream = sorted(itertools.chain.from_iterable(ALL[n] for n in names))
    per_trade = EQUITY * risk_pct / 100.0
    eq, peak, maxdd = EQUITY, EQUITY, 0.0
    wins = 0
    for _, r in stream:
        eq += r * per_trade
        peak = max(peak, eq)
        maxdd = max(maxdd, (peak - eq) / peak * 100)
        wins += 1 if r > 0 else 0
    if not stream:
        return None
    ret = (eq - EQUITY) / EQUITY * 100
    return len(stream), wins / len(stream) * 100, ret, maxdd, ret / maxdd if maxdd else 0


print(f"\n  {'portfolio':<34} {'n':>5} {'win%':>6} {'ret%':>8} {'DD%':>6} "
      f"{'ret/DD':>7}", flush=True)
names = [m[0] for m in MARKETS]
combos = ([(n,) for n in names]
          + [("GOLD", "S&P"), ("GOLD", "S&P", "GBPUSD"),
             ("GOLD", "S&P", "GBPUSD", "EURUSD"), tuple(names)])
for combo in combos:
    # keep total risk near 1% of equity per trade across the portfolio
    res = evaluate(list(combo), 1.0 / len(combo))
    if res:
        n, win, ret, dd, rdd = res
        print(f"  {'+'.join(combo):<34} {n:>5} {win:>6.1f} {ret:>+8.1f} "
              f"{dd:>6.1f} {rdd:>7.2f}", flush=True)


# --- does the portfolio hold up era by era? ------------------------------
from datetime import datetime, timezone

ERAS = [("2007-2011", "2007-01-01", "2011-12-31"),
        ("2012-2016", "2012-01-01", "2016-12-31"),
        ("2017-2023", "2017-01-01", "2023-12-31")]
PICK = ["GOLD", "S&P", "GBPUSD"]

print(f"\n  GOLD+S&P+GBPUSD, by era (each sleeve risking "
      f"{1.0/len(PICK):.2f}% per trade)\n", flush=True)
print(f"  {'era':<11} {'n':>5} {'win%':>6} {'ret%':>8} {'DD%':>6} {'ret/DD':>7}",
      flush=True)
for era, a, b in ERAS:
    lo = datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp()
    hi = datetime.fromisoformat(b).replace(tzinfo=timezone.utc).timestamp()
    stream = sorted((ts, r) for n in PICK for ts, r in ALL[n] if lo <= ts <= hi)
    if not stream:
        print(f"  {era:<11}  -- none", flush=True); continue
    per = EQUITY * (1.0 / len(PICK)) / 100.0
    eq, peak, dd = EQUITY, EQUITY, 0.0
    wins = 0
    for _, r in stream:
        eq += r * per
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak * 100)
        wins += 1 if r > 0 else 0
    ret = (eq - EQUITY) / EQUITY * 100
    print(f"  {era:<11} {len(stream):>5} {wins/len(stream)*100:>6.1f} "
          f"{ret:>+8.1f} {dd:>6.1f} {ret/dd if dd else 0:>7.2f}", flush=True)
