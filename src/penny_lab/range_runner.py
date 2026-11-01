"""Active research policy: USD 1-35, frozen prior high, same-day exits."""
import argparse
import json
import os
from pathlib import Path
from .config import Config
from .target_policy import POLICY
from .report import cell
from . import research_v2

def discover(yf,limit):
    symbols,events=[],[]
    for label,otc in (('otc_1_to_35',True),('us_1_to_35',False)):
        try:
            rules=[yf.EquityQuery('eq',['region','us']),yf.EquityQuery('btwn',['intradayprice',1,35])]
            if otc:
                rules.append(yf.EquityQuery('eq',['exchange','PNK']))
            result=yf.screen(yf.EquityQuery('and',rules),size=limit,sortField='dayvolume',sortAsc=False)
            found=[r['symbol'] for r in result.get('quotes',[]) if r.get('symbol')]
            symbols.extend(found)
            events.append({'source':label,'status':'ok','count':len(found)})
        except Exception as exc:
            events.append({'source':label,'status':'failed','error':str(exc)})
    return list(dict.fromkeys(symbols)),events

def report_policy():
    out=Path('results/research-v2')
    out.mkdir(parents=True,exist_ok=True)
    lines=['## Active price and structural-target policy','','USD 1–35 inclusive at discovery and RAW historical entry. Entry execution cost can put the modeled purchase price slightly outside that raw-price range. Uptrend entries only; target is the highest high of the 12 completed bars before the pullback/confirmation, frozen at the signal. Minimum planned net reward/risk is 1.0 after modeled costs and fees. Stop is unchanged. Same-day session-end exit; no overnight or three-day holding.','','| Portfolio | Trade | Symbol | Historical target | Reference time | Planned net RR | Expected net reward | Planned risk |','|---|---:|---|---:|---|---:|---:|---:|']
    for path in sorted(out.glob('*/run.json')):
        result=json.loads(path.read_text())
        for r in result.get('execution_audit',[])[:200]:
            keys=('trade_number','symbol','target','reference_time','expected_net_rr','expected_net_reward','planned_net_risk')
            lines.append('| '+cell(path.parent.name)+' | '+' | '.join(cell(r.get(k,'N/A')) for k in keys)+' |')
    lines+=['','Full target references and planned RR are in execution_audit in run.json and execution-audit.csv. Realized RR can differ, and planned loss is not guaranteed. Legacy runner labels mentioning under-25 or legacy engine warnings do not override this policy or the recorded engine version.']
    text='\n'.join(lines)+'\n'
    (out/'TARGET_POLICY.md').write_text(text)
    with (out/'SUMMARY.md').open('a') as f:
        f.write('\n'+text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(text)

def main():
    import sys
    if '--report-only' in sys.argv:
        report_policy()
        return
    original_cfg,original_discover,original_run=research_v2.Config,research_v2.discover,research_v2.engine.run
    def config(*args,**kwargs):
        kwargs['max_price']=35.
        kwargs['strategies']=('uptrend_pullback',)
        return Config(*args,**kwargs)
    def run(bars,cfg,manifest):
        return original_run(bars,cfg,{**manifest,'entry_policy':dict(POLICY),'historical_entry_ceiling':35.,'historical_entry_floor':1.})
    try:
        research_v2.Config=config
        research_v2.discover=discover
        research_v2.engine.run=run
        research_v2.main()
    finally:
        research_v2.Config=original_cfg
        research_v2.discover=original_discover
        research_v2.engine.run=original_run

if __name__=='__main__':
    main()
