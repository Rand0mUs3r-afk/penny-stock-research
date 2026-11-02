"""Hash-checked regular sessions plus optional historical extended-hours inputs."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')

def news_events(path):
    import csv
    events=[]
    if not path:
        return events
    with Path(path).open(newline='') as f:
        for row in csv.DictReader(f):
            stamp=datetime.fromisoformat(row['published_at'].replace('Z','+00:00'))
            if stamp.utcoffset() is None or not row.get('source') or not row.get('headline'):
                raise ValueError('Catalysts require aware published_at, source and headline')
            events.append({**row,'symbol':row['symbol'].upper(),'published_at':stamp})
    return events

def read_frame(path,expected):
    import pandas as pd
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('Price hash mismatch: '+path.name)
    frame=pd.read_csv(path,index_col=0)
    frame.index=pd.to_datetime(frame.index,utc=True)
    if frame.index.has_duplicates:
        raise ValueError('Duplicate price bars')
    return frame.sort_index()

def contexts(source,symbols):
    import pandas as pd
    import pandas_market_calendars as mcal
    from .quality import inspect_session
    hashes=json.loads((source/'input-hashes.json').read_text())
    coverage=json.loads((source/'coverage.json').read_text())
    extra=json.loads((source/'sip-inputs.json').read_text()) if (source/'sip-inputs.json').exists() else {'hashes':{}}
    actions={r['symbol']:{a['day'] for a in r.get('actions',[])} for r in coverage['coverage']}
    output={}
    for symbol in symbols:
        safe=''.join(c for c in symbol if c.isalnum() or c in '-_.')
        frame=read_frame(source/('history-'+safe+'.csv'),hashes[symbol])
        filename='extended-'+safe+'.csv'
        extended=read_frame(source/filename,extra['hashes'][filename]) if filename in extra.get('hashes',{}) else None
        schedule=mcal.get_calendar('NYSE').schedule(start_date=frame.index.min().date(),end_date=frame.index.max().date())
        previous=None
        for _,session in schedule.iterrows():
            day=session.market_open.date().isoformat()
            context={'previous_close':previous,'premarket_high':None,'premarket_volume':None,'premarket_status':'unavailable'}
            if day in actions.get(symbol,set()):
                context['previous_close']=None
            if extended is not None and day not in actions.get(symbol,set()):
                begin=pd.Timestamp(day+' 04:00',tz=NY)
                pre=extended[(extended.index>=begin)&(extended.index<session.market_open)]
                if not pre.empty and all(c in pre for c in ('Open','High','Low','Close','Volume')) and (pre[['Open','High','Low','Close']]>0).all().all() and (pre.Volume>=0).all() and pre[['Open','High','Low','Close','Volume']].notna().all().all() and (pre.Volume>0).any():
                    context.update(premarket_high=float(pre.High.max()),premarket_volume=float(pre.Volume.sum()),premarket_status='provider_reported_0400_0930')
            output[(symbol,day)]=context
            piece=frame[(frame.index>=session.market_open)&(frame.index<session.market_close)]
            expected=pd.date_range(session.market_open,session.market_close,freq='5min',inclusive='left')
            previous=float(piece.Close.iloc[-1]) if inspect_session(piece,expected)=='usable' and day not in actions.get(symbol,set()) else None
    return output

def acquire_extras(source,premarket=True,benchmark=True):
    import yfinance as yf
    coverage=json.loads((source/'coverage.json').read_text())
    universe=json.loads((source/'universe.json').read_text())
    audit={'hashes':{},'attempts':[],'benchmark_actions':[]}
    requested=[(s,True,'extended-') for s in universe['symbols']] if premarket else []
    if benchmark:
        requested.append(('SPY',False,'benchmark-'))
    for symbol,extended,prefix in requested:
        try:
            ticker=yf.Ticker(symbol)
            frame=ticker.history(start=coverage['download_start'],end=coverage['evaluation_end_exclusive'],interval='5m',prepost=extended,auto_adjust=False,back_adjust=False,actions=True,raise_errors=True)
            if frame.empty or frame.index.tz is None:
                raise ValueError('Missing aware extended/benchmark bars')
            safe=''.join(c for c in symbol if c.isalnum() or c in '-_.')
            filename=prefix+safe+'.csv'
            frame.to_csv(source/filename)
            audit['hashes'][filename]=hashlib.sha256((source/filename).read_bytes()).hexdigest()
            if not extended:
                for col in ('Dividends','Stock Splits'):
                    if col in frame:
                        audit['benchmark_actions']+=sorted({stamp.date().isoformat() for stamp,value in frame[col].items() if value!=0})
            audit['attempts'].append({'symbol':symbol,'extended':extended,'status':'saved','file':filename})
        except Exception as exc:
            audit['attempts'].append({'symbol':symbol,'extended':extended,'status':'unavailable','reason':str(exc)})
    (source/'sip-inputs.json').write_text(json.dumps(audit,indent=2,allow_nan=False))

def benchmark_bars(source):
    import pandas as pd
    import pandas_market_calendars as mcal
    from .models import Bar
    from .quality import inspect_session
    audit=json.loads((source/'sip-inputs.json').read_text())
    filename='benchmark-SPY.csv'
    if filename not in audit['hashes']:
        return [],{},audit.get('benchmark_actions',[])
    frame=read_frame(source/filename,audit['hashes'][filename])
    schedule=mcal.get_calendar('NYSE').schedule(start_date=frame.index.min().date(),end_date=frame.index.max().date())
    bars,closes=[],{}
    for _,session in schedule.iterrows():
        day=session.market_open.date().isoformat()
        piece=frame[(frame.index>=session.market_open)&(frame.index<session.market_close)]
        expected=pd.date_range(session.market_open,session.market_close,freq='5min',inclusive='left')
        if inspect_session(piece,expected)!='usable':
            audit.setdefault('benchmark_actions',[]).append(day)
            continue
        closes[day]=session.market_close.tz_convert(NY).strftime('%H:%M')
        bars.extend(Bar('SPY',(stamp+pd.Timedelta(minutes=5)).to_pydatetime(),*[float(r[c]) for c in ('Open','High','Low','Close','Volume')]) for stamp,r in piece.iterrows())
    return bars,closes,audit.get('benchmark_actions',[])
