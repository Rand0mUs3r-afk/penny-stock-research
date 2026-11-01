"""Active price-action experiments. No moving-average or oscillator entries."""
from datetime import time
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
CASES={
 'engulfing_low':('engulfing_at_low',),
 'three_candle':('three_candle_reversal',),
 'stair_step':('stair_step_continuation',),
 'reversal_mix':('engulfing_at_low','three_candle_reversal'),
 'price_action_mix':('engulfing_at_low','three_candle_reversal','stair_step_continuation')}

def names_at(case,stamp):
    return CASES[case]

def pattern(history,name):
    if len(history)<13:
        return None
    c=history[-1]
    if c.timestamp.astimezone(NY).time()>time(15) or c.close<=c.open:
        return None
    a,b=history[-3:-1]
    if name=='engulfing_at_low':
        reference_low=min(x.low for x in history[-13:-1])
        if b.close<b.open and c.open<=b.close and c.close>b.open and min(b.low,c.low)<=reference_low:
            return {'stop':min(b.low,c.low)*.999,'reason':'Bullish real body engulfs prior bearish body at or below preceding 12-candle low'}
    elif name=='three_candle_reversal':
        small_body=abs(b.close-b.open)<=.5*(b.high-b.low)
        if a.close<a.open and b.low<a.low and small_body and c.close>a.high:
            return {'stop':min(a.low,b.low,c.low)*.999,'reason':'Bearish candle, lower-low small-body candle, then bullish close above first candle high'}
    elif name=='stair_step_continuation':
        x,y,z=history[-4:-1]
        rising=x.low<y.low<z.low and x.high<y.high<z.high and x.close<y.close<z.close
        if rising and c.low>z.low and c.close>z.high:
            return {'stop':min(x.low,y.low,z.low,c.low)*.999,'reason':'Three preceding candles form higher highs, lows and closes; fourth holds higher low and closes above prior high'}
    return None
