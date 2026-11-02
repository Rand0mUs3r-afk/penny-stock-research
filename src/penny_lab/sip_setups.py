"""Fixed-rule stocks-in-play components; completed session candles only."""
from datetime import time
from statistics import mean
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
COMPONENTS=('sip_orb5','sip_orb15','sip_pullback','sip_vwap_bounce','sip_vwap_reclaim','sip_gap_go')
CASES={name:((name,), 'signal') for name in COMPONENTS}
CASES.update({'orb5_range_stop':(('sip_orb5',),'range'),'orb15_range_stop':(('sip_orb15',),'range'),
              'blend_orb5':(('sip_orb5',*COMPONENTS[2:]),'signal'),
              'blend_orb15':(('sip_orb15',*COMPONENTS[2:]),'signal')})

def vw(history):
    volume=sum(b.volume for b in history)
    return sum((b.high+b.low+b.close)/3*b.volume for b in history)/volume if volume else None

def detect(history,name,context,stop_mode='signal'):
    if len(history)<2 or name not in COMPONENTS:
        return None
    c,p=history[-1],history[-2]
    clock=c.timestamp.astimezone(NY).time()
    vwap=vw(history)
    if c.close<=c.open or vwap is None or c.close<=vwap or clock>time(15):
        return None
    average=mean(b.volume for b in history[-13:-1])
    if average<=0 or c.volume<average:
        return None
    stop,reason,event=None,None,None
    if name in ('sip_orb5','sip_orb15'):
        end=time(9,35) if name=='sip_orb5' else time(9,45)
        opening=[b for b in history if time(9,35)<=b.timestamp.astimezone(NY).time()<=end]
        expected=1 if name=='sip_orb5' else 3
        if len(opening)!=expected or not end<clock<=time(11,30):
            return None
        high=max(b.high for b in opening)
        if any(b.close>high for b in history[:-1] if b.timestamp>opening[-1].timestamp):
            return None
        if c.close<=high or c.volume<1.5*average:
            return None
        stop=min(b.low for b in opening) if stop_mode=='range' else c.low
        reason='First completed opening-range break above VWAP; >=1.5x preceding volume'
        event=name+':'+opening[-1].timestamp.isoformat()
    elif name=='sip_pullback':
        if clock>time(11,30):
            return None
        for count in (2,3):
            i=len(history)-count-2
            if i<6:
                continue
            impulse=history[i]
            before=history[max(0,i-12):i]
            pause=history[i+1:-1]
            span=impulse.high-impulse.low
            if span<=0 or impulse.close<=max(b.high for b in before) or impulse.close-impulse.open<.65*span:
                continue
            if span<1.5*mean(b.high-b.low for b in before):
                continue
            support=max(max(b.high for b in before),impulse.high-.5*span)
            if pause[0].close>=impulse.close or any(b.low<support or b.high>impulse.high for b in pause):
                continue
            if any(pause[j].close>pause[j-1].high for j in range(1,len(pause))):
                continue
            if c.low<support or c.close<=p.high:
                continue
            stop=min(b.low for b in [*pause,c])
            reason='Strong impulse, first 2-3-bar defended pullback, close above preceding pullback high'
            event=name+':'+impulse.timestamp.isoformat()
            break
    elif name=='sip_vwap_bounce':
        if len(history)<12 or clock<time(10):
            return None
        pv=vw(history[:-1])
        earlier=vw(history[:-3])
        if pv is None or earlier is None or not vwap>earlier or p.close<pv:
            return None
        if not pv*.997<=p.low<=pv*1.003 or c.close<=p.high:
            return None
        if not all(b.close>vw(history[:i+1]) for i,b in enumerate(history[:-2]) if i>=len(history)-5):
            return None
        stop=min(p.low,c.low)
        reason='Above-VWAP trend pulls back within 0.3% of VWAP; rising VWAP and recovery above prior high'
        event=name+':'+p.timestamp.isoformat()
    elif name=='sip_vwap_reclaim':
        if len(history)<12 or clock<time(10) or p.close>vw(history[:-1]) or c.close<=p.high:
            return None
        stop=min(b.low for b in history[-3:])
        reason='Previous close below its prefix VWAP; current bullish close above VWAP and previous high'
        event=name+':'+p.timestamp.isoformat()
    elif name=='sip_gap_go':
        high=context.get('premarket_high')
        gap=context.get('gap')
        if high is None or gap is None or gap<.04 or not time(9,35)<clock<=time(10,30):
            return None
        if any(b.close>high for b in history[:-1]) or c.close<=high or c.volume<1.5*average:
            return None
        stop=min(b.low for b in history[-3:])
        reason='Gap >=4%, first completed premarket-high break above VWAP with volume expansion'
        event=name+':'+c.timestamp.astimezone(NY).date().isoformat()
    if stop is None or not 0<stop*.999<c.close:
        return None
    return {'stop':stop*.999,'reason':reason,'event':event}
