"""One cash ledger shared by monthly trend, buy-and-hold and every ticker."""
import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from datetime import date
from math import isfinite
from pathlib import Path
from statistics import mean
from .monthly_trend import ASSETS,SOURCE,write_table

STRATEGIES=('buy_hold','monthly_trend')

class Ledger:
    def __init__(self,rate):
        self.cash=2000.
        self.rate=rate
        self.lots=[]
        self.fills=[]
        self.trades=[]
        self.paid=0.
        self.next_id=1

    def quantity(self,strategy,symbol):
        return sum(p['units'] for p in self.lots if p['strategy']==strategy and p['symbol']==symbol)

    def transact(self,strategy,symbol,delta,quote,day,reason):
        if strategy not in STRATEGIES or not isfinite(quote) or quote<=0 or not isfinite(delta):
            raise ValueError('Invalid fill')
        if abs(delta)<1e-10:
            return
        notional=abs(delta)*quote
        cost=notional*self.rate
        if delta>0:
            if notional+cost>self.cash+1e-7:
                raise ValueError('Purchase exceeds shared cash')
            self.cash-=notional+cost
            self.lots.append({'lot_id':self.next_id,'strategy':strategy,'symbol':symbol,'entry_date':day,'units':delta,'entry_quote':quote,'entry_cost_per_unit':quote*self.rate})
            self.next_id+=1
        else:
            remaining=-delta
            if remaining>self.quantity(strategy,symbol)+1e-7:
                raise ValueError('Sale exceeds owned units')
            for p in self.lots:
                if remaining<=1e-10:
                    break
                if p['strategy']!=strategy or p['symbol']!=symbol:
                    continue
                units=min(p['units'],remaining)
                entry_cost=units*p['entry_cost_per_unit']
                exit_cost=units*quote*self.rate
                gross=units*(quote-p['entry_quote'])
                self.trades.append({'trade_id':len(self.trades)+1,'lot_id':p['lot_id'],'strategy':strategy,'ticker':symbol,'entry_date':p['entry_date'],'exit_date':day,'hold_calendar_days':(date.fromisoformat(day)-date.fromisoformat(p['entry_date'])).days,'units':units,'adjusted_entry_quote':p['entry_quote'],'adjusted_exit_quote':quote,'entry_cost':entry_cost,'exit_cost':exit_cost,'gross_pnl':gross,'net_pnl':gross-entry_cost-exit_cost,'exit_reason':reason})
                p['units']-=units
                remaining-=units
            self.lots=[p for p in self.lots if p['units']>1e-10]
            self.cash+=notional-cost
        self.paid+=cost
        self.fills.append({'day':day,'strategy':strategy,'ticker':symbol,'side':'buy' if delta>0 else 'sell','units':abs(delta),'adjusted_quote':quote,'notional':notional,'cost':cost,'cash_after':self.cash,'combined_ticker_value_after':sum(p['units'] for p in self.lots if p['symbol']==symbol)*quote,'reason':reason})
        if self.cash< -1e-7:
            raise ValueError('Negative shared cash')

    def marked_positions(self,quotes,day):
        return [{'lot_id':p['lot_id'],'strategy':p['strategy'],'ticker':p['symbol'],'entry_date':p['entry_date'],'exit_date':None,'as_of_date':day,'hold_calendar_days':(date.fromisoformat(day)-date.fromisoformat(p['entry_date'])).days,'units':p['units'],'adjusted_entry_quote':p['entry_quote'],'adjusted_mark':quotes[p['symbol']],'marked_value':p['units']*quotes[p['symbol']]*(1-self.rate),'unrealized_pnl':p['units']*(quotes[p['symbol']]*(1-self.rate)-p['entry_quote']-p['entry_cost_per_unit'])} for p in self.lots]


