"""Does it work on 5, 3 and 1 minute charts?

Two tables, because the honest answer depends on comparing like with like.

The fast series are short -- 200,000 bars is 2.8 years at 5 minutes but only
207 days at 1 minute -- so a 1m run covers a different (and much smaller)
slice of history than a 1h run. Comparing them directly would say more about
2023 than about the timeframe. So each fast chart is measured against the
slower ones over its OWN window.

Note also that on a 207-day series the weekly and monthly rungs cannot be
built at all (30 and 7 bars), so a 1m test is really a daily-lines test.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name, validate
from tori.config import RiskConfig, recommended

SETS = [("GOLD", "MGC", {"1h": "data/gold_1h_deep.csv",
                         "15m": "data/gold_15m_deep.csv",
                         "5m": "data/gold_5m.csv",
                         "3m": "data/gold_3m.csv",
                         "1m": "data/gold_1m.csv"}),
        ("GBPUSD", "M6B", {"1h": "data/gbpusd_1h.csv",
                           "15m": "data/gbpusd_15m.csv",
                           "5m": "data/gbpusd_5m.csv",
                           "3m": "data/gbpusd_3m.csv",
                           "1m": "data/gbpusd_1m.csv"})]
ORDER = ["1h", "15m", "5m", "3m", "1m"]


def measure(cs, sym, start=None):
    seg = [c for c in cs if start is None or c.ts >= start]
    if len(seg) < 2000:
        return None
    bs = bar_seconds(seg)
    cfg = replace(recommended().for_timeframe(bs))
    risk = RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0)
    r = run(seg, cfg, risk)
    s = r.stats
    if not s.get("trades"):
        return None
    free = run(seg, cfg, replace(risk, slippage_ticks=0.0)).stats
    years = (seg[-1].ts - seg[0].ts) / (365.25 * 86400)
    rs = [t.r_multiple for t in r.trades]
    rr = abs(s["avg_win_r"] / s["avg_loss_r"]) if s["avg_loss_r"] else 0
    return dict(n=s["trades"], per_yr=s["trades"] / years, years=years,
                win=s["win_rate"], rr=rr, best=max(rs),
                exp=s["expectancy_r"], pf=s["profit_factor"],
                ret=s["return_pct"], dd=s["max_drawdown_pct"],
                pf_free=free["profit_factor"])


for name, sym, files in SETS:
    loaded = {}
    for tf in ORDER:
        cs, _ = validate(load_csv(files[tf]))
        loaded[tf] = cs

    print(f"\n{'='*104}\n{name} -- each entry chart over its own full window\n{'='*104}")
    print(f"  {'entry':<5} {'window':>8} {'n':>6} {'/yr':>6} {'/mo':>6} {'win%':>6} "
          f"{'RR':>5} {'best':>7} {'expR':>8} {'PF':>5} {'PF free':>8} "
          f"{'ret%':>8} {'DD%':>6}", flush=True)
    for tf in ORDER:
        m = measure(loaded[tf], sym)
        if not m:
            print(f"  {tf:<5}  -- no trades", flush=True); continue
        print(f"  {tf:<5} {m['years']:>7.1f}y {m['n']:>6} {m['per_yr']:>6.1f} "
              f"{m['per_yr']/12:>6.1f} {m['win']:>6.1f} {m['rr']:>5.2f} "
              f"{m['best']:>+7.1f} {m['exp']:>+8.3f} {m['pf']:>5.2f} "
              f"{m['pf_free']:>8.2f} {m['ret']:>+8.1f} {m['dd']:>6.1f}", flush=True)

    for window_tf in ("5m", "1m"):
        start = loaded[window_tf][0].ts
        span = (loaded[window_tf][-1].ts - start) / 86400
        print(f"\n  -- all charts over the {window_tf} window "
              f"({span:.0f} days from {loaded[window_tf][0].dt:%Y-%m-%d})",
              flush=True)
        print(f"  {'entry':<5} {'n':>6} {'/mo':>6} {'win%':>6} {'RR':>5} "
              f"{'expR':>8} {'PF':>5} {'PF free':>8} {'ret%':>8} {'DD%':>6}",
              flush=True)
        for tf in ORDER:
            m = measure(loaded[tf], sym, start)
            if not m:
                print(f"  {tf:<5}  -- too few trades", flush=True); continue
            print(f"  {tf:<5} {m['n']:>6} {m['per_yr']/12:>6.1f} {m['win']:>6.1f} "
                  f"{m['rr']:>5.2f} {m['exp']:>+8.3f} {m['pf']:>5.2f} "
                  f"{m['pf_free']:>8.2f} {m['ret']:>+8.1f} {m['dd']:>6.1f}",
                  flush=True)
