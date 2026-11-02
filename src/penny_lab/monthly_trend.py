"""Monthly trend allocation on adjusted ETF research prices; no broker orders."""
import argparse
import csv
import hashlib
import json
import os
from datetime import date,timedelta
from math import isfinite
from pathlib import Path
from statistics import mean

ASSETS={'SPY':'US equities','EFA':'foreign developed equities','IEF':'US Treasury bonds','VNQ':'real estate','DBC':'commodities'}
SOURCE='https://mebfaber.com/2017/12/13/episode-86-quantitative-approach-tactical-asset-allocation/'


def replay(data,month_ends,start,end,case='monthly_trend',allocation=300.,cost_multiple=1):
    if case not in ('monthly_trend','trend_45day_cap','buy_hold') or allocation not in (250.,300.) or cost_multiple not in (0,1,2):
        raise ValueError('Unknown case, allocation or cost multiple')
    symbols=sorted(data)
    if not symbols or len({tuple(data[s]) for s in symbols})!=1:
        raise ValueError('Assets require identical chronological trading dates')
    days=list(data[symbols[0]])
    if days!=sorted(set(days)) or start>end or not any(start<=d<=end for d in days):
        raise ValueError('Invalid evaluation dates')
    for symbol in symbols:
        for row in data[symbol].values():
            if not all(isfinite(row[k]) and row[k]>0 for k in ('open','close')):
                raise ValueError('Nonpositive/nonfinite adjusted price')
    monthly={s:[] for s in symbols}
    active={s:False for s in symbols}
    units={s:0. for s in symbols}
    entered={}
    cash=2000.
    rate=.005*cost_multiple
    fills,curve,signals=[],[],[]
    paid=turnover=0.
    peak=cash
    drawdown=0.
    started=False
    pending=False
    blocked=set()
    def fill(symbol,delta,price,day,reason):
        nonlocal cash,paid,turnover
        notional=abs(delta)*price
        cost=notional*rate
        cash-=delta*price+cost
        units[symbol]+=delta
        if abs(units[symbol])<1e-10:
            units[symbol]=0.
            entered.pop(symbol,None)
        elif symbol not in entered:
            entered[symbol]=day
        paid+=cost
        turnover+=notional
        fills.append({'day':day,'symbol':symbol,'side':'buy' if delta>0 else 'sell','units':abs(delta),'adjusted_unit_quote':price,'notional':notional,'execution_cost':cost,'reason':reason})
    for day in days:
        if day>end:
            break
        if day>=start:
            first=not started
            started=True
            if case=='trend_45day_cap':
                for s in symbols:
                    if units[s] and (date.fromisoformat(day)-date.fromisoformat(entered[s])).days>=45:
                        fill(s,-units[s],data[s][day]['open'],day,'45_calendar_day_expiry')
                        blocked.add(s)
            rebalance=first or (pending and case!='buy_hold')
            if rebalance:
                blocked.clear()
                equity=cash+sum(units[s]*data[s][day]['open']*(1-rate) for s in symbols)
                budget=min(equity/len(symbols),allocation)
                target={s:(budget/(data[s][day]['open']*(1+rate)) if (case=='buy_hold' or active[s]) else 0.) for s in symbols}
                for s in symbols:
                    if units[s]>target[s]+1e-10:
                        fill(s,target[s]-units[s],data[s][day]['open'],day,'monthly_rebalance' if not first else 'initial_allocation')
                for s in symbols:
                    delta=target[s]-units[s]
                    if delta>1e-10 and s not in blocked:
                        delta=min(delta,max(0,cash)/(data[s][day]['open']*(1+rate)))
                        if delta>1e-10:
                            fill(s,delta,data[s][day]['open'],day,'monthly_rebalance' if not first else 'initial_allocation')
            reserve=sum(units[s]*data[s][day]['close']*rate for s in symbols)
            raw_value=sum(units[s]*data[s][day]['close'] for s in symbols)
            equity=cash+raw_value-reserve
            if cash< -1e-7:
                raise ValueError('Portfolio used unavailable cash')
            peak=max(peak,equity)
            drawdown=max(drawdown,(peak-equity)/peak)
            curve.append({'day':day,'equity':equity,'cash':cash,'gross_invested_value':raw_value,'exit_cost_reserve':reserve,'exposure':raw_value/(cash+raw_value) if cash+raw_value else 0.})
        pending=False
        if day in month_ends:
            for s in symbols:
                monthly[s].append(data[s][day]['close'])
                average=mean(monthly[s][-10:]) if len(monthly[s])>=10 else None
                active[s]=average is not None and monthly[s][-1]>average
                signals.append({'available_after_close':day,'symbol':s,'completed_months':len(monthly[s]),'monthly_adjusted_close':monthly[s][-1],'sma10':average,'invest_next_session':active[s]})
            pending=True
    if not curve:
        raise ValueError('No evaluation sample')
    final=curve[-1]['equity']
    reserve=curve[-1]['exit_cost_reserve']
    gross=final-2000+paid+reserve
    summary={'starting_equity':2000.,'final_equity':final,'net_pnl':final-2000,'net_return_percentage':(final/2000-1)*100,'gross_pnl_on_actual_positions':gross,'paid_execution_costs':paid,'ending_exit_cost_reserve':reserve,'max_drawdown':drawdown,'mean_exposure':mean(r['exposure'] for r in curve),'turnover_notional':turnover,'fills':len(fills),'open_assets':sum(units[s]>0 for s in symbols),'cash':cash}
    if abs(summary['net_pnl']-(gross-paid-reserve))>1e-7:
        raise ValueError('Gross/net cost reconciliation failed')
    return {'summary':summary,'fills':fills,'equity':curve,'signals':signals,'open_positions':[{'symbol':s,'units':units[s],'opened':entered.get(s),'adjusted_mark':data[s][curve[-1]['day']]['close']} for s in symbols if units[s]>0],
            'settings':{'case':case,'allocation_ceiling':allocation,'cost_multiple':cost_multiple,'execution':'next regular-session open after completed month-end signal','units':'fractional adjusted-price research units, not historical executable whole-share fills','cash_interest':0,'source':SOURCE,'no_published_performance_claim':True}}