def replay(data,month_ends,start,end,allocation=300.,trend_weight=.5,cost_multiple=1):
    if allocation not in (250.,300.) or not 0<=trend_weight<=1 or cost_multiple not in (0,1,2):
        raise ValueError('Invalid settings')
    symbols=sorted(data)
    if not symbols or len({tuple(data[s]) for s in symbols})!=1:
        raise ValueError('Require identical chronological dates across assets')
    days=list(data[symbols[0]])
    if days!=sorted(set(days)) or start>end:
        raise ValueError('Invalid dates')
    for values in data.values():
        if any(not all(isfinite(r[k]) and r[k]>0 for k in ('open','close')) for r in values.values()):
            raise ValueError('Invalid adjusted prices')
    ledger=Ledger(.005*cost_multiple)
    active={s:False for s in symbols}
    monthly={s:[] for s in symbols}
    pending=started=False
    peak=2000.
    drawdown=0.
    curve,signals=[],[]
    for day in days:
        if day>end:
            break
        if day>=start:
            first=not started
            started=True
            if first or pending:
                opens={s:data[s][day]['open'] for s in symbols}
                equity=ledger.cash+sum(p['units']*opens[p['symbol']]*(1-ledger.rate) for p in ledger.lots)
                per_ticker=min(equity/len(symbols),allocation)
                targets={}
                for s in symbols:
                    core=ledger.quantity('buy_hold',s)
                    if first:
                        targets[('buy_hold',s)]=per_ticker*(1-trend_weight)/(opens[s]*(1+ledger.rate))
                        core=targets[('buy_hold',s)]
                    room=max(0,allocation-core*opens[s])
                    budget=min(per_ticker*trend_weight,room)
                    targets[('monthly_trend',s)]=budget/(opens[s]*(1+ledger.rate)) if active[s] else 0.
                for (strategy,s),target in sorted(targets.items()):
                    owned=ledger.quantity(strategy,s)
                    if owned>target+1e-10:
                        ledger.transact(strategy,s,target-owned,opens[s],day,'trend_rebalance')
                for (strategy,s),target in sorted(targets.items()):
                    delta=target-ledger.quantity(strategy,s)
                    combined=sum(ledger.quantity(role,s) for role in STRATEGIES)*opens[s]
                    room=max(0,allocation-combined)
                    delta=min(delta,max(0,ledger.cash)/(opens[s]*(1+ledger.rate)),room/(opens[s]*(1+ledger.rate)))
                    if delta>1e-10:
                        ledger.transact(strategy,s,delta,opens[s],day,'initial_allocation' if first else 'trend_rebalance')
            quotes={s:data[s][day]['close'] for s in symbols}
            raw=sum(p['units']*quotes[p['symbol']] for p in ledger.lots)
            reserve=raw*ledger.rate
            equity=ledger.cash+raw-reserve
            peak=max(peak,equity)
            drawdown=max(drawdown,(peak-equity)/peak)
            curve.append({'day':day,'equity':equity,'cash':ledger.cash,'gross_position_value':raw,'exit_reserve':reserve,'open_lots':len(ledger.lots)})
        pending=False
        if day in month_ends:
            for s in symbols:
                monthly[s].append(data[s][day]['close'])
                average=mean(monthly[s][-10:]) if len(monthly[s])>=10 else None
                active[s]=average is not None and monthly[s][-1]>average
                signals.append({'signal_date':day,'ticker':s,'monthly_close':monthly[s][-1],'sma10':average,'trend_enabled':active[s]})
            pending=True
    if not curve:
        raise ValueError('No evaluation sessions')
    asof=curve[-1]['day']
    positions=ledger.marked_positions({s:data[s][asof]['close'] for s in symbols},asof)
    realized=sum(t['net_pnl'] for t in ledger.trades)
    unrealized=sum(p['unrealized_pnl'] for p in positions)
    final=curve[-1]['equity']
    if abs(final-2000-realized-unrealized)>1e-7:
        raise ValueError('Shared account does not reconcile to FIFO lots')
    attribution=[]
    for strategy in STRATEGIES:
        closed=sum(t['net_pnl'] for t in ledger.trades if t['strategy']==strategy)
        opened=sum(p['unrealized_pnl'] for p in positions if p['strategy']==strategy)
        attribution.append({'strategy':strategy,'realized_pnl':closed,'unrealized_pnl':opened,'total_pnl':closed+opened})
    holdings=[{'status':'closed','strategy':t['strategy'],'ticker':t['ticker'],'lot_id':t['lot_id'],'entry_date':t['entry_date'],'exit_date':t['exit_date'],'as_of_date':t['exit_date'],'hold_calendar_days':t['hold_calendar_days'],'units':t['units']} for t in ledger.trades]
    holdings += [{'status':'open','strategy':p['strategy'],'ticker':p['ticker'],'lot_id':p['lot_id'],'entry_date':p['entry_date'],'exit_date':None,'as_of_date':asof,'hold_calendar_days':p['hold_calendar_days'],'units':p['units']} for p in positions]
    summary={'starting_equity':2000.,'final_equity':final,'cash':ledger.cash,'net_pnl':final-2000,'return_percentage':(final/2000-1)*100,'realized_pnl':realized,'unrealized_pnl':unrealized,'paid_costs':ledger.paid,'exit_reserve':curve[-1]['exit_reserve'],'max_drawdown':drawdown,'closed_trade_segments':len(ledger.trades),'open_lots':len(positions),'first_entry_date':min((f['day'] for f in ledger.fills if f['side']=='buy'),default=None),'last_exit_date':max((t['exit_date'] for t in ledger.trades),default=None)}
    split=int(len(curve)*.7)
    periods=[]
    if 0<split<len(curve):
        for name,first,last,initial in [('development',0,split-1,2000.),('later_period',split,len(curve)-1,curve[split-1]['equity'])]:
            final_period=curve[last]['equity']
            periods.append({'period':name,'start':curve[first]['day'],'end':curve[last]['day'],'starting_equity':initial,'final_equity':final_period,'net_pnl':final_period-initial,'cash_reset':False})
    return {'summary':summary,'trades':ledger.trades,'fills':ledger.fills,'equity':curve,'open_positions':positions,'ticker_holding_days':holdings,'strategy_attribution':attribution,'periods':periods,'signals':signals,'settings':{'portfolio_mode':'one_shared_cash_ledger','starting_capital_deposits':1,'strategy_weights':{'monthly_trend':trend_weight,'buy_hold':1-trend_weight},'combined_ticker_allocation_ceiling':allocation,'cost_multiple':cost_multiple,'fractional_adjusted_research_units':True,'date_precision':'exchange trading dates; not intraday timestamps','lot_matching':'FIFO within strategy and ticker'}}


