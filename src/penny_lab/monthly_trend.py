"""Monthly ten-month trend allocation on normalized total-return ETF units."""
import argparse
import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date,timedelta
from math import isfinite
from pathlib import Path
from statistics import mean

DEFAULT_SYMBOLS='SPY,EFA,IEF,VNQ,DBC'
PROFILES=('trend','buy_hold','trend_45_capped','buy_hold_capped')

@dataclass(frozen=True)
class Daily:
    day: str
    open: float
    high: float
    low: float
    close: float
    def __post_init__(self):
        date.fromisoformat(self.day)
        if not all(isfinite(x) and x>0 for x in (self.open,self.high,self.low,self.close)) or self.high<max(self.open,self.close) or self.low>min(self.open,self.close):
            raise ValueError('Invalid adjusted daily unit OHLC')

def month_signals(bars,month_ends):
    closes=[]
    output={}
    for b in sorted(bars,key=lambda b:b.day):
        if b.day in month_ends:
            closes.append(b.close)
            if len(closes)>=10:
                output[b.day]=b.close>mean(closes[-10:])
    return output

def partitions(days,boundary=''):
    days=sorted(set(days))
    if boundary:
        boundary=date.fromisoformat(boundary).isoformat()
        result={'earlier':[d for d in days if d<boundary],'declared_later':[d for d in days if d>=boundary]}
        if not all(result.values()):
            raise ValueError('Boundary must leave observations on both sides')
        return result
    cut=int(len(days)*.7)
    return {'full':days,'earlier':days[:cut],'later':days[cut:]} if len(days)>=20 else {'full':days}

