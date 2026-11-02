"""One-minute long-only stochastic trend scalper; independent of the 5m engine."""
import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from datetime import timedelta
from math import floor
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo
from .models import Bar

NY=ZoneInfo('America/New_York')
SOURCE='https://www.ig.com/en/trading-strategies/four-simple-scalping-trading-strategies-190131'

def oscillator(history):
    if len(history)<16:
        return None
    values=[]
    for end in range(len(history)-2,len(history)+1):
        window=history[end-14:end]
        low=min(b.low for b in window)
        high=max(b.high for b in window)
        if high<=low:
            return None
        values.append(100*(window[-1].close-low)/(high-low))
    return values[-1],mean(values)

def signal(history):
    if len(history)<23:
        return None
    c=history[-1]
    clock=c.timestamp.astimezone(NY).strftime('%H:%M')
    if not '09:45'<=clock<='15:30' or not 1<=c.close<=35:
        return None
    now,previous=oscillator(history),oscillator(history[:-1])
    trend=mean(b.close for b in history[-20:])
    old=mean(b.close for b in history[-23:-3])
    if not now or not previous or not c.close>trend>old:
        return None
    if previous[0]>previous[1] or now[0]<=now[1] or min(previous[0],now[0])>20:
        return None
    if mean(b.close*b.volume for b in history[-12:])<10000:
        return None
    stop=min(b.low for b in history[-3:])*.999
    return {'stop':stop,'score':100-now[0]} if 0<stop<c.close else None

def exit_signal(history):
    now,previous=oscillator(history),oscillator(history[:-1])
    return bool(now and (now[0]>=80 or previous and previous[0]>=previous[1] and now[0]<now[1]))