def render(result):
    r=result['summary']
    lines=['# One shared USD 2,000 portfolio','','| Starting equity | Final equity | Net P&L | Return | Paid costs | Exit reserve | Drawdown |','|---:|---:|---:|---:|---:|---:|---:|',f"| {r['starting_equity']:.2f} | {r['final_equity']:.2f} | {r['net_pnl']:.2f} | {r['return_percentage']:.2f}% | {r['paid_costs']:.2f} | {r['exit_reserve']:.2f} | {r['max_drawdown']:.2%} |",'',f"First entry: {r['first_entry_date'] or 'none'}. Last closed-trade exit: {r['last_exit_date'] or 'none'}.",'','## Closed trades: entry and exit dates','','| Trade | Strategy | Ticker | Entry date | Exit date | Calendar hold days | Units | Net P&L |','|---:|---|---|---|---|---:|---:|---:|']
    for t in result['trades']:
        lines.append(f"| {t['trade_id']} | {t['strategy']} | {t['ticker']} | {t['entry_date']} | {t['exit_date']} | {t['hold_calendar_days']} | {t['units']:.6f} | {t['net_pnl']:.2f} |")
    lines+=['','## Exact ticker holding ledger','','| Status | Strategy | Ticker | Lot | Entry date | Exit date | As of | Calendar hold days | Units |','|---|---|---|---:|---|---|---|---:|---:|']
    for p in result['ticker_holding_days']:
        lines.append(f"| {p['status']} | {p['strategy']} | {p['ticker']} | {p['lot_id']} | {p['entry_date']} | {p['exit_date'] or '-'} | {p['as_of_date']} | {p['hold_calendar_days']} | {p['units']:.6f} |")
    lines+=['','## Strategy P&L within the same account','','| Strategy | Realized | Unrealized | Total P&L |','|---|---:|---:|---:|']
    for a in result['strategy_attribution']:
        lines.append(f"| {a['strategy']} | {a['realized_pnl']:.2f} | {a['unrealized_pnl']:.2f} | {a['total_pnl']:.2f} |")
    lines+=['','## Continuous period diagnostics: capital is not reset','','| Period | Start | End | Starting equity | Final equity | Net P&L |','|---|---|---|---:|---:|---:|']
    for p in result['periods']:
        lines.append(f"| {p['period']} | {p['start']} | {p['end']} | {p['starting_equity']:.2f} | {p['final_equity']:.2f} | {p['net_pnl']:.2f} |")
    lines+=['','Daily data determines exact entry/exit trading dates, not exact intraday times. Partial sells are FIFO trade segments, not duplicated full trades. Open rows have no fabricated exit date; their age is measured at the final data date. Research units use provider-adjusted ETF prices.']
    return '\n'.join(lines)+'\n'


