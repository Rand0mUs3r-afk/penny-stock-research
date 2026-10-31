from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True)
class Bar:
    """Timestamp is the aware END of a completed bar; OHLC are raw prices."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self):
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not self.symbol or self.timestamp.utcoffset() is None:
            raise ValueError("Symbol and timezone-aware bar-end timestamp required")
        if not all(isfinite(v) for v in values):
            raise ValueError("Non-finite bar")
        if min(values[:4]) <= 0 or self.volume < 0:
            raise ValueError("Invalid price or volume")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError("Inconsistent OHLC")


@dataclass(frozen=True)
class Signal:
    symbol: str
    strategy: str
    timestamp: datetime
    stop: float
    score: float
    reason: str


@dataclass
class Position:
    signal: Signal
    entry_time: datetime
    entry: float
    shares: int
    stop: float
    target: float
    planned_risk: float
    entry_fee: float


@dataclass(frozen=True)
class Trade:
    symbol: str
    strategy: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry: float
    exit: float
    shares: int
    stop: float
    target: float
    planned_risk: float
    net_pnl: float
    exit_reason: str
    entry_reason: str
