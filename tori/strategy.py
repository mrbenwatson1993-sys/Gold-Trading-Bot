"""The strategy itself, as a bar-by-bar state machine.

    scan -> wait -> break -> enter -> safety line -> exit -> repeat

The one thing worth being explicit about is how the exit is modelled, because
it is where faithfulness to the method and futures reality pull against each
other.

  * The *primary* exit is Tori's: a candle CLOSING through the Safety Line.
    That is what lets a winner breathe through pullbacks instead of being
    shaken out by a wick.
  * A *resting* protective stop also sits in the market at the structural
    invalidation point, and fills intrabar. Without it a gap through the
    Safety Line -- a Sunday open, a CPI print -- is an unbounded loss, and on
    leveraged futures that is not survivable. It ratchets up to each new
    confirmed higher low (lower high for shorts), never down.

So the Safety Line decides when the trend is over; the resting stop only
decides how bad a gap is allowed to be.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .breaks import Break, detect_break
from .candles import Candle
from .config import StrategyConfig, grade_at_least
from .levels import Level, clean_space, find_levels
from .quality import Grade, grade_setup
from .structure import Structure, classify
from .swings import HIGH, LOW, Swing, find_swings, last_swing_before, visible_swings
from .trendlines import BEARISH, BULLISH, Trendline, build_trendlines, near_price


@dataclass
class Signal:
    """A graded, tradable break."""
    brk: Break
    grade: Grade
    structure: Structure
    entry_index: int          # bar the position opens on
    entry_price: float
    initial_stop: float
    room_r: float
    blocker: Level | None
    is_reversal: bool = False   # came from a flip, not a fresh line break

    @property
    def direction(self) -> str:
        return self.brk.direction

    @property
    def is_long(self) -> bool:
        return self.brk.is_long

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.initial_stop)


@dataclass
class Position:
    signal: Signal
    contracts: int
    entry_index: int
    entry_ts: int
    entry_price: float
    initial_stop: float
    action_line: Trendline
    safety_line: Trendline | None = None
    hard_stop: float = 0.0
    structural_anchor: Swing | None = None   # last pivot the stop trailed to
    safety_origin: Swing | None = None       # where the new trend began
    mfe_r: float = 0.0
    mae_r: float = 0.0

    @property
    def is_long(self) -> bool:
        return self.signal.is_long

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.initial_stop)

    def r_multiple(self, price: float) -> float:
        if self.risk <= 0:
            return 0.0
        move = (price - self.entry_price) if self.is_long else (self.entry_price - price)
        return move / self.risk

    def safety_value(self, index: int) -> float | None:
        return self.safety_line.value_at(index) if self.safety_line else None


    def broken_line(self, reason: str) -> Trendline:
        """Whichever line price just came back through.

        That line is the Action Line for the trade in the other direction --
        the same break, read from the other side.
        """
        if reason == "safety line" and self.safety_line is not None:
            return self.safety_line
        if reason == "hard stop" and self.safety_line is not None:
            # the resting stop rides the Safety Line, so it is that line
            return self.safety_line
        return self.action_line


@dataclass
class Trade:
    """A completed round turn."""
    signal: Signal
    contracts: int
    entry_index: int
    entry_ts: int
    entry_price: float
    exit_index: int
    exit_ts: int
    exit_price: float
    exit_reason: str
    gross: float = 0.0
    costs: float = 0.0
    r_multiple: float = 0.0
    mfe_r: float = 0.0
    mae_r: float = 0.0
    equity_after: float = 0.0

    @property
    def net(self) -> float:
        return self.gross - self.costs

    @property
    def bars_held(self) -> int:
        return self.exit_index - self.entry_index

    @property
    def direction(self) -> str:
        return self.signal.direction


class ToriStrategy:
    """Walks a candle series and produces signals and exits.

    Nothing here reads a bar beyond the one being processed. Swings are gated
    on `confirmed_at`, trendlines are rebuilt only from confirmed swings, and
    entries fill on the next bar's open by default.
    """

    def __init__(self, candles: list[Candle], atr: list[float],
                 cfg: StrategyConfig, alignment=None):
        self.candles = candles
        self.atr = atr
        self.cfg = cfg
        self.swings = find_swings(candles, cfg.swing_strength)
        self.alignment = alignment
        self._lines: list[Trendline] = []
        self._confirmed_count = 0
        self._levels: list[Level] = []
        self._levels_at = -1

    # --- trendline book ---------------------------------------------------
    def _refresh_lines(self, i: int) -> None:
        """Redraw the chart only when the drawable structure has changed.

        A trader redraws when a new swing completes, not on every candle, and
        doing the same here is both faithful and several times cheaper.
        """
        confirmed = sum(1 for s in self.swings if s.confirmed_at <= i)
        if confirmed != self._confirmed_count or not self._lines:
            self._confirmed_count = confirmed
            self._lines = build_trendlines(
                self.candles, self.swings, self.atr, self.cfg, i,
                intact_through=i)

    def levels_at(self, i: int) -> list[Level]:
        if self._levels_at != i:
            self._levels = find_levels(self.candles, self.swings, self.atr,
                                       self.cfg, i)
            self._levels_at = i
        return self._levels

    # --- entry ------------------------------------------------------------
    def scan(self, i: int) -> list[Trendline]:
        """Lines that are currently intact and that price has reached.

        The second half is STEP 4: a valid line price is nowhere near is not a
        setup yet, it is just a drawing.
        """
        self._refresh_lines(i)
        atr_ref = self.atr[i]
        return [ln for ln in self._lines
                if near_price(ln, self.candles[i], i, atr_ref, self.cfg)]

    def find_signal(self, i: int) -> Signal | None:
        """Test bar `i` for a tradable Action Line break."""
        if i + 1 >= len(self.candles):
            return None
        self._refresh_lines(i)
        atr_ref = self.atr[i]
        if atr_ref <= 0:
            return None

        candidates: list[Signal] = []
        survivors: list[Trendline] = []
        for line in self._lines:
            brk = detect_break(self.candles, line, i, atr_ref, self.cfg)
            if brk is None:
                survivors.append(line)   # line still holds
                continue
            # A close through the line retires it either way; whether we take
            # the trade is a separate question.
            signal = self._grade(brk, i, atr_ref)
            if signal is not None:
                candidates.append(signal)
        self._lines = survivors

        if not candidates:
            return None
        # If two lines broke on the same candle, take the better-evidenced one.
        return max(candidates, key=lambda s: (s.grade.score, s.brk.line.touch_count))

    def observe(self, i: int) -> None:
        """Keep the trendline book current on bars we are not looking to enter.

        Lines still break while a position is open. If they were not retired
        the book would hand back already-broken lines the moment we go flat
        again, and the strategy would trade a break that happened days ago.
        """
        self._refresh_lines(i)
        atr_ref = self.atr[i]
        if atr_ref <= 0:
            return
        self._lines = [
            ln for ln in self._lines
            if detect_break(self.candles, ln, i, atr_ref, self.cfg) is None
        ]

    def _grade(self, brk: Break, i: int, atr_ref: float) -> Signal | None:
        cfg = self.cfg
        entry_index = i + 1 if cfg.entry_mode == "next_open" else i
        if entry_index >= len(self.candles):
            return None
        entry_price = (self.candles[entry_index].open
                       if cfg.entry_mode == "next_open" else self.candles[i].close)

        stop = self._initial_stop(brk, i, atr_ref)
        if stop is None:
            return None
        risk = abs(entry_price - stop)
        if risk <= 0:
            return None

        if brk.line.touch_count > cfg.max_touches:
            return None
        # Do the timeframes above this one support the trade?
        if self.alignment is not None and cfg.htf_align != "none":
            if not self.alignment.agrees(i, brk.direction, cfg.htf_align):
                return None

        levels = self.levels_at(i)
        room_r, blocker = clean_space(levels, entry_price, brk.direction, risk, atr_ref)
        structure = classify(self.candles, self.swings, i)
        grade = grade_setup(brk, cfg, structure, levels, room_r, blocker, risk)

        if not grade_at_least(grade.letter, cfg.min_grade):
            return None
        if cfg.require_trending_htf and not structure.is_trending:
            return None

        return Signal(brk=brk, grade=grade, structure=structure,
                      entry_index=entry_index, entry_price=entry_price,
                      initial_stop=stop, room_r=room_r, blocker=blocker)

    def _initial_stop(self, brk: Break, i: int, atr_ref: float) -> float | None:
        """Where the trade is structurally wrong, before a Safety Line exists.

        For a long off a broken downtrend that is the last swing low before the
        break: if price goes back under it, the break failed and the downtrend
        was never broken at all.
        """
        buffer = self.cfg.initial_stop_buffer_atr * atr_ref
        pivot = LOW if brk.is_long else HIGH
        swing = last_swing_before(
            [s for s in self.swings if s.confirmed_at <= i], i, pivot)
        if swing is None:
            return None
        if brk.is_long:
            stop = swing.price - buffer
            return stop if stop < brk.close else None
        stop = swing.price + buffer
        return stop if stop > brk.close else None

    # --- management -------------------------------------------------------
    def open_position(self, signal: Signal, contracts: int) -> Position:
        entry = self.candles[signal.entry_index]
        pos = Position(
            signal=signal, contracts=contracts,
            entry_index=signal.entry_index, entry_ts=entry.ts,
            entry_price=signal.entry_price, initial_stop=signal.initial_stop,
            action_line=signal.brk.line, hard_stop=signal.initial_stop,
        )
        pivot = LOW if pos.is_long else HIGH
        anchor = last_swing_before(
            [s for s in self.swings if s.confirmed_at <= signal.brk.index],
            signal.brk.index, pivot)
        pos.structural_anchor = anchor
        pos.safety_origin = anchor
        return pos

    def update_safety_line(self, pos: Position, i: int) -> None:
        """Draw / redraw the opposing trendline from the new structure.

        For a long that means higher lows. The pivot that defined the initial
        stop counts as the first of them -- it is the low the new uptrend
        started from -- so the Safety Line can become active after a single new
        swing rather than waiting for two.
        """
        cfg = self.cfg
        pivot = LOW if pos.is_long else HIGH
        origin = pos.safety_origin
        if origin is None:
            return
        pool = [s for s in visible_swings(self.swings, i, pivot)
                if s.index > origin.index]
        if not pool:
            return

        if cfg.safety_anchor == "origin":
            # Keep the near end pinned to where the new trend began and swing
            # the far end up to the newest higher low. A line drawn across the
            # last two swings instead gets steeper and steeper as the trend
            # ages, and ends up knifing through a perfectly healthy pullback.
            a, b = origin, pool[-1]
        else:
            if len(pool) < 2:
                return
            a, b = pool[-2], pool[-1]

        improving = (b.price > a.price) if pos.is_long else (b.price < a.price)
        if not improving or b.index <= a.index:
            return   # structure has not made a new higher low / lower high yet

        slope = (b.price - a.price) / (b.index - a.index)
        line = Trendline(
            kind=BULLISH if pos.is_long else BEARISH,
            anchor_index=a.index, anchor_price=a.price, slope=slope,
            touches=[a, b], atr_ref=self.atr[i],
        )

        # Count how many pivots actually sit on this line, rather than
        # recording just the two anchors. Without this every Safety Line looks
        # like a 2-touch line, and in always-in mode -- where each reversal
        # adopts the broken Safety Line as its Action Line -- that silently
        # labels almost every trade a 2-touch setup.
        tol = cfg.touch_tolerance_atr * self.atr[i]
        line.touches = [s for s in visible_swings(self.swings, i, pivot)
                        if s.index >= a.index
                        and abs(s.price - line.value_at(s.index)) <= tol]
        if a not in line.touches:
            line.touches.insert(0, a)
        if b not in line.touches:
            line.touches.append(b)
        line.touches.sort(key=lambda s: s.index)

        if cfg.safety_only_improves and pos.safety_line is not None:
            old, new = pos.safety_line.value_at(i), line.value_at(i)
            if (new < old) if pos.is_long else (new > old):
                return   # never loosen a stop
        pos.safety_line = line

        # Ratchet the resting stop to the newer structural pivot.
        buffer = cfg.initial_stop_buffer_atr * self.atr[i]
        candidate = b.price - buffer if pos.is_long else b.price + buffer
        if (candidate > pos.hard_stop) if pos.is_long else (candidate < pos.hard_stop):
            pos.hard_stop = candidate
            pos.structural_anchor = b

    def reversal(self, pos: Position, i: int, reason: str) -> Signal | None:
        """Turn an exit into the entry for the opposite direction.

        Always-in means the position that just closed and the one about to
        open are two readings of one event: price broke the line it had been
        respecting. The broken line becomes the new Action Line, and the new
        Safety Line gets drawn from whatever structure forms next.
        """
        if i + 1 >= len(self.candles):
            return None
        atr_ref = self.atr[i]
        if atr_ref <= 0:
            return None

        line = pos.broken_line(reason)
        direction = "short" if pos.is_long else "long"
        c = self.candles[i]
        level = line.value_at(i)
        displacement = abs(c.close - level)

        brk = Break(
            line=line, index=i, ts=c.ts, close=c.close, line_value=level,
            displacement_atr=displacement / atr_ref, body_ratio=c.body_ratio,
            direction=direction, strong=True, atr_ref=atr_ref,
        )

        entry_index = i + 1
        entry_price = self.candles[entry_index].open
        stop = self._initial_stop(brk, i, atr_ref)
        if stop is None:
            return None
        risk = abs(entry_price - stop)
        if risk <= 0:
            return None

        levels = self.levels_at(i)
        room_r, blocker = clean_space(levels, entry_price, direction, risk, atr_ref)
        structure = classify(self.candles, self.swings, i)
        grade = grade_setup(brk, self.cfg, structure, levels, room_r, blocker, risk)
        return Signal(brk=brk, grade=grade, structure=structure,
                      entry_index=entry_index, entry_price=entry_price,
                      initial_stop=stop, room_r=room_r, blocker=blocker,
                      is_reversal=True)

    def check_exit(self, pos: Position, i: int) -> tuple[float, str] | None:
        """Resolve bar `i` for an open position -> (exit price, reason).

        The resting stop is checked first and against the bar's extremes,
        because within a single bar we cannot know whether the stop or the
        close came first, and assuming the worse of the two is the only honest
        choice.
        """
        c = self.candles[i]

        if pos.is_long and c.low <= pos.hard_stop:
            return min(pos.hard_stop, c.open), "hard stop"
        if not pos.is_long and c.high >= pos.hard_stop:
            return max(pos.hard_stop, c.open), "hard stop"

        self.update_safety_line(pos, i)
        buffer = self.cfg.safety_buffer_atr * self.atr[i]
        safety = pos.safety_value(i)
        if safety is not None:
            # The opposing trendline, extended. Price breaking back through it
            # is the whole exit rule -- there is no target, so this is the only
            # thing that ends a winning trade.
            if pos.is_long and c.close < safety - buffer:
                return c.close, "safety line"
            if not pos.is_long and c.close > safety + buffer:
                return c.close, "safety line"
        else:
            # No new structure yet, so the Action Line is still the reference.
            # It stays extended after the break, and price closing back through
            # it means the break failed and the old trend never actually ended.
            action = pos.action_line.value_at(i)
            if pos.is_long and c.close < action - buffer:
                return c.close, "failed break"
            if not pos.is_long and c.close > action + buffer:
                return c.close, "failed break"

        # Survived the bar: drag the stop along the line, ready for the next
        # one. This happens last so the stop protecting bar i+1 is placed
        # using nothing beyond bar i.
        self._advance_stop(pos, i)

        # Track excursions for reporting.
        best = c.high if pos.is_long else c.low
        worst = c.low if pos.is_long else c.high
        pos.mfe_r = max(pos.mfe_r, pos.r_multiple(best))
        pos.mae_r = min(pos.mae_r, pos.r_multiple(worst))
        return None

    def _advance_stop(self, pos: Position, i: int) -> None:
        """Move the stop to where the Safety Line sits on the next bar.

        The line slopes, so this moves every single bar rather than only when
        a new swing confirms -- that is the difference between a stop trailing
        the structure and one parked under an old low. It only ever moves in
        the trade's favour.

        Extrapolating the line one bar forward is not lookahead: the line is
        fully determined by swings already confirmed at bar i, so where it will
        sit at i+1 is known now. That is exactly how a resting order is placed.
        """
        if not self.cfg.stop_follows_safety or pos.safety_line is None:
            return
        buffer = self.cfg.trail_buffer_atr * self.atr[i]
        nxt = pos.safety_line.value_at(i + 1)
        candidate = nxt - buffer if pos.is_long else nxt + buffer
        if (candidate > pos.hard_stop) if pos.is_long else (candidate < pos.hard_stop):
            pos.hard_stop = candidate
