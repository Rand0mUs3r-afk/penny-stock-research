"""Deterministic initial hypotheses, not validated trading edges."""
from statistics import mean
from .config import Config
from .models import Bar, Signal


def scan(history: list[Bar], cfg: Config) -> list[Signal]:
    if len(history) < cfg.lookback + 3:
        return []
    current, previous = history[-1], history[-2]
    base = history[-cfg.lookback - 2:-2]
    avg_volume = mean(b.volume for b in base)
    if current.volume <= 0 or avg_volume <= 0:
        return []
    if mean(b.close * b.volume for b in base) < cfg.min_avg_dollar_volume:
        return []
    if current.close >= cfg.max_price:
        return []
    rvol = current.volume / avg_volume
    support, resistance = min(b.low for b in base), max(b.high for b in base)
    tolerance = 0.003
    out: list[Signal] = []

    def emit(name: str, stop: float, reason: str):
        if name in cfg.strategies and 0 < stop < current.close:
            score = min(rvol, 5.0) + min((current.close - stop) / current.close, 0.1)
            out.append(Signal(current.symbol, name, current.timestamp, stop, score, reason))

    # Prior bar must actually cross a level fixed before that prior bar.
    if (base[-1].close <= resistance and previous.close > resistance
            and previous.volume >= 1.5 * avg_volume
            and resistance * (1 - tolerance) <= current.low <= resistance * (1 + tolerance)
            and current.close > max(resistance, current.open)):
        emit("breakout_retest", current.low * 0.999, "Prior-bar resistance break on >=1.5x volume; current retest held")

    a, b = base[:len(base)//2], base[len(base)//2:]
    rising = max(x.high for x in b) > max(x.high for x in a) and min(x.low for x in b) > min(x.low for x in a)
    if (rising and previous.close < base[-1].close and previous.low >= min(x.low for x in b)
            and current.close > previous.high and current.close > current.open and rvol >= 1):
        emit("uptrend_pullback", min(previous.low, current.low) * 0.999,
             "Higher-window highs/lows, one-bar pullback, then close above pullback high")

    touches = [i for i, bar in enumerate(base) if bar.low <= support * (1 + tolerance)]
    separated = len(touches) >= 2 and touches[-1] - touches[0] >= 2
    if (separated and support * (1 - tolerance) <= current.low <= support * (1 + tolerance)
            and current.close > max(previous.close, current.open) and rvol >= 1):
        emit("support_bounce", min(support, current.low) * 0.999,
             "Two separated historical support touches; current bullish bounce")

    volume_before = sum(x.volume for x in history[:-1])
    volume_now = volume_before + current.volume
    if volume_before > 0 and volume_now > 0:
        numerator = sum(((x.high + x.low + x.close) / 3) * x.volume for x in history[:-1])
        old_vwap = numerator / volume_before
        new_vwap = (numerator + ((current.high + current.low + current.close) / 3) * current.volume) / volume_now
        if previous.close <= old_vwap and current.close > new_vwap and current.close > current.open and rvol >= 1.5:
            emit("vwap_reclaim", min(previous.low, current.low) * 0.999,
                 "Cross above bar-typical-price session VWAP on >=1.5x relative volume")
    return out
