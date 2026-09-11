"""Human-readable output, meant to be read next to a chart."""

from __future__ import annotations

from datetime import datetime, timezone

from .backtest import BacktestResult
from .candles import Candle, timeframe_name
from .mtf import Apex, TimeframeView
from .strategy import Signal, Trade


def when(ts: int) -> str:
    return f"{datetime.fromtimestamp(ts, tz=timezone.utc):%Y-%m-%d %H:%M}"


def signal_report(sig: Signal) -> str:
    line, brk = sig.brk.line, sig.brk
    out = [
        "=" * 74,
        f"  {sig.grade.letter:>2}   {sig.direction.upper():<5} {when(brk.ts)}",
        "=" * 74,
        f"  ACTION LINE  {line.touch_count}-touch {line.kind} line "
        f"({line.timeframe}), {line.age_bars(brk.index)} bars old",
    ]
    for n, t in enumerate(line.touches, 1):
        out.append(f"     touch {n}    {when(t.ts)}   {t.price:.2f}")
    out += [
        f"  BREAK        closed {brk.close:.2f} through {brk.line_value:.2f}"
        f"  ({brk.displacement_atr:.2f} ATR, body {brk.body_ratio:.0%},"
        f" {'strong' if brk.strong else 'weak'})",
        f"  ENTRY        {sig.entry_price:.2f}",
        f"  RISK         invalidation {sig.initial_stop:.2f}"
        f"  ({sig.risk:.2f} points = 1R)",
        f"  TARGET       none -- price decides. Exit is the Safety Line only.",
        f"  STRUCTURE    {sig.structure.bias}: {sig.structure.note}",
        f"  CLEAN SPACE  {sig.room_r:.1f}R"
        + (f" to {sig.blocker.price:.2f}" if sig.blocker else " (open air)"),
        "",
        sig.grade.table(),
    ]
    return "\n".join(out)


def ladder_report(views: list[TimeframeView], apexes: list[Apex],
                  candle: Candle, bar_seconds: int) -> str:
    out = [
        "=" * 74,
        f"  TOP-DOWN READ    {when(candle.ts)}    close {candle.close:.2f}",
        "=" * 74,
    ]
    for v in views:
        bias = v.structure.bias if v.structure else "?"
        note = v.structure.note if v.structure else ""
        out.append(f"  {v.label:>3}  {bias:<8} {len(v.lines)} live line(s)   {note}")
        for ln in sorted(v.lines, key=lambda x: -x.touch_count):
            arrow = "\\" if ln.slope < 0 else "/"
            price = ln.value_at_ts(candle.ts)
            side = "resistance" if ln.kind == "bearish" else "support"
            dist = (price - candle.close)
            out.append(f"        {arrow} {ln.touch_count}-touch {side:<10} "
                       f"@ {price:>9.2f}  ({dist:+.2f} from price)")

    out.append("")
    if apexes:
        out.append(f"  COILS / TRIANGLES ({len(apexes)} converging pair(s)):")
        for a in apexes[:5]:
            out.append(f"     {a.describe(bar_seconds)}")
        out.append("     -> wait. Break of either line is the Action Line;")
        out.append("        the other one is already drawn as the Safety Line.")
    else:
        out.append("  COILS / TRIANGLES: none -- no converging pair with price inside")
    out.append("=" * 74)
    return "\n".join(out)


def trade_line(t: Trade) -> str:
    return (f"  {t.signal.grade.letter:>2} {t.direction:<5} "
            f"{when(t.entry_ts)} {when(t.exit_ts)} "
            f"{t.contracts:>3}x "
            f"{t.entry_price:>9.2f} {t.exit_price:>9.2f} "
            f"{t.r_multiple:>6.2f}R {t.net:>9,.0f} "
            f"{t.bars_held:>4}b  {t.exit_reason}")


def backtest_report(result: BacktestResult, show_trades: bool = True) -> str:
    s = result.stats
    c, r, cfg = result.contract, result.risk, result.cfg
    tf = timeframe_name(cfg.bar_seconds) if cfg else "?"
    out = [
        "=" * 100,
        f"TORI TRENDLINE BACKTEST -- {c.symbol} ({c.name}) on {tf}",
        f"{when(result.start_ts)} .. {when(result.end_ts)}   {result.bars} bars",
        f"risk {r.risk_pct:.2f}%/trade | ${c.point_value:,.0f} per point | "
        f"{r.slippage_ticks} tick slip + ${c.commission}/side | "
        f"min grade {cfg.min_grade} | no profit target",
        "=" * 100,
    ]
    if not s.get("trades"):
        out.append("  no trades taken")
        if result.skipped:
            out.append(f"  skipped: {dict(result.skipped)}")
        out.append("=" * 100)
        return "\n".join(out)

    if show_trades:
        out.append(f"  {'gr':>2} {'dir':<5} {'entry':<16} {'exit':<16} "
                   f"{'size':>4} {'in':>9} {'out':>9} {'R':>6} {'net $':>9} "
                   f"{'held':>5}  reason")
        out += [trade_line(t) for t in result.trades]
        out.append("")

    pf = s["profit_factor"]
    pf_txt = "inf" if pf == float("inf") else f"{pf:.2f}"
    out += [
        "-" * 100,
        f"  trades {s['trades']:<4} wins {s['wins']:<4} losses {s['losses']:<4} "
        f"win rate {s['win_rate']:.1f}%",
        f"  expectancy {s['expectancy_r']:+.3f}R   total {s['total_r']:+.1f}R   "
        f"profit factor {pf_txt}",
        f"  avg win {s['avg_win_r']:+.2f}R   avg loss {s['avg_loss_r']:+.2f}R   "
        f"best {s['best_r']:+.2f}R   worst {s['worst_r']:+.2f}R",
        f"  equity ${s['starting_equity']:,.0f} -> ${s['ending_equity']:,.0f} "
        f"({s['return_pct']:+.1f}%)   max DD ${s['max_drawdown']:,.0f} "
        f"({s['max_drawdown_pct']:.1f}%)",
        f"  costs ${s['total_costs']:,.0f}   avg hold {s['avg_bars_held']:.0f} bars",
        "  exits: " + ", ".join(f"{k} x{v}" for k, v in s["exit_reasons"].items()),
        "-" * 100,
        "  by grade:",
    ]
    for letter in ("A+", "A", "B", "C"):
        g = s["by_grade"].get(letter)
        if g:
            out.append(f"    {letter:>2}  n={g['n']:<4} win {g['wins']/g['n']*100:>5.1f}%  "
                       f"total {g['r']:+7.1f}R  avg {g['r']/g['n']:+.3f}R  "
                       f"net ${g['net']:>9,.0f}")
    out.append("  by direction:")
    for d, v in s["by_direction"].items():
        out.append(f"    {d:<6} n={v['n']:<4} win {v['wins']/v['n']*100:>5.1f}%  "
                   f"total {v['r']:+7.1f}R  avg {v['r']/v['n']:+.3f}R")
    if result.skipped:
        out.append(f"  skipped: {dict(result.skipped)}")
    out.append("=" * 100)
    return "\n".join(out)
