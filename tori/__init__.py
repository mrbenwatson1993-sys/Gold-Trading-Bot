"""Tori Trades trendline strategy engine.

A deliberately simple, price-action-only system:
swing points -> trendlines -> 3-touch break (Action Line) -> ride it -> exit on
the opposing trendline (Safety Line).

No indicator stack. ATR is used only for scale-normalisation (tolerances,
displacement, spacing), never as a signal.
"""

__version__ = "0.1.0"