def write_table(path,rows):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['status'])
        writer.writeheader()
        writer.writerows(rows)


def summary_text(rows):
    lines=['# Monthly diversified trend research','','| Period | Case | Cost | Starting equity | Final equity | Net P&L | Return | Gross P&L* | Paid costs | Exit reserve | Drawdown |','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['period']} | {r['case']} | {r['cost_multiple']} | {r['starting_equity']:.2f} | {r['final_equity']:.2f} | {r['net_pnl']:.2f} | {r['net_return_percentage']:.2f}% | {r['gross_pnl_on_actual_positions']:.2f} | {r['paid_execution_costs']:.2f} | {r['ending_exit_cost_reserve']:.2f} | {r['max_drawdown']:.2%} |")
    lines+=['','*Gross P&L is reconciled on each actual position path. Cost=0 is a separate zero-cost rerun, not arithmetic removal of costs. Final equity includes marked open positions less modeled liquidation costs. Later-period results are chronological diagnostics, not independently certified holdouts.']
    return '\n'.join(lines)+'\n'


def main():
    import pandas as pd
    import pandas_market_calendars as mcal
    import yfinance as yf
    parser=argparse.ArgumentParser()
    parser.add_argument('--years',type=int,default=10)
    parser.add_argument('--allocation',type=float,choices=(250.,300.),default=300.)
    parser.add_argument('--output',default='results/monthly-trend')
    args=parser.parse_args()
    if not 1<=args.years<=15:
        parser.error('years must be 1-15')
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    end=pd.Timestamp.now(tz='America/New_York').normalize()
    start=end-pd.DateOffset(years=args.years)
    warmup=(start-pd.DateOffset(months=12)).replace(day=1)
    calendar_end=end+pd.offsets.MonthEnd(0)
    schedule=mcal.get_calendar('NYSE').schedule(start_date=warmup.date(),end_date=calendar_end.date())
    dates=[s.market_open.date().isoformat() for _,s in schedule.iterrows() if s.market_close<end]
    month_ends=set()
    for _,group in schedule.groupby(schedule.index.strftime('%Y-%m')):
        day=group.iloc[-1].market_open.date().isoformat()
        if day<end.date().isoformat():
            month_ends.add(day)
    data={}
    audit={'assets':ASSETS,'evaluation_start':start.date().isoformat(),'end_exclusive':end.date().isoformat(),'warmup_start':warmup.date().isoformat(),'coverage':[],'hashes':{},'price_basis':'provider-adjusted total-return research prices','source':SOURCE}
    for symbol in ASSETS:
        try:
            ticker=yf.Ticker(symbol)
            info=ticker.get_info()
            if info.get('quoteType')!='ETF' or info.get('currency')!='USD':
                raise ValueError('ETF/USD metadata unavailable')
            frame=ticker.history(start=warmup,end=end,interval='1d',auto_adjust=True,back_adjust=False,actions=True,raise_errors=True)
            if frame.empty or frame.index.tz is None or frame.index.has_duplicates:
                raise ValueError('Missing/duplicate aware daily prices')
            frame=frame.sort_index()
            path=out/('history-'+symbol+'.csv')
            frame.to_csv(path)
            audit['hashes'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            mapping={stamp.tz_convert('America/New_York').date().isoformat():{'open':float(row.Open),'close':float(row.Close)} for stamp,row in frame.iterrows()}
            if any(day not in mapping for day in dates):
                raise ValueError('Missing exchange session; no forward-filled price')
            data[symbol]={day:mapping[day] for day in dates}
            audit['coverage'].append({'symbol':symbol,'status':'eligible','days':len(dates)})
        except Exception as exc:
            audit['coverage'].append({'symbol':symbol,'status':'unavailable','reason':str(exc)})
    (out/'coverage.json').write_text(json.dumps(audit,indent=2))
    if set(data)!=set(ASSETS):
        text='# Monthly trend research\n\nStarting equity: USD 2,000. Final equity: unavailable. All five asset histories are required; see coverage.json.\n'
    else:
        evaluation=[d for d in dates if d>=start.date().isoformat()]
        if len(evaluation)<10:
            raise ValueError('Insufficient evaluation sessions')
        cut=int(len(evaluation)*.7)
        periods={'full':evaluation,'development':evaluation[:cut],'later_period':evaluation[cut:]}
        audit.update(periods=periods,holdout_independence_verified=False,allocation=args.allocation,fractional_units=True,individual_stock_price_cap_removed=True,no_intraday_stop_rule=True)
        (out/'experiment.json').write_text(json.dumps(audit,indent=2))
        rows=[]
        for period,chosen in periods.items():
            for case in ('monthly_trend','trend_45day_cap','buy_hold'):
                for cost in (0,1,2):
                    result=replay(data,month_ends,chosen[0],chosen[-1],case,args.allocation,cost)
                    folder=out/f'{period}-{case}-cost{cost}'
                    folder.mkdir(exist_ok=True)
                    (folder/'run.json').write_text(json.dumps(result,indent=2,allow_nan=False))
                    for name in ('fills','equity','signals','open_positions'):
                        write_table(folder/(name+'.csv'),result[name])
                    rows.append({'period':period,'case':case,'cost_multiple':cost,**result['summary']})
        write_table(out/'comparison.csv',rows)
        indexed={(r['period'],r['case'],r['cost_multiple']):r for r in rows}
        comparisons=[]
        for r in rows:
            if r['case']=='buy_hold':
                continue
            benchmark=indexed[(r['period'],'buy_hold',r['cost_multiple'])]
            comparisons.append({'period':r['period'],'case':r['case'],'cost_multiple':r['cost_multiple'],'net_pnl_difference_vs_buy_hold':r['net_pnl']-benchmark['net_pnl'],'drawdown_difference_vs_buy_hold':r['max_drawdown']-benchmark['max_drawdown']})
        write_table(out/'versus-buy-hold.csv',comparisons)
        text=summary_text(rows)
    (out/'SUMMARY.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(text)

if __name__=='__main__':
    main()
