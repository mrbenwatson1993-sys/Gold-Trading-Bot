"""More markets instead of a faster chart.

Trade count is the binding constraint: 4-7 a month on multi-day holds forces
the risk per trade up to make the effort worthwhile, which is the wrong
direction. More sleeves at smaller size fixes that without touching the
timeframe -- and the era-diversification already paid when the portfolio went
from one market to three.

Step one prints every market on both 1H and 4H so the choice of entry chart is
visible rather than buried. Step two builds portfolios from the survivors.
"""
import itertools
import statistics
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, recommended

MARKETS = [
    ("GOLD", "MGC", "data/gold_4h_16y.csv", "data/gold_1h_deep.csv"),
    ("SILVER", "SIL", "data/silver_4h.csv", "data/silver_1h.csv"),
    ("S&P", "MES", "data/spx500_4h.csv", "data/spx500_1h.csv"),
    ("NASDAQ", "MNQ", "data/nas100_4h.csv", "data/nas100_1h.csv"),
    ("BRENT", "MCL", "data/brent_4h.csv", "data/brent_1h.csv"),
    ("EURUSD", "M6E", "data/eurusd_4h.csv", "data/eurusd_1h.csv"),
    ("GBPUSD", "M6B", "data/gbpusd_4h.csv", "data/gbpusd_1h.csv"),
    ("USDJPY", "M6J", "data/usdjpy_4h.csv", "data/usdjpy_1h.csv"),
    ("AUDUSD", "M6A", "data/audusd_4h.csv", "data/audusd_1h.csv"),
]
EQUITY = 250_000.0


def measure(path, sym):
    cs, _ = validate(load_csv(path))
    cfg = replace(recommended().for_timeframe(bar_seconds(cs)))
    r = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=EQUITY,
                                risk_pct=1.0, compound=False))
    s = r.stats
    if not s.get("trades"):
        return None, []
    years = (cs[-1].ts - cs[0].ts) / (365.25 * 86400)
    return (s["profit_factor"], s["trades"] / years / 12), \
        [(t.exit_ts, t.r_multiple) for t in r.trades]


print(f"  {'market':<7} {'4h PF':>6} {'4h /mo':>7} | {'1h PF':>6} {'1h /mo':>7} "
      f"| {'pick':>5}", flush=True)
STREAMS, PICKED = {}, {}
for name, sym, p4, p1 in MARKETS:
    (pf4, mo4), t4 = measure(p4, sym)
    (pf1, mo1), t1 = measure(p1, sym)
    # take 1H only where it is not materially worse; the S&P collapse on 1H
    # (0.73 against 1.37) is the case this guards against
    use_1h = pf1 >= pf4 - 0.05
    STREAMS[name] = t1 if use_1h else t4
    PICKED[name] = ("1h" if use_1h else "4h", pf1 if use_1h else pf4,
                    mo1 if use_1h else mo4)
    print(f"  {name:<7} {pf4:>6.2f} {mo4:>7.1f} | {pf1:>6.2f} {mo1:>7.1f} "
          f"| {PICKED[name][0]:>5}", flush=True)

survivors = [n for n in PICKED if PICKED[n][1] > 1.0]
print(f"\n  markets with PF > 1.0 on their chosen chart: "
      f"{', '.join(survivors)}\n", flush=True)


def evaluate(names):
    stream = sorted(itertools.chain.from_iterable(STREAMS[n] for n in names))
    if not stream:
        return None
    per = EQUITY * (1.0 / len(names)) / 100.0     # total 1% risk per trade
    eq, peak, dd, wins = EQUITY, EQUITY, 0.0, 0
    span = (stream[-1][0] - stream[0][0]) / (365.25 * 86400)
    for _, r in stream:
        eq += r * per
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak * 100)
        wins += 1 if r > 0 else 0
    ret = (eq - EQUITY) / EQUITY * 100
    return (len(stream), len(stream) / span / 12, wins / len(stream) * 100,
            ret, dd, ret / dd if dd else 0)


print(f"  {'portfolio':<44} {'n':>5} {'/mo':>6} {'win%':>6} {'ret%':>8} "
      f"{'DD%':>6} {'ret/DD':>7}", flush=True)
order = sorted(survivors, key=lambda n: -PICKED[n][1])
for k in range(1, len(order) + 1):
    combo = order[:k]
    res = evaluate(combo)
    if res:
        n, mo, win, ret, dd, rdd = res
        print(f"  {'+'.join(combo):<44} {n:>5} {mo:>6.1f} {win:>6.1f} "
              f"{ret:>+8.1f} {dd:>6.1f} {rdd:>7.2f}", flush=True)


# --- the unfitted version -------------------------------------------------
# Choosing each market's entry chart by whichever scored better is a selection
# across eighteen cells, and USDJPY flipping from 0.77 on 4H to 1.24 on 1H is
# exactly what chance produces there. So rebuild the same portfolios with
# every market forced onto the 4-hour -- no per-market choice at all -- and
# see how much of the result survives.
print("\n\n  SAME PORTFOLIOS, EVERY MARKET FORCED ONTO 4H (no per-market choice)\n",
      flush=True)
FIXED = {}
for name, sym, p4, _p1 in MARKETS:
    (pf, mo), tr = measure(p4, sym)
    FIXED[name] = (pf, tr)

order4 = [n for n, (pf, _) in sorted(FIXED.items(), key=lambda kv: -kv[1][0])
          if pf > 1.0]
print(f"  markets with PF > 1.0 on 4H: {', '.join(order4)}\n", flush=True)
STREAMS = {n: FIXED[n][1] for n in FIXED}
print(f"  {'portfolio':<44} {'n':>5} {'/mo':>6} {'win%':>6} {'ret%':>8} "
      f"{'DD%':>6} {'ret/DD':>7}", flush=True)
for k in range(1, len(order4) + 1):
    res = evaluate(order4[:k])
    if res:
        n, mo, win, ret, dd, rdd = res
        print(f"  {'+'.join(order4[:k]):<44} {n:>5} {mo:>6.1f} {win:>6.1f} "
              f"{ret:>+8.1f} {dd:>6.1f} {rdd:>7.2f}", flush=True)
