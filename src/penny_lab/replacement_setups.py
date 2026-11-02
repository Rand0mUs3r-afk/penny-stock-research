"""Causal ORB, bull-flag first pullback and VWAP-reclaim portfolio."""
from datetime import time
from statistics import mean,median
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
COMPONENTS=('opening_range_breakout','impulse_first_pullback','vwap_reclaim')
CASES={'classic_blend_mix':COMPONENTS}

def names_at(case,stamp):
    clock=stamp.astimezone(NY).time()
    return tuple(n for n in CASES[case] if (time(9,45)<clock<=time(11,30) if n=='opening_range_breakout' else time(9,35)<=clock<=time(11,30) if n=='impulse_first_pullback' else time(10)<=clock<=time(15)))

def session_vwap(history):
    total=volume=0.
    result=[]
    for b in history:
        total+=(b.high+b.low+b.close)/3*b.volume
        volume+=b.volume
        result.append(total/volume if volume>0 else None)
    return result

def first_pullback(history):
    if len(history)<15:
        return None
    current=history[-1]
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
        if pullback[0].close>=impulse.close or any(b.low<support or b.high>impulse.high for b in pullback):
            continue
        if current.low<support or current.close<=impulse.high:
            continue
        return {'stop':min(b.low for b in [*pullback,current])*.999,'reason':f'Bull flag: impulse above prior 12-bar high, >=1.5x median range, >=65% bullish body; first {count}-bar shallow pullback; close above impulse high and session VWAP'}
    return None

def pattern(history,name):
    if len(history)<4 or name not in COMPONENTS:
        return None
    current,previous=history[-1],history[-2]
    if name not in names_at('classic_blend_mix',current.timestamp) or current.close<=current.open:
        return None
    vwap=session_vwap(history)
    if vwap[-1] is None or current.close<=vwap[-1]:
        return None
    prior=history[-13:-1]
    average=mean(b.volume for b in prior)
    if average<=0:
        return None
    if name=='opening_range_breakout':
        opening=[b for b in history if time(9,35)<=b.timestamp.astimezone(NY).time()<=time(9,45)]
        if len(opening)!=3:
            return None
        ceiling=max(b.high for b in opening)
        earlier=[b for b in history[:-1] if b.timestamp>opening[-1].timestamp]
        if any(b.close>ceiling for b in earlier):
            return None
        if current.close>ceiling and current.volume>=1.5*average:
            return {'stop':current.low*.999,'reason':'First close above 15-minute opening range and session VWAP with >=1.5x preceding mean volume'}
    elif name=='impulse_first_pullback':
        return first_pullback(history)
    elif name=='vwap_reclaim':
        if len(history)<12 or vwap[-2] is None:
            return None
        if previous.close<=vwap[-2] and current.close>previous.high and current.volume>=average:
            return {'stop':min(b.low for b in history[-3:])*.999,'reason':'Previous close at/below its causal session VWAP; bullish close reclaims current VWAP and prior candle high; volume >= preceding mean'}
    return None
