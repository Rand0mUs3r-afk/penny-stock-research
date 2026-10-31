from math import floor, isfinite
from .config import Config


def adverse_price(price: float, buy: bool, cfg: Config) -> float:
    haircut = (cfg.spread_bps / 2 + cfg.slippage_bps) / 10000
    return price * (1 + haircut if buy else 1 - haircut)


def size_position(entry: float, stop: float, cash: float, risk_room: float,
                  prior_volume: float, cfg: Config) -> tuple[int, float]:
    """Entry includes adverse costs; reserve both fees in planned risk.

    Exit haircut at stop is included. Gaps can still exceed planned risk.
    Liquidity cap uses only the PREVIOUS completed bar's volume.
    """
    if not all(isfinite(v) for v in (entry, stop, cash, risk_room, prior_volume)):
        return 0, 0.0
    if not 0 < stop < entry or min(cash, risk_room, prior_volume) <= 0:
        return 0, 0.0
    unit_risk = entry - adverse_price(stop, False, cfg)
    budget = min(cfg.risk_per_position, risk_room) - 2 * cfg.fee_per_order
    affordable = min(cfg.allocation, cash) - cfg.fee_per_order
    if budget <= 0 or affordable <= 0:
        return 0, 0.0
    n = max(0, min(floor(affordable / entry), floor(budget / unit_risk),
                   floor(prior_volume * cfg.max_volume_fraction)))
    return n, n * unit_risk + 2 * cfg.fee_per_order if n else 0.0
