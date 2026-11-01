"""One contextual hypothesis; no indicator entries or generic candle mixtures."""
from datetime import time
from statistics import median
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
CASES={'impulse_first_pullback':('impulse_first_pullback',)}

def names_at(case,stamp):
    return CASES[case]

def pattern(history,name):
    if name!='impulse_first_pullback' or len(history)<15:
        return None
    current=history[-1]
    if not time(9,35)<=current.timestamp.astimezone(NY).time()<=time(11,30):
        return None
    if current.close<=current.open:
        return None
    for count in (1,2,3):
        index=len(history)-count-2
        if index<12:
            continue
        impulse=history[index]
        before=history[index-12:index]
        pullback=history[index+1:-1]
        span=impulse.high-impulse.low
        typical=median(b.high-b.low for b in before)
        level=max(b.high for b in before)
        if typical<=0 or span<1.5*typical:
            continue
        if impulse.close<=level or impulse.close-impulse.open<.65*span or impulse.close<impulse.high-.2*span:
            continue
        support=max(level,impulse.high-.5*span)
        if pullback[0].close>=impulse.close:
            continue
        if any(b.low<support or b.high>impulse.high for b in pullback):
            continue
        if current.low<support or current.close<=impulse.high:
            continue
        return {'stop':min(b.low for b in [*pullback,current])*.999,
                'reason':f'Impulse closes above prior 12-bar high with >=1.5x median range and >=65% bullish body; first {count}-bar pullback holds breakout and upper half; bullish close above impulse high'}
    return None
