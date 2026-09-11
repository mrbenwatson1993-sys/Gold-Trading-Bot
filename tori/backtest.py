"""Event-driven backtest.

Deliberately pessimistic where it is uncertain:

  * entries fill at the next bar's open, never at the signal bar's close;
  * when a bar touches the resting stop, that bar is assumed to have stopped
    out, even if it also closed well beyond -- a single bar's internal order is
    unknowable;
  * a gap through the stop fills at the open, not at the stop price;
  * commission and slippage are charged on every contract, both ways.

The result is a floor rather than a best case, which is the only useful
direction for the error to run.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .candles import Candle, atr_series, bar_seconds
from .config import RiskConfig, StrategyConfig
from .contracts import Contract, get_contract
from .strategy import Position, Signal, ToriStrategy, Trade


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    contract: Contract | None = None
    cfg: StrategyConfig | None = None
    risk: RiskConfig | None = None
    bars: int = 0
    start_ts: int = 0
    end_ts: int = 0

    @property
    def stats(self) -> dict:
        return compute_stats(self)


def run(candles: list[Candle], cfg: StrategyConfig | None = None,
        risk: RiskConfig | None = None) -> BacktestResult:
    cfg = cfg or StrategyConfig()
    risk = risk or RiskConfig()
    bs = bar_seconds(candles)
    if bs and cfg.bar_seconds != bs:
        cfg = cfg.for_timeframe(bs)

    contract = get_contract(risk.symbol)
    atr = atr_series(candles, cfg.atr_period)
    alignment = None
    if cfg.htf_align != "none":
        from .htf import build_alignment
        alignment = build_alignment(candles, cfg.bar_seconds,
                                    tuple(cfg.htf_timeframes),
                                    cfg.swing_strength)
    strat = ToriStrategy(candles, atr, cfg, alignment)

    result = BacktestResult(contract=contract, cfg=cfg, risk=risk,
                            bars=len(candles),
                            start_ts=candles[0].ts if candles else 0,
                            end_ts=candles[-1].ts if candles else 0)

    equity = risk.starting_equity
    position: Position | None = None
    pending: Signal | None = None
    pending_contracts = 0

    # Nothing can be drawn until there is enough history for a line that
    # satisfies the age rule, so skip the warm-up entirely.
    warmup = max(cfg.atr_period + cfg.swing_strength * 2, cfg.min_age_bars) + 5

    for i in range(warmup, len(candles)):
        # 1. fill any entry that was signalled on the previous bar
        if pending is not None and pending.entry_index == i:
            position = strat.open_position(pending, pending_contracts)
            pending = None

        # 2. manage what is open
        if position is not None:
            outcome = strat.check_exit(position, i)
            strat.observe(i)
            if outcome is not None:
                price, reason = outcome
                trade = _close(position, i, candles[i], price, reason,
                               contract, risk, equity)
                equity = trade.equity_after
                result.trades.append(trade)
                result.equity_curve.append((candles[i].ts, equity))

                # Always-in: the line that just stopped us out is the line we
                # now trade from the other side. Flip rather than go flat.
                if cfg.always_in:
                    flip = strat.reversal(position, i, reason)
                    position = None
                    if flip is not None:
                        size = _size(flip, contract, risk, equity, result)
                        if size >= 1:
                            pending, pending_contracts = flip, size
                    continue
                position = None
            else:
                continue   # one position at a time

        # 3. hunt for the next break
        if position is None and pending is None:
            signal = strat.find_signal(i)
            if signal is None:
                continue
            if signal.is_long and not risk.allow_longs:
                result.skipped["longs disabled"] += 1
                continue
            if not signal.is_long and not risk.allow_shorts:
                result.skipped["shorts disabled"] += 1
                continue
            size = _size(signal, contract, risk, equity, result)
            if size < 1:
                continue
            pending, pending_contracts = signal, size

    # Close anything still open at the final bar, marked to market.
    if position is not None:
        last = len(candles) - 1
        trade = _close(position, last, candles[last], candles[last].close,
                       "open at end", contract, risk, equity)
        equity = trade.equity_after
        result.trades.append(trade)
        result.equity_curve.append((candles[last].ts, equity))

    return result


def _size(signal: Signal, contract: Contract, risk: RiskConfig,
          equity: float, result: BacktestResult) -> int:
    """Whole contracts for this trade, or 0 meaning skip.

    Skipping is the correct answer when the stop is too wide for the account:
    taking it anyway would silently break the risk model, and in a backtest
    that shows up as a flattering result rather than as an error.
    """
    size = min(contract.contracts_for_risk(risk.risk_dollars(equity), signal.risk),
               risk.max_contracts)
    if size < 1:
        result.skipped["stop too wide to size"] += 1
        return 0
    return size


def _close(pos: Position, i: int, candle: Candle, price: float, reason: str,
           contract: Contract, risk: RiskConfig, equity: float) -> Trade:
    price = contract.round_to_tick(price)
    gross = contract.pnl(pos.entry_price, price, pos.contracts, pos.is_long)
    costs = contract.cost(pos.contracts, risk.slippage_ticks)
    trade = Trade(
        signal=pos.signal, contracts=pos.contracts,
        entry_index=pos.entry_index, entry_ts=pos.entry_ts,
        entry_price=pos.entry_price, exit_index=i, exit_ts=candle.ts,
        exit_price=price, exit_reason=reason, gross=gross, costs=costs,
        r_multiple=pos.r_multiple(price), mfe_r=pos.mfe_r, mae_r=pos.mae_r,
    )
    trade.equity_after = equity + trade.net
    return trade


def compute_stats(result: BacktestResult) -> dict:
    trades = result.trades
    start = result.risk.starting_equity if result.risk else 0.0
    if not trades:
        return {"trades": 0, "starting_equity": start, "ending_equity": start}

    wins = [t for t in trades if t.net > 0]
    losses = [t for t in trades if t.net <= 0]
    gross_win = sum(t.net for t in wins)
    gross_loss = abs(sum(t.net for t in losses))
    rs = [t.r_multiple for t in trades]
    ending = trades[-1].equity_after

    # Drawdown on the closed-trade equity curve.
    peak, max_dd, max_dd_pct = start, 0.0, 0.0
    for t in trades:
        peak = max(peak, t.equity_after)
        dd = peak - t.equity_after
        if dd > max_dd:
            max_dd, max_dd_pct = dd, dd / peak * 100 if peak else 0.0

    by_grade: dict[str, dict] = {}
    for t in trades:
        g = by_grade.setdefault(t.signal.grade.letter, {"n": 0, "r": 0.0, "net": 0.0, "wins": 0})
        g["n"] += 1
        g["r"] += t.r_multiple
        g["net"] += t.net
        g["wins"] += 1 if t.net > 0 else 0

    by_touches: dict[int, dict] = {}
    for t in trades:
        n = t.signal.brk.line.touch_count
        d = by_touches.setdefault(n, {"n": 0, "r": 0.0, "net": 0.0, "wins": 0})
        d["n"] += 1
        d["r"] += t.r_multiple
        d["net"] += t.net
        d["wins"] += 1 if t.net > 0 else 0

    fresh = [t for t in trades if not t.signal.is_reversal]
    flips = [t for t in trades if t.signal.is_reversal]

    by_direction: dict[str, dict] = {}
    for t in trades:
        d = by_direction.setdefault(t.direction, {"n": 0, "r": 0.0, "net": 0.0, "wins": 0})
        d["n"] += 1
        d["r"] += t.r_multiple
        d["net"] += t.net
        d["wins"] += 1 if t.net > 0 else 0

    return {
        "trades": len(trades),
        "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100,
        "starting_equity": start, "ending_equity": ending,
        "net_profit": ending - start,
        "return_pct": (ending - start) / start * 100 if start else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "expectancy_r": sum(rs) / len(rs),
        "total_r": sum(rs),
        "avg_win_r": (sum(t.r_multiple for t in wins) / len(wins)) if wins else 0.0,
        "avg_loss_r": (sum(t.r_multiple for t in losses) / len(losses)) if losses else 0.0,
        "best_r": max(rs), "worst_r": min(rs),
        "max_drawdown": max_dd, "max_drawdown_pct": max_dd_pct,
        "avg_bars_held": sum(t.bars_held for t in trades) / len(trades),
        "total_costs": sum(t.costs for t in trades),
        "exit_reasons": Counter(t.exit_reason for t in trades),
        "by_grade": by_grade,
        "by_touches": by_touches,
        "fresh_breaks": len(fresh),
        "reversals": len(flips),
        "by_direction": by_direction,
    }
