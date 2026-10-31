"""Offline snapshot replays; no optimization or independent-edge claims."""
import argparse
import csv
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo
from . import engine
from .config import Config
from .models import Bar
from .report import statistics, render, money, cell
from .yahoo_pilot import write_table

NY=ZoneInfo('America/New_York')
VARIANTS=('A_baseline','B_rvol','C_rvol_vwap')

def split_days(days,minimum_days=10):
    days=sorted(set(days))
    if len(days)<minimum_days:
        return {'full_sample_only':days}
    cut=int(len(days)*.7)
    return {'development':days[:cut],'later_period':days[cut:]}

def stressed_config(cfg,multiplier):
    if multiplier not in (1,2):
        raise ValueError('Only predeclared cost multipliers 1 or 2')
    return replace(cfg,spread_bps=cfg.spread_bps*multiplier,slippage_bps=cfg.slippage_bps*multiplier)

def checked_bytes(path,expected):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError(f'Snapshot hash mismatch: {path.name}')
    return raw

def gate(history,denominator,variant):
    if variant not in VARIANTS:
        raise ValueError('Unknown variant')
    if variant=='A_baseline':
        return True
    if not denominator or sum(b.volume for b in history)/denominator<2:
        return False
    if variant=='B_rvol':
        return True
    def vwap(items):
        volume=sum(b.volume for b in items)
        return sum((b.high+b.low+b.close)/3*b.volume for b in items)/volume if volume else None
    current,earlier=vwap(history),vwap(history[:-3])
    return current is not None and earlier is not None and history[-1].close>current>earlier

