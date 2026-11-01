"""Predeclared experimental long-only rules, not validated edges."""
from datetime import time
from statistics import mean
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
CASES={
 'orb':('opening_range_breakout',),
 'failed_breakdown':('failed_breakdown_recovery',),
 'compression':('compression_continuation',),
 'orb_then_pullback':('opening_range_pullback',),
 'time_separated_mix':('opening_range_breakout','compression_continuation')}

def names_at(case,stamp):
    clock=stamp.astimezone(NY).time()
    if case=='time_separated_mix':
        if clock<=time(11,30):
            return ('opening_range_breakout',)
        if time(12)<=clock<=time(15):
            return ('compression_continuation',)
        return ()
    return CASES[case]

def pattern(history,name):
    if len(history)<4:
        return None
    current,previous=history[-1],history[-2]
    clock=current.timestamp.astimezone(NY).time()
    prior=history[max(0,len(history)-13):-1]
    average=mean(b.volume for b in prior)
    if average<=0 or current.close<=current.open:
        return None
    if name in ('opening_range_breakout','opening_range_pullback'):
        opening=[b for b in history if time(9,35)<=b.timestamp.astimezone(NY).time()<=time(9,45)]
        if len(opening)!=3 or not time(9,45)<clock<=time(11,30):
            return None
        ceiling=max(b.high for b in opening)
        if name=='opening_range_breakout':
            earlier=[b for b in history[:-1] if b.timestamp>opening[-1].timestamp]
            if any(b.close>ceiling for b in earlier):
                return None
            if current.close>ceiling and current.volume>=1.5*average:
                return {'stop':current.low*.999,'reason':'First completed close above 15-minute opening range; >=1.5x preceding-bar mean volume'}
        else:
            earlier=[b for b in history[:-2] if b.timestamp>opening[-1].timestamp and b.close>ceiling]
            if earlier and ceiling*.997<=previous.low<=ceiling*1.003 and previous.close>=ceiling and current.low>=ceiling*.997 and current.close>previous.high and current.volume>=average:
                return {'stop':min(previous.low,current.low)*.999,'reason':'Opening-range break followed by defended pullback and recovery close'}
    elif name=='failed_breakdown_recovery':
        if len(history)<14 or clock>time(15):
            return None
        base=history[-14:-2]
        support=min(b.low for b in base)
        if previous.low<support and previous.close>support and previous.close>previous.open and current.low>=previous.low and current.close>previous.high and current.volume>=average:
            return {'stop':previous.low*.999,'reason':'Sweep below historical support, close recovery, then confirming close above recovery high'}
    elif name=='compression_continuation':
        if len(history)<13 or clock>time(15):
            return None
        impulse=history[-13:-5]
        pause=history[-5:-1]
        impulse_range=max(b.high for b in impulse)-min(b.low for b in impulse)
        ceiling=max(b.high for b in pause)
        floor=min(b.low for b in pause)
        rising=impulse[-1].close>impulse[0].close and min(b.low for b in impulse[4:])>min(b.low for b in impulse[:4])
        if rising and impulse_range>0 and ceiling-floor<=.5*impulse_range and floor>min(b.low for b in impulse) and previous.close<=ceiling<current.close and current.volume>=1.5*mean(b.volume for b in pause):
            return {'stop':floor*.999,'reason':'Rising eight-bar impulse, four-bar compression <=50% of impulse range, volume-confirmed breakout'}
    return None

def overhead_reference(history,previous_session=None):
    """Nearest overhead historical high, confirmed with no future candles."""
    candidates=[]
    if previous_session and previous_session['target']>history[-1].close:
        candidates.append(previous_session)
    for i in range(2,len(history)-2):
        bar=history[i]
        neighbours=history[i-2:i]+history[i+1:i+3]
        if bar.high>max(b.high for b in neighbours) and bar.high>history[-1].close:
            candidates.append({'target':bar.high,'reference_time':bar.timestamp.isoformat(),'reference_rule':'intraday_pivot_high_confirmed_by_two_completed_right_bars'})
    return min(candidates,key=lambda c:c['target']) if candidates else None
