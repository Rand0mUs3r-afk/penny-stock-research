"""Five predeclared setups/mixtures, same saved data and independent accounts."""
import argparse
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from statistics import mean
from . import engine
from .lab_setups import CASES,NY,names_at,pattern,overhead_reference
from .models import Signal
from .quality import inspect_session
from .report import render,statistics,money,cell
from .validation import load_snapshot,stressed_config,checked_bytes
from .yahoo_pilot import write_table

def historical_levels(source,symbols):
    import pandas as pd
    import pandas_market_calendars as mcal
    hashes=json.loads((source/'input-hashes.json').read_text())
    coverage=json.loads((source/'coverage.json').read_text())
    action_days={r['symbol']:{a['day'] for a in r.get('actions',[])} for r in coverage['coverage']}
    levels={}
    for symbol in symbols:
        safe=''.join(c for c in symbol if c.isalnum() or c in '-_.')
        path=source/('history-'+safe+'.csv')
        checked_bytes(path,hashes[symbol])
        frame=pd.read_csv(path,index_col=0)
        frame.index=pd.to_datetime(frame.index,utc=True)
        frame=frame.sort_index()
        schedule=mcal.get_calendar('NYSE').schedule(start_date=frame.index.min().date(),end_date=frame.index.max().date())
        previous=None
        for _,session in schedule.iterrows():
            day=session.market_open.date().isoformat()
            if previous and day not in action_days.get(symbol,set()):
                levels[(symbol,day)]=previous
            piece=frame[(frame.index>=session.market_open)&(frame.index<session.market_close)]
            expected=pd.date_range(session.market_open,session.market_close,freq='5min',inclusive='left')
            if inspect_session(piece,expected)=='usable' and day not in action_days.get(symbol,set()):
                stamp=piece.High.idxmax()
                previous={'target':float(piece.High.max()),'reference_time':(stamp+pd.Timedelta(minutes=5)).isoformat(),'reference_rule':'previous_complete_exchange_session_high'}
            else:
                previous=None
    return levels

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',default='results/research-v2')
    args=parser.parse_args()
    source=Path(args.input)
    out=source/'strategy-lab'
    out.mkdir(parents=True,exist_ok=True)
    def publish(text):
        (out/'SUMMARY.md').write_text(text)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
                f.write(text)
    if not (source/'A_baseline'/'run.json').exists():
        publish('# Strategy discovery lab\n\nNo usable source snapshot; inspect coverage. No strategy results fabricated.\n')
        return
    bars,refs,base,provenance=load_snapshot(source)
    levels=historical_levels(source,sorted({b.symbol for b in bars}))
    policy=dict(provenance['entry_policy'])
    policy['minimum_net_rr']=None
    manifest={**provenance,'entry_policy':policy,'lab_target_rule':'nearest confirmed intraday pivot or previous complete-session high above signal; next-open invalidation remains active'}
    original_scan,original_high=engine.scan,engine.previous_high
    summaries=[]
    lines=['# Strategy discovery lab','','Predeclared standalone setups and mixtures on the SAME eligible snapshot. USD 1–35, same-day exits, no minimum RR. Targets are already-known historical overhead highs; signals without a target are rejected, not assigned invented reward.', '',
           'Independent starting accounts per case and cost scenario. October is development data, not an untouched holdout. Source uptrend results are acquisition diagnostics and are not the new setup results.','','| Case | Spread/slippage multiple | Trades | Final equity | Net P&L | Win rate | Avg trade | Drawdown | Mean hold, min | Sample |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for case,names in CASES.items():
        for multiple in (1,2):
            cfg=replace(stressed_config(base,multiple),strategies=names)
            references,used,decisions={},{},[]
            def scanner(history,config):
                b=history[-1]
                local=b.timestamp.astimezone(NY)
                day=local.date().isoformat()
                if mean(x.close*x.volume for x in history[-12:])<config.min_avg_dollar_volume:
                    return []
                candidates=[]
                for name in names_at(case,b.timestamp):
                    if name in ('opening_range_breakout','opening_range_pullback') and (b.symbol,day,name) in used:
                        continue
                    setup=pattern(history,name)
                    if not setup or not 0<setup['stop']<b.close:
                        continue
                    ref=overhead_reference(history,levels.get((b.symbol,day)))
                    if ref is None:
                        decisions.append({'symbol':b.symbol,'timestamp':b.timestamp.isoformat(),'setup':name,'reason':'no_known_overhead_target'})
                        continue
                    if name in ('opening_range_breakout','opening_range_pullback'):
                        used[(b.symbol,day,name)]=True
                    references[(b.symbol,b.timestamp)]=ref
                    decisions.append({'symbol':b.symbol,'timestamp':b.timestamp.isoformat(),'setup':name,'reason':'signal_emitted'})
                    average=mean(x.volume for x in history[max(0,len(history)-13):-1])
                    score=min(b.volume/average,5) if average else 0
                    candidates.append(Signal(b.symbol,name,b.timestamp,setup['stop'],score,setup['reason']))
                return candidates
            def reference(history,lookback):
                b=history[-1]
                return references.get((b.symbol,b.timestamp))
            try:
                engine.scan=scanner
                engine.previous_high=reference
                result=engine.run(bars,cfg,manifest)
            finally:
                engine.scan=original_scan
                engine.previous_high=original_high
            result['experiment_case']={'case':case,'setups':names,'cost_multiple':multiple}
            result['limitations'].append('New strategy hypotheses selected after inspecting October; not validated edges or a replication of an academic paper')
            folder=out/f'{case}-cost{multiple}'
            folder.mkdir(exist_ok=True)
            (folder/'run.json').write_text(json.dumps(result,indent=2,allow_nan=False))
            (folder/'SUMMARY.md').write_text(render(result))
            for filename,key in [('trades','trades'),('equity','equity_curve'),('rejections','rejections'),('ranking','strategy_ranking'),('execution-audit','execution_audit')]:
                records=result[key]
                write_table(folder/(filename+'.csv'),records,list(records[0]) if records else ['status'])
            write_table(folder/'setup-decisions.csv',decisions,['symbol','timestamp','setup','reason'])
            stats=statistics(result['trades'])
            summary=result['summary']
            pnl_by_symbol=defaultdict(float)
            pnl_by_day=defaultdict(float)
            for t in result['trades']:
                pnl_by_symbol[t['symbol']]+=t['net_pnl']
                pnl_by_day[t['exit_time'][:10]]+=t['net_pnl']
            audit=result['execution_audit']
            hold=mean(t['hold_minutes_upper_bound'] for t in audit) if audit else None
            status='no_trades' if not stats['trades'] else ('small_sample' if stats['trades']<30 else 'exploratory_not_validated')
            row={'case':case,'cost_multiple':multiple,**summary,'win_rate':stats['win_rate'],'average_win':stats['average_win'],'average_loss':stats['average_loss'],'expectancy':stats['expectancy'],'profit_factor':stats['profit_factor'],'mean_hold_upper_bound':hold,'largest_winner':stats['best'],'worst_day':min(pnl_by_day.values()) if pnl_by_day else None,'sample_status':status,'no_target_signals':sum(d['reason']=='no_known_overhead_target' for d in decisions)}
            summaries.append(row)
            (folder/'attribution.json').write_text(json.dumps({'by_symbol':dict(pnl_by_symbol),'by_day':dict(pnl_by_day),'statistics':stats},indent=2))
            win=f"{stats['win_rate']:.1%}" if stats['win_rate'] is not None else 'N/A'
            hold_text=f'{hold:.1f}' if hold is not None else 'N/A'
            lines.append(f"| {case} | {multiple} | {stats['trades']} | {money(summary['ending_equity'])} | {money(summary['net_pnl'])} | {win} | {money(stats['expectancy'])} | {summary['max_drawdown']:.2%} | {hold_text} | {status} |")
    write_table(out/'comparison.csv',summaries,list(summaries[0]))
    audit={'cases':CASES,'source_price_hashes':json.loads((source/'input-hashes.json').read_text()),'cost_multiples':[1,2],'engine_version':engine.ENGINE_VERSION,'source_evaluation':json.loads((source/'coverage.json').read_text()).get('evaluation_start'),'selection':'All cases shown; no optimized or automatically selected winner'}
    (out/'experiment.json').write_text(json.dumps(audit,indent=2))
    lines+=['','## Decision and attribution diagnostics','','| Case | Cost multiple | Signals without historical target | Biggest winner | Worst trading day | Average win | Average loss |','|---|---:|---:|---:|---:|---:|---:|']
    for r in summaries:
        lines.append(f"| {r['case']} | {r['cost_multiple']} | {r['no_target_signals']} | {money(r['largest_winner'])} | {money(r['worst_day'])} | {money(r['average_win'])} | {money(r['average_loss'])} |")
    lines+=['','Each case artifact includes full trades, setup decisions, reasons, targets, risk, cost reconciliation, per-day/per-ticker attribution, equity and report. Mix components share one account with no duplicate ticker position. Thirty trades is only a disclosure threshold, not statistical proof. No-trade cases are inactive/inconclusive, not profitable winners. Current-universe, complete-session, RVOL warmup eligibility and all provider limitations remain.']
    publish('\n'.join(lines)+'\n')

if __name__=='__main__':
    main()
