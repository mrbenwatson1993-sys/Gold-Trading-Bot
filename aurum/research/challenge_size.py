"""What actually happens at a $7,000 or $10,000 challenge, honestly sized.

Earlier work showed the 1 oz minimum forces you to skip signals whose stop
exceeds your risk budget. This re-runs the whole out-of-sample trade log with
that constraint actually applied - not just reporting what fraction would be
skipped, but rebuilding the trade sequence as if you had genuinely skipped
them - then measures expectancy, drawdown, and prop-style survival on what's
left.
"""
import pickle
import numpy as np, pandas as pd
from pathlib import Path
import sys
sys.path.insert(0, ".")
from aurum.engine.metrics import summarise, bootstrap_pvalue
from aurum.research import propfirm as pf
from aurum.data.dukascopy import load_minutes

pd.set_option("display.width", 220)

logs = pickle.load(open("/tmp/claude-0/-home-user-Gold-Trading-Bot/dee0a71a-10a1-5032-bda3-cf3142202824/scratchpad/logs.pkl","rb"))
t_full = logs["flat_by_friday"].sort_values("exit_ts").reset_index(drop=True)

def rebuild(t, acct_usd, risk_pct, oz_min=1.0):
    """Rebuild the trade log as if every trade is sized at max(oz_min, budget/stop),
    but a trade is SKIPPED (not taken) when oz_min alone already blows the budget
    past a tolerance -- mirrors what a disciplined trader actually does: skip
    trades they can't size properly rather than knowingly over-risk."""
    budget = acct_usd * risk_pct / 100.0
    stop = t["risk_px"].to_numpy()
    takeable = stop * oz_min <= budget * 1.5   # allow up to 1.5x intended risk before skipping
    sub = t[takeable].copy()
    # dollars actually risked per trade at 1 oz (may exceed budget slightly)
    sub["usd_r"] = sub["r"].to_numpy() * sub["risk_px"].to_numpy() * oz_min
    return sub, takeable.mean()

GBP = 1.27
print("=== $7,000 vs $10,000, honestly sized at 1 oz minimum ===\n")

rows = []
eqs = {}
for acct_usd in (7000, 10000):
    for rp in (0.15, 0.25, 0.35):
        sub, frac = rebuild(t_full, acct_usd, rp)
        if len(sub) < 100:
            continue
        eq = np.cumsum(sub["usd_r"].to_numpy())
        peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
        dd = (peak - eq).max()
        s = summarise(sub.rename(columns={"r": "r_orig"}).assign(r=sub["r"]))
        rows.append(dict(
            account=f"${acct_usd:,}", risk=f"{rp:.2f}%",
            takeable=f"{frac*100:.0f}%", n=len(sub),
            E_R=round(s["expectancy_r"], 4),
            tr_day=round(s["trades_per_available_day"], 2),
            total_usd=round(eq[-1], 0), total_pct=round(eq[-1]/acct_usd*100, 0),
            maxDD_usd=round(dd, 0), maxDD_pct=round(dd/acct_usd*100, 1),
        ))
        eqs[(acct_usd, rp)] = (sub, eq)

out = pd.DataFrame(rows)
print(out.to_string(index=False))

print("\n=== Floating-equity survival, 0.25% risk (the workable setting) ===")
minutes = load_minutes(Path("data/bars"))
m2 = minutes[minutes.index >= pf.OOS_START]
for acct_usd in (7000, 10000):
    sub, frac = rebuild(t_full, acct_usd, 0.25)
    sub = sub.assign(swap_r=0.0)  # already swap-adjusted in source log
    # floating_equity expects risk_pct as %, and computes float in units of risk_pct*r
    # we instead need $ equity: build directly from usd_r per-minute path
    ts = m2["ts"].to_numpy(np.int64); mid = m2["close"].to_numpy(np.float64)
    float_usd = np.zeros(len(ts)); real_usd = np.zeros(len(ts))
    for _, row in sub.iterrows():
        i = int(np.searchsorted(ts, row["entry_ts"], "left"))
        j = int(np.searchsorted(ts, row["exit_ts"], "left"))
        if j <= i: j = min(i+1, len(ts)-1)
        seg = (mid[i:j] - row["entry_px"]) * row["side"]  # $/oz move, 1 oz -> $ directly
        float_usd[i:j] += seg
        if j < len(real_usd): real_usd[j:] += row["r"] * row["risk_px"]
    eq_pct = (real_usd + float_usd) / acct_usd * 100
    eq = pd.Series(eq_pct, index=m2.index)
    for rules in pf.RULESETS:
        acc = pf.rolling_accounts(eq, rules)
        vc = acc["outcome"].value_counts(normalize=True)
        print(f"  ${acct_usd:,}  {rules.name:42s}  passed={vc.get('passed',0)*100:5.1f}%  "
              f"fail_dd={vc.get('failed_maxdd',0)*100:5.1f}%  fail_daily={vc.get('failed_daily',0)*100:5.1f}%")
