"""Does this bot survive the rules prop firms attach beyond the drawdown limit?

Two that were never modelled and can disqualify a strategy outright:
  consistency  - no single day may be more than X% of total profit
  best trade   - same idea applied per trade
Both punish exactly the shape of a trend-follower's return distribution.
"""
import pickle
import numpy as np, pandas as pd
pd.set_option("display.width", 220)

logs = pickle.load(open("/tmp/claude-0/-home-user-Gold-Trading-Bot/dee0a71a-10a1-5032-bda3-cf3142202824/scratchpad/logs.pkl","rb"))
t = logs["flat_by_friday"].sort_values("exit_ts").reset_index(drop=True)
GBP = 1.27

# --- 1. account size vs. how much of the strategy you can actually run -------
stop = t.risk_px.to_numpy()
print("=== SIGNALS YOU CAN TAKE, BY CHALLENGE SIZE (1 oz minimum) ===")
rows = []
for usd in (5000, 10000, 25000, 50000, 100000):
    row = {"account": f"${usd:,}"}
    for rp in (0.15, 0.25):
        row[f"takeable@{rp:.2f}%"] = f"{(stop <= usd*rp/100).mean()*100:.0f}%"
    row["budget@0.15%"] = f"${usd*0.0015:.2f}"
    rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))

# --- 2. consistency rules ---------------------------------------------------
print("\n=== CONSISTENCY: how concentrated is the profit? ===")
# simulate a challenge run: trades until cumulative R reaches the 10% target
# at 0.15% risk, 10% target = 66.7 R
target_r = 10.0 / 0.15
r = t.r.to_numpy()
day = t.exit_dt.dt.normalize().to_numpy()
cum = np.cumsum(r)
starts = np.arange(0, len(r) - 400, 20)
best_day_share, best_trade_share = [], []
for s in starts:
    c = np.cumsum(r[s:])
    hit = np.argmax(c >= target_r) if (c >= target_r).any() else -1
    if hit < 0:
        continue
    seg_r, seg_day = r[s:s+hit+1], day[s:s+hit+1]
    tot = seg_r.sum()
    if tot <= 0:
        continue
    by_day = pd.Series(seg_r).groupby(pd.Series(seg_day)).sum()
    best_day_share.append(by_day.max() / tot * 100)
    best_trade_share.append(seg_r.max() / tot * 100)

bd, bt = np.array(best_day_share), np.array(best_trade_share)
print(f"{len(bd)} simulated challenge runs to a 10% target at 0.15% risk")
print(f"  best DAY as share of the run's profit:   median {np.median(bd):.0f}%   "
      f"90th pct {np.percentile(bd,90):.0f}%   max {bd.max():.0f}%")
print(f"  best TRADE as share of the run's profit: median {np.median(bt):.0f}%   "
      f"90th pct {np.percentile(bt,90):.0f}%   max {bt.max():.0f}%")
for lim in (20, 25, 30, 40, 50):
    print(f"  would FAIL a '{lim}% max single day' consistency rule: "
          f"{(bd > lim).mean()*100:.0f}% of runs")
