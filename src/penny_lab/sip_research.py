"""Component/blend, activity-selection, cost and chronological experiments."""
import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import date,datetime
from pathlib import Path
from statistics import mean
from . import engine,sip_inputs,sip_setups,sip_benchmark,new_strategy_lab
from .models import Signal
from .sip_selection import make_selection
from .lab_setups import overhead_reference,NY
from .strategy_lab import historical_levels
from .validation import load_snapshot,stressed_config,split_days
from .report import render,statistics
from .yahoo_pilot import write_table

def dump(path,data):
    path.write_text(json.dumps(data,indent=2,allow_nan=False))

def table(path,rows):
    write_table(path,rows,list(rows[0]) if rows else ['status'])

def experiment_cases():
    cases=dict(sip_setups.CASES)
    for blend in ('blend_orb5','blend_orb15'):
        names,stop=cases[blend]
        for component in names:
            cases[blend+'_without_'+component]=(tuple(n for n in names if n!=component),stop)
    return cases

def compare(args):
    source=Path(args.input)
    out=source/'stocks-in-play'
    out.mkdir(parents=True,exist_ok=True)
    if not (source/'A_baseline'/'run.json').exists():
        (out/'SUMMARY.md').write_text('# Stocks-in-play research\n\nNo usable acquisition snapshot. See coverage.json.\n')
        return
    bars,refs,base,manifest=load_snapshot(source)
    ctx=sip_inputs.contexts(source,sorted({b.symbol for b in bars}))
    events=sip_inputs.news_events(args.catalysts)
    features,selection=make_selection(bars,refs,ctx,args.top_n,args.minimum_rvol,args.require_catalyst,events)
    table(out/'selection.csv',selection)
    table(out/'contexts.csv',[{'symbol':s,'day':d,**v} for (s,d),v in sorted(ctx.items())])
    levels=historical_levels(source,sorted({b.symbol for b in bars}))
    days=sorted({b.timestamp.astimezone(NY).date().isoformat() for b in bars})
    periods={'full':days,**split_days(days)}
    if 'full_sample_only' in periods:
        del periods['full_sample_only']
    if args.holdout_start:
        args.holdout_start=date.fromisoformat(args.holdout_start).isoformat()
        periods={'development':[d for d in days if d<args.holdout_start],'declared_holdout':[d for d in days if d>=args.holdout_start]}
        if not all(periods.values()):
            raise ValueError('Holdout boundary must leave data on both sides')
    policy=dict(manifest['entry_policy'])
    policy['minimum_net_rr']=None
    manifest={**manifest,'entry_policy':policy,'experiment':'stocks_in_play_multistrategy','target_rule':'nearest known overhead historical high'}
    fingerprints={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file() and p.suffix in ('.csv','.json')}
    if args.catalysts:
        fingerprints['catalysts_input']=hashlib.sha256(Path(args.catalysts).read_bytes()).hexdigest()
    cases=experiment_cases()
    audit={'cases':cases,'periods':periods,'selection':{'top_n':args.top_n,'minimum_rvol':args.minimum_rvol,'require_catalyst':args.require_catalyst},'hashes':fingerprints,'holdout_boundary':args.holdout_start,'holdout_independence_verified':False,'no_automatic_winner':True,'main_policy_preserved':True}
    dump(out/'experiment.json',audit)
    summaries=[]
    for period,dates in periods.items():
        selected_days=set(dates)
        chosen=[b for b in bars if b.timestamp.astimezone(NY).date().isoformat() in selected_days]
        for mode in ('unfiltered','stocks_in_play'):
            for case,(names,stop_mode) in cases.items():
                for cost in (1,2):
                    cfg=replace(stressed_config(base,cost),strategies=names)
                    references,decisions,used={},[],set()
                    def scanner(history,config):
                        b=history[-1]
                        feature=features[(b.symbol,b.timestamp)]
                        if not feature[mode+'_eligible']:
                            return []
                        signals=[]
                        for name in names:
                            setup=sip_setups.detect(history,name,feature,stop_mode)
                            if not setup:
                                if name=='sip_gap_go' and feature.get('premarket_high') is None:
                                    decisions.append({'symbol':b.symbol,'timestamp':b.timestamp.isoformat(),'setup':name,'reason':'premarket_unavailable'})
                                continue
                            key=(b.symbol,b.timestamp.astimezone(NY).date().isoformat(),setup['event'])
                            if key in used:
                                continue
                            ref=overhead_reference(history,levels.get((b.symbol,b.timestamp.astimezone(NY).date().isoformat())))
                            if not ref:
                                decisions.append({'symbol':b.symbol,'timestamp':b.timestamp.isoformat(),'setup':name,'reason':'no_known_overhead_target'})
                                continue
                            used.add(key)
                            references[(b.symbol,b.timestamp)]=ref
                            signals.append(Signal(b.symbol,name,b.timestamp,setup['stop'],feature.get('rvol') or 0,setup['reason']))
                            decisions.append({'symbol':b.symbol,'timestamp':b.timestamp.isoformat(),'setup':name,'reason':'candidate','rvol':feature.get('rvol'),'gap':feature.get('gap')})
                        return signals
                    original_scan,original_high=engine.scan,engine.previous_high
                    try:
                        engine.scan=scanner
                        engine.previous_high=lambda history,lookback: references.get((history[-1].symbol,history[-1].timestamp))
                        result=engine.run(chosen,cfg,manifest)
                    finally:
                        engine.scan=original_scan
                        engine.previous_high=original_high
                    result['experiment_case']={'period':period,'selector':mode,'case':case,'stop_mode':stop_mode,'cost_multiple':cost,'shared_capital':len(names)>1}
                    folder=out/f'{period}-{mode}-{case}-cost{cost}'
                    folder.mkdir(exist_ok=True)
                    dump(folder/'run.json',result)
                    (folder/'SUMMARY.md').write_text(render(result))
                    for filename,key in [('trades','trades'),('equity','equity_curve'),('rejections','rejections'),('execution-audit','execution_audit'),('components','strategy_ranking')]:
                        table(folder/(filename+'.csv'),result[key])
                    table(folder/'decisions.csv',decisions)
                    attribution=[]
                    for trade in result['trades']:
                        f=features[(trade['symbol'],datetime.fromisoformat(trade['signal_time']))]
                        ratio=f.get('rvol')
                        attribution.append({**trade,'same_time_rvol':ratio,'activity_bucket':'missing' if ratio is None else '<2' if ratio<2 else '2-5' if ratio<5 else '>=5','gap':f.get('gap'),'selection_rank':f.get('rank'),'day':datetime.fromisoformat(trade['exit_time']).astimezone(NY).date().isoformat()})
                    table(folder/'trade-attribution.csv',attribution)
                    totals={}
                    for dimension in ('symbol','day','strategy','activity_bucket'):
                        grouped=defaultdict(float)
                        for t in attribution:
                            grouped[t[dimension]]+=t['net_pnl']
                        totals[dimension]=dict(grouped)
                    dump(folder/'attribution.json',totals)
                    stats=statistics(result['trades'])
                    hold=mean(t['hold_minutes_upper_bound'] for t in result['execution_audit']) if result['execution_audit'] else None
                    summaries.append({**result['experiment_case'],**result['summary'],'profit_factor':stats['profit_factor'],'expectancy':stats['expectancy'],'win_rate':stats['win_rate'],'mean_hold_minutes':hold})
    table(out/'comparison.csv',summaries)
    lookup={(r['period'],r['selector'],r['case'],r['cost_multiple']):r for r in summaries}
    incremental=[]
    for r in summaries:
        if '_without_' not in r['case']:
            continue
        blend,component=r['case'].split('_without_',1)
        full=lookup[(r['period'],r['selector'],blend,r['cost_multiple'])]
        incremental.append({'period':r['period'],'selector':r['selector'],'blend':blend,'component':component,'cost_multiple':r['cost_multiple'],'incremental_net_pnl':full['net_pnl']-r['net_pnl'],'incremental_trades':full['trades']-r['trades'],'drawdown_change':full['max_drawdown']-r['max_drawdown']})
    table(out/'component-incremental.csv',incremental)
    try:
        bb,closes,actions=sip_inputs.benchmark_bars(source)
    except FileNotFoundError:
        bb,closes,actions=[],{},[]
    if bb:
        for period,dates in periods.items():
            for cost in (1,2):
                cfg=replace(stressed_config(base,cost),allocation=base.starting_equity)
                subset=[b for b in bb if b.timestamp.astimezone(NY).date().isoformat()<=max(dates)]
                result=sip_benchmark.run(subset,cfg,closes,evaluation_start=min(dates),action_days=actions)
                result['statistics']=statistics(result['trades'])
                result['experiment_case']={'period':period,'cost_multiple':cost,'account_allocation_ceiling':cfg.allocation}
                dump(out/f'benchmark-{period}-cost{cost}.json',result)
                table(out/f'benchmark-{period}-cost{cost}-trades.csv',result['trades'])
    else:
        dump(out/'benchmark-status.json',{'status':'unavailable','reason':'No saved SPY benchmark data; see sip-inputs.json'})
    lines=['# Stocks-in-play multistrategy research','','| Period | Selector | Case | Cost | Trades | Net P&L | Drawdown |','|---|---|---|---:|---:|---:|---:|']
    for r in summaries:
        lines.append(f"| {r['period']} | {r['selector']} | {r['case']} | {r['cost_multiple']} | {r['trades']} | {r['net_pnl']:.2f} | {r['max_drawdown']:.2%} |")
    lines+=['','Each row has an independent starting account. Blend components share one account. Later-period diagnostics are not automatically untouched validation. SPY benchmark uses separate long-only noise-band/VWAP exits and an account-sized allocation ceiling.']
    text='\n'.join(lines)+'\n'
    (out/'SUMMARY.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(text)

def main():
    if len(sys.argv)>1 and sys.argv[1]=='acquire':
        parser=argparse.ArgumentParser(add_help=False)
        parser.add_argument('--output',default='results/research-v2')
        known,_=parser.parse_known_args(sys.argv[2:])
        new_strategy_lab.acquire(sys.argv[2:])
        source=Path(known.output)
        if (source/'coverage.json').exists():
            sip_inputs.acquire_extras(source)
        return
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',default='results/research-v2')
    parser.add_argument('--top-n',type=int,default=20)
    parser.add_argument('--minimum-rvol',type=float,default=2.)
    parser.add_argument('--catalysts',default='')
    parser.add_argument('--require-catalyst',action='store_true')
    parser.add_argument('--holdout-start',default='')
    compare(parser.parse_args())

if __name__=='__main__':
    main()
