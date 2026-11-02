"""Time-of-day RVOL ranking using saved historical prefixes, not daily volume."""
from collections import defaultdict
from math import isfinite
from statistics import mean
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')

def catalyst_present(events,symbol,stamp):
    return any(e['symbol']==symbol and e['published_at']<=stamp and
               e['published_at'].astimezone(NY).date()==stamp.astimezone(NY).date() for e in events)

def make_selection(bars,references,contexts,top_n=20,minimum_rvol=2.,require_catalyst=False,events=()):
    if top_n<1 or not isfinite(minimum_rvol) or minimum_rvol<=0:
        raise ValueError('Invalid selection thresholds')
    grouped=defaultdict(list)
    for b in bars:
        grouped[b.timestamp].append(b)
    histories=defaultdict(list)
    features,decisions={},[]
    for stamp,batch in sorted(grouped.items()):
        ranked=[]
        for b in sorted(batch,key=lambda b:b.symbol):
            day=stamp.astimezone(NY).date().isoformat()
            history=histories[(b.symbol,day)]
            history.append(b)
            denominator=references.get((b.symbol,day,stamp.astimezone(NY).strftime('%H:%M')))
            ratio=sum(x.volume for x in history)/denominator if denominator and denominator>0 else None
            ctx=dict(contexts.get((b.symbol,day),{}))
            previous=ctx.get('previous_close')
            ctx.update(gap=history[0].open/previous-1 if previous and previous>0 else None,
                       rvol=ratio,catalyst=catalyst_present(events,b.symbol,stamp))
            valid=1<=b.close<=35 and mean(x.close*x.volume for x in history[-12:])>=10000
            if require_catalyst and not ctx['catalyst']:
                valid=False
            ctx['unfiltered_eligible']=valid
            ctx['rank']=None
            ctx['stocks_in_play_eligible']=False
            features[(b.symbol,stamp)]=ctx
            if valid and ratio is not None and ratio>=minimum_rvol:
                ranked.append((ratio,b.symbol))
        ranked.sort(key=lambda x:(-x[0],x[1]))
        for rank,(_,symbol) in enumerate(ranked,1):
            ctx=features[(symbol,stamp)]
            ctx['rank']=rank
            ctx['stocks_in_play_eligible']=rank<=top_n
        for b in batch:
            ctx=features[(b.symbol,stamp)]
            reason='selected' if ctx['stocks_in_play_eligible'] else ('price_liquidity_or_catalyst' if not ctx['unfiltered_eligible'] else 'missing_rvol_reference' if ctx['rvol'] is None else 'rvol_below_threshold' if ctx['rvol']<minimum_rvol else 'outside_top_n')
            decisions.append({'symbol':b.symbol,'timestamp':stamp.isoformat(),'rvol':ctx['rvol'],'rank':ctx['rank'],'gap':ctx['gap'],'catalyst':ctx['catalyst'],'premarket_available':ctx.get('premarket_high') is not None,'reason':reason})
    return features,decisions
