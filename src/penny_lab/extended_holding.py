"""Stochastic entries with overnight holding and a 45-calendar-day maximum."""
import argparse
import csv
import hashlib
import json
import os
import time
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime,timedelta
from math import floor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .models import Bar
from .stochastic_scalper import signal,exit_signal,NY


def replay(bars,sessions,allocation=300.,cost_multiple=1,hold_days=45,fast_exits=False,signal_fn=None):
    if allocation not in (250.,300.) or cost_multiple not in (1,2) or not 1<=hold_days<=45:
        raise ValueError('Invalid allocation, cost multiple or holding period')
    choose=signal if signal_fn is None else signal_fn
    calendar=sorted(sessions.values(),key=lambda s:s['open'])
    openings=[s['open'] for s in calendar]
    def expected_after(stamp):
        day=stamp.astimezone(NY).date().isoformat()
        if stamp<sessions[day]['close']:
            return stamp+timedelta(minutes=1)
        i=bisect_right(openings,stamp)
        return calendar[i]['open']+timedelta(minutes=1) if i<len(calendar) else None
    events=defaultdict(list)
    seen=set()
    for b in bars:
        day=b.timestamp.astimezone(NY).date().isoformat()
        session=sessions.get(day)
        if not session or not session['open']<b.timestamp<=session['close'] or b.volume<=0 or b.timestamp.second or b.timestamp.microsecond or (b.symbol,b.timestamp) in seen:
            raise ValueError('Invalid regular-session minute bar')
        seen.add((b.symbol,b.timestamp))
        events[b.timestamp].append(b)
    cash=2000.
    positions,pending,histories,last,marks={}, {}, {}, {}, {}
    trades,curve,rejections=[],[],[]
    haircut=.005*cost_multiple
    peak=cash
    drawdown=0.
    def finish(symbol,raw,stamp,reason):
        nonlocal cash
        p=positions.pop(symbol)
        price=raw*(1-haircut)
        cash+=p['shares']*price
        pnl=p['shares']*(price-p['entry'])
        gross=p['shares']*(raw-p['raw_entry'])
        costs=p['shares']*(raw+p['raw_entry'])*haircut
        trades.append({'symbol':symbol,'entry_time':p['entry_time'].isoformat(),'exit_time_upper_bound':stamp.isoformat(),'shares':p['shares'],'entry':p['entry'],'exit':price,'stop':p['stop'],'planned_risk':p['risk'],'gross_pnl':gross,'modeled_cost':costs,'net_pnl':pnl,'reconciliation_error':pnl-(gross-costs),'holding_calendar_days':(stamp-p['entry_time']).total_seconds()/86400,'exit_reason':reason})
    for stamp,batch in sorted(events.items()):
        current={b.symbol:b for b in batch}
        for symbol,p in list(positions.items()):
            due=expected_after(last[symbol])
            if due is None or stamp<due:
                continue
            if symbol not in current or stamp!=due:
                raise ValueError('Missing expected trading minute while holding '+symbol)
            b=current[symbol]
            opened=stamp-timedelta(minutes=1)
            if b.open<=p['stop']:
                finish(symbol,b.open,opened,'gap_stop')
            elif opened>=p['deadline']:
                finish(symbol,b.open,opened,'holding_limit')
            elif p.get('exit_pending'):
                finish(symbol,b.open,opened,'oscillator_next_open')
        waiting,pending=pending,{}
        for symbol,s in sorted(waiting.items(),key=lambda item:(-item[1]['score'],item[0])):
            b=current.get(symbol)
            if not b or stamp-s['stamp']!=timedelta(minutes=1):
                rejections.append({'symbol':symbol,'timestamp':stamp.isoformat(),'reason':'missing_next_bar'})
                continue
            if symbol in positions or not 1<=b.open<=35 or b.open<=s['stop']:
                continue
            entry=b.open*(1+haircut)
            risk=entry-s['stop']*(1-haircut)
            shares=floor(min(allocation/entry,cash/entry,20/risk,s['volume']*.01)) if risk>0 else 0
            if shares<1:
                rejections.append({'symbol':symbol,'timestamp':stamp.isoformat(),'reason':'cash_risk_or_volume'})
                continue
            entered=stamp-timedelta(minutes=1)
            cash-=shares*entry
            positions[symbol]={'entry_time':entered,'deadline':entered+timedelta(days=hold_days),'raw_entry':b.open,'entry':entry,'stop':s['stop'],'shares':shares,'risk':shares*risk}
        for b in sorted(batch,key=lambda b:b.symbol):
            if b.symbol in positions and b.low<=positions[b.symbol]['stop']:
                finish(b.symbol,positions[b.symbol]['stop'],stamp,'stop')
            day=stamp.astimezone(NY).date().isoformat()
            h=histories.setdefault((b.symbol,day),[])
            if h and stamp-h[-1].timestamp!=timedelta(minutes=1):
                h.clear()
            h.append(b)
            last[b.symbol]=stamp
            marks[b.symbol]=b.close
            if b.symbol in positions:
                if fast_exits and exit_signal(h):
                    positions[b.symbol]['exit_pending']=True
            elif stamp<sessions[day]['close']:
                found=choose(h)
                if found:
                    pending[b.symbol]={**found,'stamp':stamp,'volume':b.volume}
        equity=cash+sum(p['shares']*marks[s]*(1-haircut) for s,p in positions.items())
        peak=max(peak,equity)
        drawdown=max(drawdown,(peak-equity)/peak)
        curve.append({'timestamp':stamp.isoformat(),'equity':equity,'cash':cash,'open_positions':len(positions)})
    final=curve[-1]['equity'] if curve else cash
    realized=sum(t['net_pnl'] for t in trades)
    open_rows=[{'symbol':s,'entry_time':p['entry_time'].isoformat(),'deadline':p['deadline'].isoformat(),'shares':p['shares'],'entry':p['entry'],'last_raw_price':marks[s],'marked_value':p['shares']*marks[s]*(1-haircut),'unrealized_pnl':p['shares']*(marks[s]*(1-haircut)-p['entry'])} for s,p in positions.items()]
    if abs(final-2000-realized-sum(p['unrealized_pnl'] for p in open_rows))>1e-7:
        raise ValueError('Equity reconciliation failed')
    return {'summary':{'starting_equity':2000.,'final_equity':final,'ending_equity':final,'final_cash':cash,'net_pnl':final-2000,'return_percentage':(final/2000-1)*100,'realized_pnl':realized,'unrealized_pnl':final-2000-realized,'closed_trades':len(trades),'open_positions':len(open_rows),'max_drawdown':drawdown},'trades':trades,'open_positions':open_rows,'equity':curve,'rejections':rejections,'settings':{'maximum_hold_calendar_days':hold_days,'overnight_allowed':True,'fast_oscillator_exits':fast_exits,'allocation':allocation,'risk_per_position':20,'spread_bps':50*cost_multiple,'slippage_bps':25*cost_multiple,'final_equity_basis':'cash plus cost-adjusted marks; no forced final sale'}}


