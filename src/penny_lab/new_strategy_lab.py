"""Data-only acquisition followed by the shared-capital strategy blend."""
import argparse
import json
import os
import sys
from pathlib import Path
from . import engine,range_runner,lab_setups,strategy_lab,replacement_setups
from .report import cell

NEW_MIXTURES={k:v for k,v in replacement_setups.CASES.items() if k.endswith('_mix')}

class SnapshotReady(Exception):
    def __init__(self,cfg,manifest,count):
        self.cfg,self.manifest,self.count=cfg,manifest,count

def capture_snapshot(bars,cfg,manifest):
    raise SnapshotReady(cfg,manifest,len(bars))

def descriptor(event):
    return {'artifact_type':'acquisition_only_metadata','strategy_execution_performed':False,'config':event.cfg.to_dict(),'provenance':event.manifest,'eligible_candles':event.count,'note':'Source configuration only. No strategy executed during acquisition; A_baseline/run.json is metadata for the legacy loader.'}

def acquire(argv):
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--output',default='results/research-v2')
    known,_=parser.parse_known_args(argv)
    out=Path(known.output)
    if (out/'A_baseline'/'run.json').exists():
        raise ValueError('Use clean output; do not overwrite existing results')
    old_run,old_argv=engine.run,sys.argv
    event=None
    try:
        engine.run=capture_snapshot
        sys.argv=[old_argv[0],*argv]
        range_runner.main()
    except SnapshotReady as ready:
        event=ready
    finally:
        engine.run=old_run
        sys.argv=old_argv
    out.mkdir(parents=True,exist_ok=True)
    if event:
        payload=json.dumps(descriptor(event),indent=2,allow_nan=False)
        (out/'snapshot.json').write_text(payload)
        compatibility=out/'A_baseline'
        compatibility.mkdir(exist_ok=True)
        (compatibility/'run.json').write_text(payload)
    path=out/'coverage.json'
    coverage=json.loads(path.read_text()) if path.exists() else {}
    lines=['## Blended strategy lab: acquisition only','','No strategy was simulated during acquisition. The comparison step runs the ORB/bull-flag/VWAP shared-capital blend.', '',f'Eligible candles: {event.count if event else 0}. Evaluation start: {cell(coverage.get("evaluation_start","unavailable"))}. End exclusive: {cell(coverage.get("evaluation_end_exclusive","unavailable"))}.','','| Symbol | Data status | Provider | Eligible sessions | Reason |','|---|---|---|---:|---|']
    for row in coverage.get('coverage',[]):
        lines.append('| '+' | '.join(cell(row.get(k,'')) for k in ('symbol','status','provider','evaluation_sessions_used','reason'))+' |')
    if not event:
        lines+=['','No usable snapshot; no performance invented.']
    text='\n'.join(lines)+'\n'
    (out/'ACQUISITION.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(text)

def compare(argv):
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',default='results/research-v2')
    args=parser.parse_args(argv)
    source=Path(args.input)
    source.mkdir(parents=True,exist_ok=True)
    if (source/'snapshot.json').exists():
        if json.loads((source/'snapshot.json').read_text()).get('strategy_execution_performed') is not False:
            raise ValueError('Require acquisition-only snapshot')
    original_cases=dict(lab_setups.CASES)
    old_pattern,old_names=strategy_lab.pattern,strategy_lab.names_at
    old_argv=sys.argv
    try:
        lab_setups.CASES.clear()
        lab_setups.CASES.update(replacement_setups.CASES)
        strategy_lab.pattern=replacement_setups.pattern
        strategy_lab.names_at=replacement_setups.names_at
        sys.argv=[old_argv[0],'--input',args.input]
        selected={'cases':replacement_setups.CASES,'portfolio_mode':'shared_cash_one_position_per_symbol','entry_families':['15-minute opening-range breakout','bull-flag first pullback','session VWAP reclaim'],'cost_multiples':[1,2],'no_minimum_rr':True,'signal_tie_break':'descending volume score then strategy name; existing engine','profitability_verified':False}
        (source/'active-setups.json').write_text(json.dumps(selected,indent=2))
        strategy_lab.main()
    finally:
        lab_setups.CASES.clear()
        lab_setups.CASES.update(original_cases)
        strategy_lab.pattern=old_pattern
        strategy_lab.names_at=old_names
        sys.argv=old_argv

def main():
    if len(sys.argv)<2 or sys.argv[1] not in ('acquire','compare'):
        raise SystemExit('Usage: new_strategy_lab acquire [data arguments] OR compare [--input PATH]')
    (acquire if sys.argv[1]=='acquire' else compare)(sys.argv[2:])

if __name__=='__main__':
    main()
