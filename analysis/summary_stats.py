"""Per-market trade statistics for the recommended configuration.

Everything a decision needs in one table: how often it trades, how long it
holds, the reward-to-risk it actually achieved, and how big the best trades
were -- which is the number that matters most in a system with no target.
"""
from dataclasses import replace

from tori.backtest import run
from tori.candles import bar_seconds, load_csv, validate
from tori.config import RiskConfig, recommended

MARKETS = [("GOLD", "data/gold_4h_16y.csv", "MGC", "futures"),
           ("SILVER", "data/silver_4h.csv", "SIL", "futures"),
           ("S&P", "data/spx500_4h.csv", "MES", "futures"),
           ("NASDAQ", "data/nas100_4h.csv", "MNQ", "futures"),
           ("BRENT", "data/brent_4h.csv", "MCL", "futures"),
           ("EURUSD", "data/eurusd_4h.csv", "M6E", "forex"),
           ("GBPUSD", "data/gbpusd_4h.csv", "M6B", "forex"),
           ("USDJPY", "data/usdjpy_4h.csv", "M6J", "forex"),
           ("AUDUSD", "data/audusd_4h.csv", "M6A", "forex")]

print(f"  {'market':<7} {'class':<8} {'yrs':>4} {'n':>5} {'/yr':>5} {'/mo':>5} "
      f"{'win%':>6} {'avgW':>6} {'avgL':>6} {'RR':>5} {'best':>7} "
      f"{'>3R':>5} {'>5R':>5} {'>10R':>5} {'hold':>6} {'PF':>5}", flush=True)
groups = {"futures": [], "forex": []}
for name, path, sym, cls in MARKETS:
    cs, _ = validate(load_csv(path))
    bs = bar_seconds(cs)
    cfg = replace(recommended().for_timeframe(bs))
    r = run(cs, cfg, RiskConfig(symbol=sym, starting_equity=250_000, risk_pct=1.0))
    s = r.stats
    if not s.get("trades"):
        print(f"  {name:<7} {cls:<8}  -- no trades", flush=True); continue
    ts = r.trades
    rs = [t.r_multiple for t in ts]
    n = len(ts)
    years = (cs[-1].ts - cs[0].ts) / (365.25 * 86400)
    hold_days = sum(t.exit_index - t.entry_index for t in ts) / n * bs / 86400
    rr = abs(s["avg_win_r"] / s["avg_loss_r"]) if s["avg_loss_r"] else 0
    pc = lambda x: f"{sum(1 for v in rs if v >= x)/n*100:>4.1f}%"
    print(f"  {name:<7} {cls:<8} {years:>4.1f} {n:>5} {n/years:>5.1f} "
          f"{n/years/12:>5.1f} {s['win_rate']:>6.1f} {s['avg_win_r']:>+6.2f} "
          f"{s['avg_loss_r']:>+6.2f} {rr:>5.2f} {max(rs):>+7.1f} "
          f"{pc(3)} {pc(5)} {pc(10)} {hold_days:>5.1f}d {s['profit_factor']:>5.2f}",
          flush=True)
    groups[cls].append((s["profit_factor"], s["return_pct"], rr, max(rs), n / years))

print(flush=True)
for cls, rows in groups.items():
    if not rows:
        continue
    n = len(rows)
    print(f"  {cls.upper():<8} mean PF {sum(r[0] for r in rows)/n:.2f}   "
          f"mean return {sum(r[1] for r in rows)/n:+.1f}%   "
          f"mean RR {sum(r[2] for r in rows)/n:.2f}   "
          f"best trade {max(r[3] for r in rows):+.1f}R   "
          f"profitable {sum(1 for r in rows if r[0] > 1.0)}/{n}", flush=True)
