"""Alternative experimental families; no performance or optimality claim."""
from datetime import time
from statistics import mean,pstdev
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
CASES={
 'ema_trend':('ema_trend_cross',),
 'bollinger_rsi':('bollinger_rsi_reentry',),
 'double_bottom':('double_bottom_neckline',),
 'trend_reversion_mix':('ema_trend_cross','bollinger_rsi_reentry'),
 'three_family_mix':('ema_trend_cross','bollinger_rsi_reentry','double_bottom_neckline')}

def names_at(case,stamp):
    return CASES[case]

def ema(values,period):
    if not values:
        return []
    output=[float(values[0])]
    alpha=2/(period+1)
    for value in values[1:]:
        output.append(alpha*value+(1-alpha)*output[-1])
    return output

def rsi(values,period=14):
    if len(values)<period+1:
        return None
    changes=[b-a for a,b in zip(values[-period-1:-1],values[-period:])]
    gains=sum(max(v,0) for v in changes)
    losses=-sum(min(v,0) for v in changes)
    if gains==losses==0:
        return 50.
    if losses==0:
        return 100.
    return 100-100/(1+gains/losses)

def pattern(history,name):
    if len(history)<20 or history[-1].timestamp.astimezone(NY).time()>time(15):
        return None
    current,previous=history[-1],history[-2]
    if current.close<=current.open:
        return None
    closes=[b.close for b in history]
    average=mean(b.volume for b in history[-13:-1])
    if average<=0:
        return None
    if name=='ema_trend_cross':
        if len(history)<35:
            return None
        fast,slow,trend=ema(closes,8),ema(closes,21),ema(closes,34)
        if fast[-2]<=slow[-2] and fast[-1]>slow[-1] and current.close>trend[-1]>trend[-4] and current.volume>=average:
            return {'stop':min(b.low for b in history[-5:])*.999,'reason':'EMA8 crosses EMA21 from below; close above rising EMA34; volume >= preceding mean'}
    elif name=='bollinger_rsi_reentry':
        if len(history)<24:
            return None
        old=closes[-21:-1]
        new=closes[-20:]
        old_lower=mean(old)-2*pstdev(old)
        new_lower=mean(new)-2*pstdev(new)
        old_rsi,new_rsi=rsi(closes[:-1]),rsi(closes)
        trend=ema(closes,21)
        flat=abs(trend[-1]/trend[-4]-1)<=.003
        if flat and previous.close<old_lower and current.close>new_lower and old_rsi is not None and new_rsi is not None and old_rsi<=35 and new_rsi>old_rsi:
            return {'stop':min(previous.low,current.low)*.999,'reason':'Close re-enters 20-bar lower Bollinger band after oversold RSI14; RSI improving; EMA21 slope <=0.3% over three bars'}
    elif name=='double_bottom_neckline':
        base=history[-25:-1]
        lows=[i for i in range(2,len(base)-2) if base[i].low<min(b.low for b in base[i-2:i]+base[i+1:i+3])]
        for second in reversed(lows):
            for first in reversed([i for i in lows if 3<=second-i<=12]):
                a,b=base[first],base[second]
                if abs(a.low-b.low)/min(a.low,b.low)>.0075:
                    continue
                neckline=max(x.high for x in base[first+1:second])
                if previous.close<=neckline<current.close and current.volume>=1.25*average:
                    return {'stop':min(a.low,b.low)*.999,'reason':'Two confirmed lows within 0.75%, separated 3-12 bars; neckline close breakout with >=1.25x preceding mean volume'}
    return None