def replay(data,days,month_ends,profile='trend',spread_bps=50.,slippage_bps=25.,cost_multiple=1):
    if profile not in PROFILES or cost_multiple not in (1,2) or not days:
        raise ValueError('Invalid profile, costs or evaluation dates')
    if not all(isfinite(x) and x>=0 for x in (spread_bps,slippage_bps)):
        raise ValueError('Costs must be finite and nonnegative')
    rate=(spread_bps/20000+slippage_bps/10000)*cost_multiple
    if rate>=1:
        raise ValueError('Cost rate must be below 100%')
    symbols=sorted(data)
    if not symbols:
        raise ValueError('No assets')
    lookup={}
    signals={}
    for symbol,items in data.items():
        mapping={b.day:b for b in items}
        if len(mapping)!=len(items) or not all(d in mapping for d in days):
            raise ValueError('Duplicate or missing common daily bars')
        lookup[symbol]=mapping
        signals[symbol]=month_signals(items,month_ends)
    days=sorted(set(days))
    flags={}
    for symbol in symbols:
        available=[d for d in signals[symbol] if d<days[0]]
        if not available:
            raise ValueError('Ten completed monthly closes required before evaluation')
        flags[symbol]=signals[symbol][max(available)]
    constrained=profile=='trend_45_capped'
    capped=profile in ('trend_45_capped','buy_hold_capped')
    passive=profile.startswith('buy_hold')
    cash=2000.
    positions,orders,curve={},[],[]
    realized=executed_costs=turnover=0.
    peak=2000.
    drawdown=0.
    rebalance=True
    def sell(symbol,units,raw,day,reason):
        nonlocal cash,realized,executed_costs,turnover
        p=positions[symbol]
        units=min(units,p['units'])
        basis=p['basis']*units/p['units']
        proceeds=units*raw*(1-rate)
        cost=units*raw*rate
        cash+=proceeds
        realized+=proceeds-basis
        executed_costs+=cost
        turnover+=units*raw
        orders.append({'day':day,'symbol':symbol,'side':'sell','units':units,'raw_unit_price':raw,'notional':units*raw,'modeled_cost':cost,'realized_pnl':proceeds-basis,'reason':reason})
        p['units']-=units
        p['basis']-=basis
        if p['units']<1e-10:
            del positions[symbol]
    def buy(symbol,notional,raw,day):
        nonlocal cash,executed_costs,turnover
        notional=max(0,min(notional,cash/(1+rate)))
        if notional<1e-8:
            return
        units=notional/raw
        spent=notional*(1+rate)
        cost=notional*rate
        cash-=spent
        executed_costs+=cost
        turnover+=notional
        if symbol not in positions:
            positions[symbol]={'units':0.,'basis':0.,'entry_day':day}
        p=positions[symbol]
        p['units']+=units
        p['basis']+=spent
        if constrained:
            p['stop']=max(0.,(p['basis']-20)/(p['units']*(1-rate)))
        orders.append({'day':day,'symbol':symbol,'side':'buy','units':units,'raw_unit_price':raw,'notional':notional,'modeled_cost':cost,'realized_pnl':0.,'reason':'monthly_allocation' if not passive else 'initial_buy_hold'})
    for day in days:
        blocked=set()
        if constrained:
            for symbol,p in list(positions.items()):
                b=lookup[symbol][day]
                age=(date.fromisoformat(day)-date.fromisoformat(p['entry_day'])).days
                reason='gap_stop' if b.open<=p['stop'] else '45_day_limit' if age>=45 else None
                if reason:
                    sell(symbol,p['units'],b.open,day,reason)
                    blocked.add(symbol)
        if rebalance:
            opening_equity=cash+sum(p['units']*lookup[s][day].open for s,p in positions.items())
            budget=opening_equity/len(symbols)
            if capped:
                budget=min(300.,budget)
            target={s:(budget/(1+rate) if (passive or flags[s]) and s not in blocked else 0.) for s in symbols}
            for symbol,p in list(positions.items()):
                raw=lookup[symbol][day].open
                excess=p['units']*raw-target[symbol]
                if excess>1e-8:
                    sell(symbol,excess/raw,raw,day,'trend_off' if target[symbol]==0 else 'rebalance')
            for symbol in symbols:
                raw=lookup[symbol][day].open
                present=positions.get(symbol,{}).get('units',0)*raw
                buy(symbol,target[symbol]-present,raw,day)
            rebalance=False
        if constrained:
            for symbol,p in list(positions.items()):
                if lookup[symbol][day].low<=p['stop']:
                    sell(symbol,p['units'],p['stop'],day,'stop')
        reserve=sum(p['units']*lookup[s][day].close*rate for s,p in positions.items())
        equity=cash+sum(p['units']*lookup[s][day].close for s,p in positions.items())-reserve
        peak=max(peak,equity)
        drawdown=max(drawdown,(peak-equity)/peak)
        invested=sum(p['units']*lookup[s][day].close for s,p in positions.items())
        curve.append({'day':day,'equity':equity,'cash':cash,'open_assets':len(positions),'invested_value':invested,'exposure_fraction':invested/(cash+invested) if cash+invested>0 else 0.})
        if day in month_ends and not passive:
            for symbol in symbols:
                if day in signals[symbol]:
                    flags[symbol]=signals[symbol][day]
            rebalance=True
    final=curve[-1]['equity']
    open_rows=[{'symbol':s,'units':p['units'],'entry_day':p['entry_day'],'cost_basis':p['basis'],'marked_value':p['units']*lookup[s][days[-1]].close*(1-rate),'unrealized_pnl':p['units']*lookup[s][days[-1]].close*(1-rate)-p['basis']} for s,p in positions.items()]
    unrealized=sum(p['unrealized_pnl'] for p in open_rows)
    if abs(final-2000-realized-unrealized)>1e-7:
        raise ValueError('Cash/position/PnL reconciliation failed')
    final_reserve=sum(p['units']*lookup[s][days[-1]].close*rate for s,p in positions.items())
    costs=executed_costs+final_reserve
    net=final-2000
    attribution=[]
    for symbol in symbols:
        asset_realized=sum(o['realized_pnl'] for o in orders if o['symbol']==symbol)
        asset_unrealized=sum(o['unrealized_pnl'] for o in open_rows if o['symbol']==symbol)
        attribution.append({'symbol':symbol,'realized_pnl':asset_realized,'unrealized_pnl':asset_unrealized,'net_pnl':asset_realized+asset_unrealized})
    duration=max(1,(date.fromisoformat(days[-1])-date.fromisoformat(days[0])).days)
    return {'summary':{'starting_equity':2000.,'final_equity':final,'final_cash':cash,'net_pnl':net,'return_percentage':net/2000*100,'gross_pnl_same_positions':net+costs,'gross_return_percentage_same_positions':(net+costs)/2000*100,'executed_costs':executed_costs,'final_exit_cost_reserve':final_reserve,'total_modeled_costs':costs,'realized_pnl':realized,'unrealized_pnl':unrealized,'max_drawdown':drawdown,'cagr':(final/2000)**(365.25/duration)-1 if final>0 else None,'orders':len(orders),'turnover_multiple':turnover/2000,'open_assets':len(positions)},'orders':orders,'equity':curve,'open_positions':open_rows,'asset_attribution':attribution,'settings':{'profile':profile,'signal':'completed month close > mean of last 10 completed monthly closes','execution':'following session open','units':'fractional normalized total-return-adjusted ETF units, not broker shares','max_holding_days':45 if constrained else None,'position_cap':300 if capped else None,'planned_risk_stop':20 if constrained else None,'cash_return':0.,'spread_bps':spread_bps*cost_multiple,'slippage_bps':slippage_bps*cost_multiple}}