def replay(bars,closes,allocation=300.,cost_multiple=1,signal_fn=None):
    if allocation not in (250.,300.) or cost_multiple not in (1,2):
        raise ValueError('Allocation 250/300; cost multiple 1/2 only')
    choose=signal if signal_fn is None else signal_fn
    grouped=defaultdict(list)
    seen=set()
    for b in bars:
        if (b.symbol,b.timestamp) in seen or b.volume<=0 or b.timestamp.second or b.timestamp.microsecond:
            raise ValueError('Duplicate, zero-volume or unaligned one-minute bars')
        seen.add((b.symbol,b.timestamp))
        day=b.timestamp.astimezone(NY).date().isoformat()
        if day not in closes or b.timestamp>closes[day]:
            raise ValueError('Missing calendar or after-close candle')
        grouped[b.timestamp].append(b)
    cash=2000.
    histories,positions,pending,last={}, {}, {}, {}
    trades,curve,rejections=[],[],[]
    haircut=(50/20000+25/10000)*cost_multiple
    peak=cash
    drawdown=0.
    def finish(symbol,raw,stamp,reason):
        nonlocal cash
        p=positions.pop(symbol)
        price=raw*(1-haircut)
        pnl=p['shares']*(price-p['entry'])
        cash+=p['shares']*price
        gross=p['shares']*(raw-p['raw_entry'])
        costs=p['shares']*(raw+p['raw_entry'])*haircut
        trades.append({'symbol':symbol,'strategy':'stochastic_trend_scalp','signal_time':p['signal_time'].isoformat(),'entry_time':p['entry_time'].isoformat(),'exit_time_upper_bound':stamp.isoformat(),'raw_entry':p['raw_entry'],'raw_exit':raw,'entry':p['entry'],'exit':price,'shares':p['shares'],'stop':p['stop'],'planned_risk':p['risk'],'net_pnl':pnl,'gross_pnl':gross,'modeled_cost':costs,'reconciliation_error':pnl-(gross-costs),'hold_minutes_upper_bound':(stamp-p['entry_time']).total_seconds()/60,'exit_reason':reason})
    for stamp,batch in sorted(grouped.items()):
        current={b.symbol:b for b in batch}
        for symbol,p in list(positions.items()):
            b=current.get(symbol)
            if b is None or stamp-last[symbol]!=timedelta(minutes=1):
                raise ValueError('Unresolved one-minute gap while position open')
            if p.get('exit_pending'):
                finish(symbol,b.open,stamp-timedelta(minutes=1),'oscillator_next_open')
        waiting,pending=pending,{}
        for symbol,s in sorted(waiting.items(),key=lambda item:(-item[1]['score'],item[0])):
            b=current.get(symbol)
            if b is None or stamp-s['stamp']!=timedelta(minutes=1):
                rejections.append({'symbol':symbol,'timestamp':stamp.isoformat(),'reason':'missing_next_bar'})
                continue
            if symbol in positions or not 1<=b.open<=35 or b.open<=s['stop']:
                continue
            entry=b.open*(1+haircut)
            per_share=entry-s['stop']*(1-haircut)
            shares=floor(min(allocation/entry,cash/entry,20/per_share,s['volume']*.01)) if per_share>0 else 0
            if shares<1:
                rejections.append({'symbol':symbol,'timestamp':stamp.isoformat(),'reason':'cash_risk_or_prior_volume_limit'})
                continue
            cash-=shares*entry
            positions[symbol]={'entry':entry,'raw_entry':b.open,'shares':shares,'stop':s['stop'],'risk':shares*per_share,'signal_time':s['stamp'],'entry_time':stamp-timedelta(minutes=1)}
        for b in sorted(batch,key=lambda b:b.symbol):
            day=stamp.astimezone(NY).date().isoformat()
            p=positions.get(b.symbol)
            if p:
                if b.open<=p['stop']:
                    finish(b.symbol,b.open,stamp-timedelta(minutes=1),'gap_stop')
                elif b.low<=p['stop']:
                    finish(b.symbol,p['stop'],stamp,'stop')
                elif stamp>=closes[day]:
                    finish(b.symbol,b.close,stamp,'session_end')
                elif stamp-p['entry_time']>=timedelta(minutes=5):
                    finish(b.symbol,b.close,stamp,'five_minute_limit')
            key=(day,b.symbol)
            history=histories.setdefault(key,[])
            if history and stamp-history[-1].timestamp!=timedelta(minutes=1):
                history.clear()
            history.append(b)
            last[b.symbol]=stamp
            if b.symbol in positions:
                if exit_signal(history):
                    positions[b.symbol]['exit_pending']=True
            elif stamp<closes[day]:
                found=choose(history)
                if found:
                    pending[b.symbol]={**found,'stamp':stamp,'volume':b.volume}
        equity=cash+sum(p['shares']*current[symbol].close*(1-haircut) for symbol,p in positions.items())
        peak=max(peak,equity)
        drawdown=max(drawdown,(peak-equity)/peak)
        curve.append({'timestamp':stamp.isoformat(),'equity':equity,'cash':cash,'open_positions':len(positions)})
    if positions:
        raise ValueError('Missing session liquidation; no fabricated exit')
    return {'summary':{'starting_equity':2000.,'ending_equity':cash,'net_pnl':cash-2000,'trades':len(trades),'max_drawdown':drawdown},'trades':trades,'equity':curve,'rejections':rejections,'settings':{'interval':'1m','allocation':allocation,'risk_per_position':20,'cost_multiple':cost_multiple,'spread_bps':50*cost_multiple,'slippage_bps':25*cost_multiple,'maximum_hold_minutes':5,'source':SOURCE}}

