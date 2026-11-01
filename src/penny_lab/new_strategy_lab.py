"""Acquisition without strategy execution, then distinct new setup portfolios."""
import argparse
import json
import os
import sys
from pathlib import Path
from . import engine,range_runner,lab_setups,strategy_lab
from .report import cell

NEW_MIXTURES={
 'breakout_recovery_mix':('opening_range_breakout','failed_breakdown_recovery'),
 'breakout_recovery_compression_mix':('opening_range_breakout','failed_breakdown_recovery','compression_continuation')}

class SnapshotReady(Exception):
    def __init__(self,cfg,manifest,count):
        self.cfg,self.manifest,self.count=cfg,manifest,count

def capture_snapshot(bars,cfg,manifest):
    # Abort before the first engine simulation, without inventing equity/trades.
    raise SnapshotReady(cfg,manifest,len(bars))

def descriptor(event):
    return {'artifact_type':'acquisition_only_metadata','strategy_execution_performed':False,
            'config':event.cfg.to_dict(),'provenance':event.manifest,'eligible_candles':event.count,
            'note':'Configuration is source metadata only. No uptrend strategy, trades or equity simulation was executed. A_baseline/run.json is a legacy loader compatibility descriptor, NOT a backtest result.'}

def acquire(argv):
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--output',default='results/research-v2')
    known,_=parser.parse_known_args(argv)
    out=Path(known.output)
    if (out/'A_baseline'/'run.json').exists():
        raise ValueError('Use a clean output directory; never overwrite/relabel a previous baseline backtest')
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
        data=descriptor(event)
        (out/'snapshot.json').write_text(json.dumps(data,indent=2,allow_nan=False))
        compatibility=out/'A_baseline'
        compatibility.mkdir(exist_ok=True)
        (compatibility/'run.json').write_text(json.dumps(data,indent=2,allow_nan=False))
    coverage_path=out/'coverage.json'
    coverage=json.loads(coverage_path.read_text()) if coverage_path.exists() else {}
    lines=['## New strategy lab — data acquisition only','','No old uptrend strategy or A/B/C portfolio simulation was run. Coverage and historical references were prepared for the NEW setup experiments only.', '',
           f'Eligible candles: {event.count if event else 0}. Evaluation start: {cell(coverage.get("evaluation_start","unavailable"))}. End exclusive: {cell(coverage.get("evaluation_end_exclusive","unavailable"))}.', '',
           '| Symbol | Data status | Provider | Eligible sessions | Reason |','|---|---|---|---:|---|']
    for row in coverage.get('coverage',[]):
        lines.append('| '+' | '.join(cell(row.get(k,'')) for k in ('symbol','status','provider','evaluation_sessions_used','reason'))+' |')
    if not event:
        lines+=['','No eligible snapshot; new strategy results will not be fabricated. Inspect coverage artifacts.']
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
    if (source/'snapshot.json').exists():
        metadata=json.loads((source/'snapshot.json').read_text())
        if metadata.get('strategy_execution_performed') is not False:
            raise ValueError('Snapshot must be acquisition-only')
    original_cases=dict(lab_setups.CASES)
    old_argv=sys.argv
    try:
        lab_setups.CASES.update(NEW_MIXTURES)
        sys.argv=[old_argv[0],'--input',args.input]
        strategy_lab.main()
    finally:
        lab_setups.CASES.clear()
        lab_setups.CASES.update(original_cases)
        sys.argv=old_argv

def main():
    if len(sys.argv)<2 or sys.argv[1] not in ('acquire','compare'):
        raise SystemExit('Usage: new_strategy_lab acquire [data arguments] OR compare [--input PATH]')
    action,args=sys.argv[1],sys.argv[2:]
    (acquire if action=='acquire' else compare)(args)

if __name__=='__main__':
    main()
