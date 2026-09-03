"""Smallest account that can trade Aurum Edge V6 as validated.

Below a certain balance the 0.01-lot minimum stops being a rounding detail and
becomes the position sizer: you cannot scale down, so every trade is 1 oz and
your risk per trade floats with the ATR instead of being held constant. This
measures where that stops mattering.
"""
import pickle
import numpy as np, pandas as pd
pd.set_option("display.width", 240)

logs = pickle.load(open("/tmp/claude-0/-home-user-Gold-Trading-Bot/dee0a71a-10a1-5032-bda3-cf3142202824/scratchpad/logs.pkl","rb"))
t = logs["flat_by_friday"].sort_values("exit_ts").reset_index(drop=True)
r, stop = t.r.to_numpy(), t.risk_px.to_numpy()
GBP = 1.27

print(f"n={len(t)}  total={r.sum():.1f}R   stop $/oz: "
      f"p25={np.percentile(stop,25):.2f} med={np.median(stop):.2f} "
      f"p75={np.percentile(stop,75):.2f} p95={np.percentile(stop,95):.2f}")

# --- A. forced 1 oz on every trade: risk per trade floats with the stop -------
print("\n=== A. FIXED 1 oz (the only option on a small account) ===")
usd_pnl = r * stop                       # dollars per trade at exactly 1 oz
eq = np.cumsum(usd_pnl)
peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
dd_usd = (peak - eq).max()
rows = []
for gbp_acct in (500, 1000, 2000, 3000, 5000, 8000, 12000):
    a = gbp_acct * GBP
    rows.append(dict(account_GBP=gbp_acct,
                     risk_median_trade=f"{np.median(stop)/a*100:.2f}%",
                     risk_p95_trade=f"{np.percentile(stop,95)/a*100:.2f}%",
                     risk_5_open=f"{5*np.median(stop)/a*100:.1f}%",
                     closed_maxDD=f"{dd_usd/a*100:.1f}%",
                     total_return=f"{eq[-1]/a*100:.0f}%"))
print(pd.DataFrame(rows).to_string(index=False))

# --- B. proper sizing: what fraction of signals fit inside the risk budget ----
print("\n=== B. PROPER SIZING — share of signals you can actually take at 1 oz ===")
rows = []
for gbp_acct in (2000, 3000, 4000, 5000, 6000, 8000, 10000, 14000):
    a = gbp_acct * GBP
    row = dict(account_GBP=gbp_acct)
    for rp in (0.15, 0.25, 0.50):
        budget = a * rp / 100
        row[f"takeable@{rp:.2f}%"] = f"{(stop <= budget).mean()*100:.0f}%"
    row["budget@0.25%"] = f"${a*0.0025:.2f}"
    rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))
print("\n(a signal is untakeable when 1 oz x its stop already exceeds the risk budget,")
print(" so you must skip it or knowingly oversize)")