def summary_text(rows):
    lines=['# Monthly diversified trend allocation','','| Period | Profile | Costs | Starting equity | Final equity | Gross P&L* | Modeled costs | Net P&L | Return | Max drawdown |','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['period']} | {r['profile']} | {r['cost_multiple']} | {r['starting_equity']:.2f} | {r['final_equity']:.2f} | {r['gross_pnl_same_positions']:.2f} | {r['total_modeled_costs']:.2f} | {r['net_pnl']:.2f} | {r['return_percentage']:.2f}% | {r['max_drawdown']:.2%} |")
    lines+=['','*Gross P&L adds modeled costs back to the SAME executed positions; not a zero-cost portfolio rerun. Final equity includes cost-adjusted open positions. Earlier/later are chronological diagnostics, not certified untouched data.']
    return '\n'.join(lines)+'\n'

def main():
    import pandas as pd
    import pandas_market_calendars as mcal
    import yfinance as yf
    parser=argparse.ArgumentParser()
    parser.add_argument('--symbols',default=DEFAULT_SYMBOLS)
    parser.add_argument('--start',default='2010-01-01')
    parser.add_argument('--end',default=date.today().isoformat())
    parser.add_argument('--boundary',default='')
    parser.add_argument('--spread-bps',type=float,default=50.)
    parser.add_argument('--slippage-bps',type=float,default=25.)
    parser.add_argument('--output',default='results/monthly-trend')
    args=parser.parse_args()
    symbols=list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(',') if s.strip()))
    start,end=date.fromisoformat(args.start),date.fromisoformat(args.end)
    if not 1<=len(symbols)<=10 or start>=end or end>date.today():
        parser.error('Require 1-10 distinct ETFs and start < end <= today')
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    warm=start-timedelta(days=400)
    last_month=(pd.Timestamp(end)+pd.offsets.MonthEnd(0)).date()
    schedule=mcal.get_calendar('NYSE').schedule(start_date=warm,end_date=last_month)
    groups={}
    for d in schedule.index:
        groups.setdefault(d.strftime('%Y-%m'),[]).append(d.date().isoformat())
    month_ends={v[-1] for v in groups.values()}
    expected=[d.date().isoformat() for d in schedule.index if warm<=d.date()<end]
    days=[d for d in expected if start.isoformat()<=d<end.isoformat()]
    if not days:
        parser.error('No exchange sessions in evaluation')
    audit={'symbols':symbols,'start':start.isoformat(),'end_exclusive':end.isoformat(),'warmup_start':warm.isoformat(),'source':'Yahoo daily OHLC/Adj Close','universe':'fixed ETF proxies, not point-in-time historical constituent selection','hashes':{},'coverage':[],'price_cap_1_to_35':False,'profiles':PROFILES,'holdout_independence_verified':False}
    data={}
    for symbol in symbols:
        try:
            ticker=yf.Ticker(symbol)
            info=ticker.get_info()
            if info.get('quoteType')!='ETF' or info.get('currency')!='USD':
                raise ValueError('Require USD ETF metadata')
            frame=ticker.history(start=warm.isoformat(),end=end.isoformat(),interval='1d',auto_adjust=False,back_adjust=False,actions=True,raise_errors=True)
            required=['Open','High','Low','Close','Adj Close']
            if frame.empty or not set(required)<=set(frame) or frame.index.has_duplicates:
                raise ValueError('Missing adjusted daily price columns or duplicate bars')
            frame=frame.sort_index()
            frame.index=[stamp.date().isoformat() for stamp in frame.index]
            if not all(d in frame.index for d in expected):
                raise ValueError('Incomplete common warmup/evaluation calendar')
            frame=frame.loc[expected]
            if frame[required].isna().any().any() or not (frame[required]>0).all().all():
                raise ValueError('Invalid daily prices')
            safe=''.join(c for c in symbol if c.isalnum() or c in '-_.')
            path=out/('history-'+safe+'.csv')
            frame.to_csv(path)
            audit['hashes'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            anchor=float(frame['Adj Close'].iloc[0])
            normalized=[]
            for day,r in frame.iterrows():
                factor=100*float(r['Adj Close'])/anchor/float(r['Close'])
                normalized.append(Daily(day,*[float(r[c])*factor for c in ('Open','High','Low','Close')]))
            data[symbol]=normalized
            audit['coverage'].append({'symbol':symbol,'status':'eligible','sessions':len(normalized)})
        except Exception as exc:
            audit['coverage'].append({'symbol':symbol,'status':'unavailable','reason':str(exc)})
    (out/'inputs.json').write_text(json.dumps(audit,indent=2))
    if len(data)!=len(symbols):
        text='# Monthly trend allocation\n\nStarting equity: USD 2,000. Final equity unavailable: incomplete requested ETF universe. See inputs.json.\n'
    else:
        periods=partitions(days,args.boundary)
        audit['periods']=periods
        (out/'inputs.json').write_text(json.dumps(audit,indent=2))
        rows=[]
        for period,chosen in periods.items():
            for profile in PROFILES:
                for multiple in (1,2):
                    result=replay(data,chosen,month_ends,profile,args.spread_bps,args.slippage_bps,multiple)
                    result['experiment']={'period':period,'cost_multiple':multiple}
                    folder=out/f'{period}-{profile}-cost{multiple}'
                    folder.mkdir(exist_ok=True)
                    (folder/'run.json').write_text(json.dumps(result,indent=2,allow_nan=False))
                    for name in ('orders','equity','open_positions','asset_attribution'):
                        records=result[name]
                        with (folder/(name+'.csv')).open('w',newline='') as f:
                            writer=csv.DictWriter(f,fieldnames=list(records[0]) if records else ['status'])
                            writer.writeheader()
                            writer.writerows(records)
                    rows.append({'period':period,'profile':profile,'cost_multiple':multiple,**result['summary']})
        with (out/'comparison.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        text=summary_text(rows)
    (out/'SUMMARY.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(text)

if __name__=='__main__':
    main()