def alpaca_rows(symbol,start,end,feed):
    key,secret=os.environ.get('ALPACA_API_KEY'),os.environ.get('ALPACA_SECRET_KEY')
    if not key or not secret:
        raise ValueError('ALPACA_API_KEY and ALPACA_SECRET_KEY required for extended one-minute history')
    params={'symbols':symbol,'timeframe':'1Min','start':start,'end':end,'feed':feed,'adjustment':'raw','limit':10000,'sort':'asc'}
    rows,tokens=[],set()
    while True:
        request=Request('https://data.alpaca.markets/v2/stocks/bars?'+urlencode(params),headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret})
        for attempt in range(4):
            try:
                with urlopen(request,timeout=60) as response:
                    result=json.load(response)
                break
            except HTTPError as exc:
                if exc.code not in (429,500,502,503,504) or attempt==3:
                    raise ValueError('Historical data HTTP '+str(exc.code)) from None
                time.sleep(2**attempt)
        rows.extend(result.get('bars',{}).get(symbol,[]))
        token=result.get('next_page_token')
        if not token:
            return rows
        if token in tokens:
            raise ValueError('Repeated historical data page token')
        tokens.add(token)
        params['page_token']=token


def summary_text(results):
    lines=['# Stochastic entries with up to 45-day holding','','| Cost multiple | Starting equity | Final equity | Net P&L | Return | Closed trades | Open positions |','|---|---:|---:|---:|---:|---:|---:|']
    for cost,result in results:
        r=result['summary']
        lines.append(f"| {cost} | {r['starting_equity']:.2f} | {r['final_equity']:.2f} | {r['net_pnl']:.2f} | {r['return_percentage']:.2f}% | {r['closed_trades']} | {r['open_positions']} |")
    lines+=['','Final equity includes cost-adjusted open-position marks. Stops can exit earlier. The 45-day deadline exits at the first available regular-session open at/after expiry.']
    return '\n'.join(lines)+'\n'


