from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
import tomllib

STRATEGIES=("breakout_retest","uptrend_pullback","support_bounce","vwap_reclaim")
LAB_STRATEGIES=('opening_range_breakout','failed_breakdown_recovery','compression_continuation','opening_range_pullback')
REPLACEMENT_STRATEGIES=('ema_trend_cross','bollinger_rsi_reentry','double_bottom_neckline')
PRICE_ACTION_STRATEGIES=('engulfing_at_low','three_candle_reversal','stair_step_continuation')
CONTEXT_STRATEGIES=('impulse_first_pullback',)
SIP_STRATEGIES=('sip_orb5','sip_orb15','sip_pullback','sip_vwap_bounce','sip_vwap_reclaim','sip_gap_go')
SUPPORTED_STRATEGIES=STRATEGIES+LAB_STRATEGIES+REPLACEMENT_STRATEGIES+PRICE_ACTION_STRATEGIES+CONTEXT_STRATEGIES+SIP_STRATEGIES

@dataclass(frozen=True)
class Config:
    starting_equity: float = 2000.0
    allocation: float = 300.0
    risk_per_position: float = 20.0
    portfolio_risk_cap: float | None = None
    max_price: float = 10.0
    universe: str = 'listed_under_10'
    timeframe_minutes: int = 5
    lookback: int = 12
    reward_risk: float = 2.0
    spread_bps: float = 50.0
    slippage_bps: float = 25.0
    fee_per_order: float = 0.0
    max_volume_fraction: float = 0.01
    min_avg_dollar_volume: float = 10000.0
    strategies: tuple[str,...] = STRATEGIES

    def __post_init__(self):
        positive=(self.starting_equity,self.allocation,self.risk_per_position,self.max_price,self.reward_risk,self.min_avg_dollar_volume)
        nonnegative=(self.spread_bps,self.slippage_bps,self.fee_per_order)
        if not all(isfinite(v) and v>0 for v in positive):
            raise ValueError('Money, price, liquidity and reward/risk must be finite and positive')
        if not all(isfinite(v) and v>=0 for v in nonnegative):
            raise ValueError('Costs must be finite and nonnegative')
        if self.portfolio_risk_cap is not None and (not isfinite(self.portfolio_risk_cap) or self.portfolio_risk_cap<=0):
            raise ValueError('Invalid portfolio risk cap')
        if not isfinite(self.max_volume_fraction) or not 0<self.max_volume_fraction<=1:
            raise ValueError('Volume fraction must be in (0, 1]')
        if self.timeframe_minutes!=5 or self.lookback<6:
            raise ValueError('Foundation supports 5-minute bars and lookback >= 6')
        if self.spread_bps/2+self.slippage_bps>=10000:
            raise ValueError('Cost haircut must be below 100%')
        if self.universe not in ('listed_under_10','otc'):
            raise ValueError('Unknown universe')
        if not self.strategies or len(set(self.strategies))!=len(self.strategies) or set(self.strategies)-set(SUPPORTED_STRATEGIES):
            raise ValueError('Select unique supported strategies')

    def to_dict(self):
        return asdict(self)

def load_config(path: str | None = None) -> Config:
    values=tomllib.loads(Path(path).read_text()) if path else {}
    if 'strategies' in values:
        values['strategies']=tuple(values['strategies'])
    return Config(**values)