def load_snapshot(source):
    import pandas as pd
    baseline=json.loads((source/'A_baseline'/'run.json').read_text())
    hashes=json.loads((source/'input-hashes.json').read_text())
    with (source/'eligibility.csv').open(newline='') as f:
        eligible={(r['symbol'],r['day']) for r in csv.DictReader(f) if r['reason']=='eligible'}
    references={}
    with (source/'rvol-reference.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            key=(r['symbol'],r['day'],r['slot'])
            if key in references:
                raise ValueError('Duplicate RVOL reference')
            references[key]=float(r['average_cumulative_volume'])
    bars=[]
    for symbol in sorted({s for s,d in eligible}):
        safe=''.join(c for c in symbol if c.isalnum() or c in '-_.')
        path=source/('history-'+safe+'.csv')
        checked_bytes(path,hashes[symbol])
        frame=pd.read_csv(path,index_col=0)
        frame.index=pd.to_datetime(frame.index,utc=True)
        if frame.index.has_duplicates:
            raise ValueError('Duplicate snapshot candles')
        frame=frame.sort_index()
        for day in sorted(d for s,d in eligible if s==symbol):
            begin=pd.Timestamp(day+' 09:30',tz='America/New_York')
            closing=baseline['provenance']['session_closes'][day]
            end=pd.Timestamp(day+' '+closing,tz='America/New_York')
            piece=frame[(frame.index>=begin)&(frame.index<end)]
            expected=pd.date_range(begin,end,freq='5min',inclusive='left').tz_convert('UTC')
            if not piece.index.equals(expected):
                raise ValueError(f'Eligible snapshot session no longer complete: {symbol} {day}')
            for stamp,r in piece.iterrows():
                bar=Bar(symbol,(stamp+pd.Timedelta(minutes=5)).to_pydatetime(),*[float(r[c]) for c in ('Open','High','Low','Close','Volume')])
                key=(symbol,day,bar.timestamp.astimezone(NY).strftime('%H:%M'))
                if references.get(key,0)<=0:
                    raise ValueError('Missing/nonpositive saved RVOL reference')
                bars.append(bar)
    if not bars:
        raise ValueError('No eligible saved bars')
    values=dict(baseline['config'])
    values['strategies']=('uptrend_pullback',)
    return sorted(bars,key=lambda b:(b.timestamp,b.symbol)),references,Config(**values),baseline['provenance']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',default='results/research-v2')
    parser.add_argument('--minimum-trades',type=int,default=30,help='Disclosure threshold only, not statistical certification')
    args=parser.parse_args()
    if args.minimum_trades<1:
        parser.error('minimum-trades must be positive')
    source=Path(args.input)
    out=source/'validation'
    out.mkdir(parents=True,exist_ok=True)
    def publish(text):
        (out/'SUMMARY.md').write_text(text)
        with (source/'SUMMARY.md').open('a') as f:
            f.write('\n'+text)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
                f.write(text)
    if not (source/'A_baseline'/'run.json').exists():
        publish('## Snapshot replay and validation\n\nNo completed baseline snapshot. No stress-test or validation returns fabricated.\n')
        return
    bars,references,base,manifest=load_snapshot(source)
    days=sorted({b.timestamp.astimezone(NY).date().isoformat() for b in bars})
    periods=split_days(days)
    inputs=['input-hashes.json','eligibility.csv','rvol-reference.csv','universe.json','config.json','A_baseline/run.json']
    audit={'engine_version':engine.ENGINE_VERSION,'input_file_hashes':{p:hashlib.sha256((source/p).read_bytes()).hexdigest() for p in inputs},
           'periods':periods,'multipliers':[1,2],'variants':VARIANTS,'minimum_trades_disclosure':args.minimum_trades,
           'selection_policy':'No optimization, no winner selection; replay all predeclared variants',
           'warning':'Historical/current-universe and data-selection biases remain. Later period is a chronological diagnostic, not certified untouched out-of-sample evidence; previous October inspection contaminated strategy selection.'}
    (out/'audit.json').write_text(json.dumps(audit,indent=2))
    original=engine.scan
    rows=[]
    lines=['## Snapshot replay, cost stress, and chronological diagnostics','',
           'No new provider requests. Price files are checked against their saved SHA-256 hashes; reference and eligibility files are fingerprinted for this replay. Each variant/period/cost case starts with an independent configured account.', '',
           'Fixed rules are evaluated on the earlier 70% and later 30% of available eligible dates when at least 10 dates exist. Otherwise only full-sample stress tests run. No automatic optimization or winner selection.', '',
           'A later-period result is NOT automatically an untouched holdout: earlier research already inspected October. More trades and positive P&L do not remove selection or execution bias.', '',
           '| Period | Dates | Variant | Cost multiple | Trades | Final equity | Net P&L | Win rate | Avg trade | Drawdown | Sample status |',
           '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for period,chosen_days in periods.items():
        dates=set(chosen_days)
        selected=[b for b in bars if b.timestamp.astimezone(NY).date().isoformat() in dates]
        for multiplier in (1,2):
            cfg=stressed_config(base,multiplier)
            for variant in VARIANTS:
                def scanner(history,config):
                    found=original(history,config)
                    if not found:
                        return []
                    b=history[-1]
                    local=b.timestamp.astimezone(NY)
                    key=(b.symbol,local.date().isoformat(),local.strftime('%H:%M'))
                    return found if gate(history,references.get(key),variant) else []
                try:
                    engine.scan=scanner
                    result=engine.run(selected,cfg,manifest)
                finally:
                    engine.scan=original
                result['validation_case']={'period':period,'dates':chosen_days,'variant':variant,'cost_multiple':multiplier,'independent_starting_account':True}
                result['limitations'].append(audit['warning'])
                folder=out/f'{period}-{variant}-cost{multiplier}'
                folder.mkdir(exist_ok=True)
                (folder/'run.json').write_text(json.dumps(result,indent=2,allow_nan=False))
                for filename,key in [('trades','trades'),('equity','equity_curve'),('execution-audit','execution_audit')]:
                    records=result[key]
                    write_table(folder/(filename+'.csv'),records,list(records[0]) if records else ['status'])
                (folder/'SUMMARY.md').write_text(render(result))
                stats=statistics(result['trades'])
                summary=result['summary']
                status='no_trades' if not stats['trades'] else ('small_sample' if stats['trades']<args.minimum_trades else 'exploratory_not_validated')
                row={'period':period,'first_date':chosen_days[0],'last_date':chosen_days[-1],'variant':variant,'cost_multiple':multiplier,**summary,'win_rate':stats['win_rate'],'expectancy':stats['expectancy'],'sample_status':status}
                rows.append(row)
                wr=f"{stats['win_rate']:.1%}" if stats['win_rate'] is not None else 'N/A'
                lines.append(f"| {period} | {chosen_days[0]} to {chosen_days[-1]} | {variant} | {multiplier} | {stats['trades']} | {money(summary['ending_equity'])} | {money(summary['net_pnl'])} | {wr} | {money(stats['expectancy'])} | {summary['max_drawdown']:.2%} | {status} |")
    write_table(out/'comparison.csv',rows,list(rows[0]))
    lines+=['','Doubled cost means twice the spread and slippage assumptions; per-order fees stay unchanged. Portfolios are rerun, so sizing, targets, available cash and future entries can change. These are not arithmetic deductions from old trades.', '',
            f'The {args.minimum_trades}-trade sample flag is an operational warning, not a proof of statistical sufficiency. Source full-period runs are development reports, not separate independent evidence.', '',
            'Full per-case trade tables, costs, timing and reports are in the artifact. No OTC fills, quote calibration, point-in-time universe, or live orders are added.']
    publish('\n'.join(lines)+'\n')

if __name__=='__main__':
    main()