def main():
    import pandas as pd
    import pandas_market_calendars as mcal
    import yfinance as yf
    parser=argparse.ArgumentParser()
    parser.add_argument('--years',type=int,default=10)
    parser.add_argument('--allocation',type=float,choices=(250.,300.),default=300.)
    parser.add_argument('--trend-weight',type=float,default=50.)
    parser.add_argument('--cost-multiple',type=int,choices=(0,1,2),default=1)
    parser.add_argument('--output',default='results/shared-monthly')
    args=parser.parse_args()
    if not 1<=args.years<=15 or not 0<=args.trend_weight<=100:
        parser.error('years 1-15 and trend weight 0-100 required')
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    end=pd.Timestamp.now(tz='America/New_York').normalize()
    start=end-pd.DateOffset(years=args.years)
    warm=(start-pd.DateOffset(months=12)).replace(day=1)
    schedule=mcal.get_calendar('NYSE').schedule(start_date=warm.date(),end_date=(end+pd.offsets.MonthEnd(0)).date())
    days=[s.market_open.date().isoformat() for _,s in schedule.iterrows() if s.market_close<end]
    ends={group.iloc[-1].market_open.date().isoformat() for _,group in schedule.groupby(schedule.index.strftime('%Y-%m')) if group.iloc[-1].market_open.date()<end.date()}
    data={}
    audit={'assets':ASSETS,'source':SOURCE,'coverage':[],'hashes':{}}
    for symbol in ASSETS:
        try:
            ticker=yf.Ticker(symbol)
            info=ticker.get_info()
            if info.get('quoteType')!='ETF' or info.get('currency')!='USD':
                raise ValueError('ETF/USD metadata unavailable')
            frame=ticker.history(start=warm,end=end,interval='1d',auto_adjust=True,back_adjust=False,actions=True,raise_errors=True)
            if frame.empty or frame.index.tz is None or frame.index.has_duplicates:
                raise ValueError('Invalid daily history')
            path=out/('history-'+symbol+'.csv')
            frame.sort_index().to_csv(path)
            audit['hashes'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            mapping={stamp.tz_convert('America/New_York').date().isoformat():{'open':float(row.Open),'close':float(row.Close)} for stamp,row in frame.iterrows()}
            if any(d not in mapping for d in days):
                raise ValueError('Missing exchange session')
            data[symbol]={d:mapping[d] for d in days}
            audit['coverage'].append({'symbol':symbol,'status':'eligible'})
        except Exception as exc:
            audit['coverage'].append({'symbol':symbol,'status':'unavailable','reason':str(exc)})
    (out/'coverage.json').write_text(json.dumps(audit,indent=2))
    if set(data)!=set(ASSETS):
        text='# Shared portfolio\n\nStarting equity: USD 2,000. Final equity unavailable; all five asset histories are required. See coverage.json.\n'
    else:
        result=replay(data,ends,start.date().isoformat(),days[-1],args.allocation,args.trend_weight/100,args.cost_multiple)
        (out/'run.json').write_text(json.dumps(result,indent=2,allow_nan=False))
        for name in ('trades','fills','equity','open_positions','ticker_holding_days','strategy_attribution','periods','signals'):
            write_table(out/(name+'.csv'),result[name])
        text=render(result)
    (out/'SUMMARY.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(text if len(text.encode('utf-8'))<900000 else text[:20000]+'\n\nComplete trade and holding-date ledger is in the artifact SUMMARY.md and CSVs.\n')

if __name__=='__main__':
    main()