def main():
    import pandas as pd
    import pandas_market_calendars as mcal
    import yfinance as yf
    from .yahoo_pilot import classify
    parser=argparse.ArgumentParser()
    parser.add_argument('--symbols',required=True)
    parser.add_argument('--allocation',type=float,choices=(250.,300.),default=300.)
    parser.add_argument('--output',default='results/stochastic-scalper')
    args=parser.parse_args()
    symbols=list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(',') if s.strip()))
    if not 1<=len(symbols)<=25:
        parser.error('Provide 1-25 fixed stock symbols')
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    audit={'source':SOURCE,'requested_interval':'1m','requested_period':'7d','coverage':[],'hashes':{}}
    bars,closes=[],{}
    now=pd.Timestamp.now(tz='UTC')
    for symbol in symbols:
        try:
            ticker=yf.Ticker(symbol)
            info=ticker.get_info()
            if classify(info)[0]!='listed' or info.get('currency')!='USD' or info.get('quoteType')!='EQUITY':
                raise ValueError('Require verified listed USD equity')
            frame=ticker.history(period='7d',interval='1m',prepost=False,auto_adjust=False,back_adjust=False,actions=True,raise_errors=True)
            if frame.empty or frame.index.tz is None or frame.index.has_duplicates:
                raise ValueError('Missing/duplicate aware one-minute history')
            frame=frame.sort_index()
            safe=''.join(c for c in symbol if c.isalnum() or c in '-_.')
            path=out/('history-'+safe+'.csv')
            frame.to_csv(path)
            audit['hashes'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            schedule=mcal.get_calendar('NYSE').schedule(start_date=frame.index.min().date(),end_date=frame.index.max().date())
            for _,session in schedule.iterrows():
                day=session.market_open.date().isoformat()
                if session.market_close>now:
                    audit['coverage'].append({'symbol':symbol,'day':day,'status':'incomplete_current_session'})
                    continue
                piece=frame[(frame.index>=session.market_open)&(frame.index<session.market_close)]
                expected=pd.date_range(session.market_open,session.market_close,freq='1min',inclusive='left').tz_convert('UTC')
                action=any(col in piece and (piece[col].fillna(0)!=0).any() for col in ('Dividends','Stock Splits'))
                valid=piece.index.tz_convert('UTC').equals(expected) and piece[['Open','High','Low','Close','Volume']].notna().all().all() and (piece[['Open','High','Low','Close','Volume']]>0).all().all()
                if action or not valid:
                    audit['coverage'].append({'symbol':symbol,'day':day,'status':'action_or_incomplete_session'})
                    continue
                prepared=[Bar(symbol,(stamp+pd.Timedelta(minutes=1)).to_pydatetime(),*[float(r[c]) for c in ('Open','High','Low','Close','Volume')]) for stamp,r in piece.iterrows()]
                bars.extend(prepared)
                closes[day]=session.market_close.to_pydatetime()
                audit['coverage'].append({'symbol':symbol,'day':day,'status':'eligible','bars':len(prepared)})
        except Exception as exc:
            audit['coverage'].append({'symbol':symbol,'status':'unavailable','reason':str(exc)})
    (out/'coverage.json').write_text(json.dumps(audit,indent=2))
    lines=['# One-minute stochastic scalper','',f'Source: {SOURCE}','','Shared USD 2,000 stock portfolio. USD 1-35, oversold stochastic cross in a rising SMA20 trend, quick oscillator exits, stop and five-minute limit.']
    if not bars:
        lines+=['','No eligible one-minute sample; inspect coverage.json. No backtest generated.']
    else:
        lines+=['','| Cost | Trades | Net P&L | Ending equity | Drawdown |','|---|---:|---:|---:|---:|']
        for cost in (1,2):
            result=replay(bars,closes,args.allocation,cost)
            folder=out/f'cost{cost}'
            folder.mkdir(exist_ok=True)
            (folder/'run.json').write_text(json.dumps(result,indent=2,allow_nan=False))
            for key in ('trades','equity','rejections'):
                rows=result[key]
                with (folder/(key+'.csv')).open('w',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['status'])
                    writer.writeheader()
                    writer.writerows(rows)
            r=result['summary']
            lines.append(f"| {cost} | {r['trades']} | {r['net_pnl']:.2f} | {r['ending_equity']:.2f} | {r['max_drawdown']:.2%} |")
    text='\n'.join(lines)+'\n'
    (out/'SUMMARY.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(text)

if __name__=='__main__':
    main()
