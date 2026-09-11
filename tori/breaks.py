"""The break of the Action Line.

Once price breaks a trendline, that trendline stops being a drawing and
becomes the Action Line: the thing that says *act*. Two rules govern this and
both are Tori's:

  * you do not anticipate the break -- a line that "looks like it will go" is
    not a signal;
  * the candle must CLOSE through the line, not wick through it and snap back.

The displacement and body filters on top are our mechanical addition. They
separate a candle that genuinely drove through the line from one that limped a
tick past it on the close.
"""

from __future__ import annotations

from dataclasses import dataclass

from .candles import Candle
from .config import StrategyConfig
from .trendlines import BEARISH, Trendline


@dataclass
class Break:
    line: Trendline
    index: int
    ts: int
    close: float
    line_value: float
    displacement_atr: float   # how far beyond the line the candle closed
    body_ratio: float
    direction: str            # "long" | "short"
    strong: bool              # displacement + body both convincing
    atr_ref: float

    @property
    def is_long(self) -> bool:
        return self.direction == "long"

    def describe(self) -> str:
        tag = "strong" if self.strong else "weak"
        return (f"{self.direction.upper()} break of {self.line.touch_count}-touch "
                f"{self.line.kind} line @ {self.line_value:.2f} "
                f"(close {self.close:.2f}, {self.displacement_atr:.2f} ATR through, {tag})")


def detect_break(candles: list[Candle], line: Trendline, index: int,
                 atr_ref: float, cfg: StrategyConfig) -> Break | None:
    """Test bar `index` for a closing break of `line`.

    Returns a Break for *any* close through the line -- including a weak one.
    A weak break still kills the trendline (price has closed through it, so it
    no longer holds), it just is not worth trading. The caller decides.
    """
    if index >= len(candles) or atr_ref <= 0:
        return None
    c = candles[index]
    level = line.at(index, c.ts)
    close_tol = cfg.max_close_violation_atr * atr_ref

    if line.kind == BEARISH:
        if c.close <= level + close_tol:
            return None
        direction, displacement = "long", c.close - level
        right_way = c.is_up
    else:
        if c.close >= level - close_tol:
            return None
        direction, displacement = "short", level - c.close
        right_way = not c.is_up

    displacement_atr = displacement / atr_ref
    strong = (displacement_atr >= cfg.break_min_displacement_atr
              and c.body_ratio >= cfg.break_min_body_ratio
              and right_way)

    return Break(
        line=line, index=index, ts=c.ts, close=c.close, line_value=level,
        displacement_atr=displacement_atr, body_ratio=c.body_ratio,
        direction=direction, strong=strong, atr_ref=atr_ref,
    )
