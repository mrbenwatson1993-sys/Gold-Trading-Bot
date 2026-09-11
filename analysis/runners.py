"""Does a slower Safety Line actually let the big moves run?"""
import sys
from dataclasses import replace
from tori.backtest import run
from tori.candles import bar_seconds, load_csv, timeframe_name
from tori.config import RiskConfig, simple

RISK = RiskConfig(symbol="MGC", starting_equity=250_000)

for path in sys.argv[1:]:
    candles = load_csv(path)
    bs = bar_seconds(candles)
    base = replace(simple().for_timeframe(bs), always_in=False)
    print(f"\n{timeframe_name(bs)}  {len(candles)} bars")
    print(f"  {'swing':>5} {'n':>5} {'win%':>6} {'expR':>8} {'PF':>6} {'avgW':>7} "
          f"{'RR':>6} {'>=3R':>5} {'>=5R':>5} {'>=10R':>6} {'best':>7} "
          f"{'peak':>7} {'ret%':>7} {'DD%':>6} {'top3':>6}")
    for swing in (2, 3, 5, 8, 12, 16):
        cfg = replace(base, swing_strength=swing)
        r = run(candles, cfg, RISK); s = r.stats
        if not s.get("trades"):
            print(f"  {swing:>5}   no trades"); continue
        ts = r.trades
        rs = sorted(t.r_multiple for t in ts)
        wins = [v for v in rs if v > 0]; losses = [v for v in rs if v <= 0]
        rr = (sum(wins)/len(wins))/abs(sum(losses)/len(losses)) if wins and losses else 0
        peak = sum(t.mfe_r for t in ts)/len(ts)
        tot = sum(rs)
        top3 = sum(rs[-3:])/tot*100 if tot else 0
        print(f"  {swing:>5} {s['trades']:>5} {s['win_rate']:>6.1f} "
              f"{s['expectancy_r']:>+8.3f} {s['profit_factor']:>6.2f} "
              f"{s['avg_win_r']:>+7.2f} {rr:>6.2f} "
              f"{sum(1 for v in rs if v>=3):>5} {sum(1 for v in rs if v>=5):>5} "
              f"{sum(1 for v in rs if v>=10):>6} {rs[-1]:>+7.1f} {peak:>+7.2f} "
              f"{s['return_pct']:>+7.1f} {s['max_drawdown_pct']:>6.1f} {top3:>5.0f}%")