def main():
    import pandas as pd
    import pandas_market_calendars as mcal
    import yfinance as yf
    from .yahoo_pilot import classify
    parser=argparse.ArgumentParser()
    parser.add_argument('--symbols',required=True)
    parser.add_argument('--allocation',type=float,choices=(250.,300.),default=300.)
    parser.add_argument('--history-days',type=int,default=90)
    parser.add_argument('--hold-days',type=int,default=45)
    parser.add_argument('--feed',choices=('sip','iex'),default='sip')
    parser.add_argument('--fast-exits',action='store_true')
    parser.add_argument('--output',default='results/extended-holding')
    args=parser.parse_args()
    symbols=list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(',') if s.strip()))
    if not 1<=len(symbols)<=25 or not 1<=args.hold_days<=45 or not args.hold_days<args.history_days<=365:
        parser.error('Require 1-25 symbols; hold_days 1-45; history_days > hold_days and <=365')
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    end=pd.Timestamp.now(tz=NY).normalize()
    start=end-pd.Timedelta(days=args.history_days)
    schedule=mcal.get_calendar('NYSE').schedule(start_date=start.date(),end_date=(end-pd.Timedelta(days=1)).date())
    sessions={s.market_open.date().isoformat():{'open':s.market_open.to_pydatetime(),'close':s.market_close.to_pydatetime()} for _,s in schedule.iterrows()}
    audit={'start':start.isoformat(),'end_exclusive':end.isoformat(),'provider':'Alpaca','feed':args.feed,'interval':'1Min','coverage':[],'hashes':{}}
    bars=[]
    for symbol in symbols:
        try:
            ticker=yf.Ticker(symbol)
            info=ticker.get_info()
            if classify(info)[0]!='listed' or info.get('quoteType')!='EQUITY' or info.get('currency')!='USD':
                raise ValueError('Require verified listed USD equity')
            actions=ticker.history(start=start,end=end,interval='1d',auto_adjust=False,actions=True,raise_errors=True)
            if actions.empty or not {'Dividends','Stock Splits'}<=set(actions):
                raise ValueError('Corporate-action history unavailable')
            if (actions[['Dividends','Stock Splits']].fillna(0)!=0).any().any():
                raise ValueError('Corporate action in holding window; raw-price overnight replay excluded')
            rows=alpaca_rows(symbol,start.isoformat(),end.isoformat(),args.feed)
            safe=''.join(c for c in symbol if c.isalnum() or c in '-_.')
            path=out/('history-'+safe+'.json')
            path.write_text(json.dumps(rows))
            audit['hashes'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            if not rows:
                raise ValueError('No one-minute bars returned')
            frame=pd.DataFrame(rows)
            frame.index=pd.to_datetime(frame['t'],utc=True)
            frame=frame.sort_index()
            if frame.index.has_duplicates:
                raise ValueError('Duplicate minute bars')
            prepared=[]
            for day,session in sessions.items():
                piece=frame[(frame.index>=session['open'])&(frame.index<session['close'])]
                expected=pd.date_range(session['open'],session['close'],freq='1min',inclusive='left')
                if not piece.index.equals(expected) or piece[['o','h','l','c','v']].isna().any().any() or not (piece[['o','h','l','c','v']]>0).all().all():
                    raise ValueError('Incomplete/nonpositive session '+day+'; symbol excluded across entire holding window')
                prepared.extend(Bar(symbol,(stamp+pd.Timedelta(minutes=1)).to_pydatetime(),*[float(r[c]) for c in ('o','h','l','c','v')]) for stamp,r in piece.iterrows())
            bars.extend(prepared)
            audit['coverage'].append({'symbol':symbol,'status':'eligible','bars':len(prepared)})
        except Exception as exc:
            audit['coverage'].append({'symbol':symbol,'status':'unavailable','reason':str(exc)})
    (out/'coverage.json').write_text(json.dumps(audit,indent=2))
    results=[]
    if bars:
        for cost in (1,2):
            result=replay(bars,sessions,args.allocation,cost,args.hold_days,args.fast_exits)
            folder=out/f'cost{cost}'
            folder.mkdir(exist_ok=True)
            (folder/'run.json').write_text(json.dumps(result,indent=2,allow_nan=False))
            for name in ('trades','equity','rejections','open_positions'):
                rows=result[name]
                with (folder/(name+'.csv')).open('w',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['status'])
                    writer.writeheader()
                    writer.writerows(rows)
            results.append((cost,result))
        text=summary_text(results)
    else:
        text='# Extended holding\n\nStarting equity: USD 2,000. Final equity: unavailable; no eligible sample. See coverage.json.\n'
    (out/'SUMMARY.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(text)

if __name__=='__main__':
    main()
