"""Futures contract specifications.

Everything downstream sizes and prices in *contracts and ticks*, not in
fractional units, because that is how the strategy will actually be traded.
A spot pseudo-instrument is included so spot/CFD series can be run through the
same engine while developing.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class Contract:
    """A tradable futures contract."""

    symbol: str
    name: str
    tick_size: float          # minimum price increment, in price points
    tick_value: float         # $ per tick per contract
    commission: float         # $ per contract per side (round turn = 2x)
    currency: str = "USD"

    @property
    def point_value(self) -> float:
        """$ per 1.00 of price movement, per contract."""
        return self.tick_value / self.tick_size

    def round_to_tick(self, price: float) -> float:
        """Snap a price to the contract's tick grid."""
        return round(round(price / self.tick_size) * self.tick_size, 10)

    def ticks_between(self, a: float, b: float) -> float:
        return abs(a - b) / self.tick_size

    def pnl(self, entry: float, exit_price: float, contracts: int, is_long: bool) -> float:
        """Gross P&L in account currency, before costs."""
        move = (exit_price - entry) if is_long else (entry - exit_price)
        return move * self.point_value * contracts

    def cost(self, contracts: int, slippage_ticks: float) -> float:
        """Round-turn commission plus slippage on both fills."""
        commissions = self.commission * 2 * contracts
        slip = slippage_ticks * 2 * self.tick_value * contracts
        return commissions + slip

    def contracts_for_risk(self, risk_dollars: float, stop_distance: float) -> int:
        """How many whole contracts keep the loss at/below `risk_dollars`.

        Returns 0 when even a single contract would risk more than allowed --
        the trade is then too wide for the account and must be skipped rather
        than silently over-risked.
        """
        if stop_distance <= 0:
            return 0
        risk_per_contract = stop_distance * self.point_value
        if risk_per_contract <= 0:
            return 0
        return max(0, floor(risk_dollars / risk_per_contract))


# Specs as listed by CME (tick/value); commissions are typical retail
# all-in round-turn halves and should be set to your broker's real numbers.
REGISTRY: dict[str, Contract] = {
    "GC":  Contract("GC",  "Gold (100 oz)",          0.10,  10.00, 2.50),
    "MGC": Contract("MGC", "Micro Gold (10 oz)",     0.10,   1.00, 0.75),
    "SI":  Contract("SI",  "Silver (5,000 oz)",      0.005, 25.00, 2.50),
    "SIL": Contract("SIL", "Micro Silver (1,000oz)", 0.005,  5.00, 1.00),
    "HG":  Contract("HG",  "Copper (25,000 lb)",     0.0005,12.50, 2.50),
    "CL":  Contract("CL",  "Crude Oil (1,000 bbl)",  0.01,  10.00, 2.50),
    "MCL": Contract("MCL", "Micro Crude Oil",        0.01,   1.00, 0.75),
    "NG":  Contract("NG",  "Natural Gas",            0.001, 10.00, 2.50),
    "ES":  Contract("ES",  "E-mini S&P 500",         0.25,  12.50, 2.25),
    "MES": Contract("MES", "Micro E-mini S&P 500",   0.25,   1.25, 0.60),
    "NQ":  Contract("NQ",  "E-mini Nasdaq 100",      0.25,   5.00, 2.25),
    "MNQ": Contract("MNQ", "Micro E-mini Nasdaq",    0.25,   0.50, 0.60),
    "YM":  Contract("YM",  "E-mini Dow",             1.0,    5.00, 2.25),
    "MYM": Contract("MYM", "Micro E-mini Dow",       1.0,    0.50, 0.60),
    "RTY": Contract("RTY", "E-mini Russell 2000",    0.10,   5.00, 2.25),
    "M2K": Contract("M2K", "Micro E-mini Russell",   0.10,   0.50, 0.60),
    "ZB":  Contract("ZB",  "30-Year T-Bond",         0.03125,31.25, 2.00),
    "ZN":  Contract("ZN",  "10-Year T-Note",         0.015625,15.625, 2.00),
    "6E":  Contract("6E",  "Euro FX",                0.00005,6.25, 2.50),
    "6J":  Contract("6J",  "Japanese Yen",           0.0000005, 6.25, 2.50),
    "6B":  Contract("6B",  "British Pound",          0.0001, 6.25, 2.50),
    "6A":  Contract("6A",  "Australian Dollar",      0.0001,10.00, 2.50),
    # Micro FX. Sized so a 1% risk budget can hold a position on a retail
    # account; the majors are all quoted around 1.0 so one spec covers them.
    "M6E": Contract("M6E", "Micro Euro FX",          0.0001, 1.25, 0.50),
    "M6B": Contract("M6B", "Micro British Pound",    0.0001, 0.625, 0.50),
    "M6A": Contract("M6A", "Micro Australian Dollar",0.0001, 1.00, 0.50),
    # Yen pairs quote around 150 rather than 1.0, so they need their own
    # scale. This approximates the economics of a micro yen position rather
    # than reproducing 6J exactly (6J is quoted the other way up).
    "M6J": Contract("M6J", "Micro Yen (USDJPY quote)", 0.01, 1.00, 0.50),
    # Pseudo-instrument: 1 unit = 1 point, no leverage. For spot/CFD series.
    "SPOT": Contract("SPOT", "Spot / CFD (1 unit)",  0.01,   0.01, 0.00),
}


def get_contract(symbol: str) -> Contract:
    key = symbol.upper()
    if key not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown contract {symbol!r}; known: {known}")
    return REGISTRY[key]
