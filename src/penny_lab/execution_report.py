"""Append reconciled execution costs and timing bounds to diagnostics summaries."""
import argparse
import json
import os
from collections import Counter
from pathlib import Path
from .report import cell, money
from .yahoo_pilot import write_table

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='results/research-v2')
    args=parser.parse_args()
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    lines=['## Execution-engine corrections and cost reconciliation','',
        'Engine execution-audit-v3 removes the direct execution-candle volume entry check, separates stop reasons, and fails on unresolved gaps while holding. Earlier generic runner warnings about that direct volume check are superseded for runs with this engine version. Retrospective whole-session data selection remains.','',
        '| Portfolio | Engine | Gross price P&L | Spread cost | Slippage cost | Fees | Net P&L | Reconciliation error |','|---|---|---:|---:|---:|---:|---:|---:|']
    found=False
    for path in sorted(out.glob('*/run.json')):
        result=json.loads(path.read_text())
        costs=result.get('cost_attribution')
        if costs is None:
            continue
        found=True
        rows=result.get('execution_audit',[])
        write_table(path.parent/'execution-audit.csv',rows,list(rows[0]) if rows else ['status'])
        lines.append('| '+cell(path.parent.name)+' | '+cell(result.get('engine_version'))+' | '+' | '.join(money(costs[k]) for k in ('gross_price_pnl','modeled_spread_cost','modeled_slippage_cost','fees','net_pnl','reconciliation_error'))+' |')
    for path in sorted(out.glob('*/run.json')):
        result=json.loads(path.read_text())
        if 'execution_audit' not in result:
            continue
        rows=result['execution_audit']
        reasons=dict(Counter(r['exit_reason'] for r in rows))
        lines+=['','### '+cell(path.parent.name)+' execution details','',
                'Exit reasons: '+cell(reasons), '',
                'Trades exceeding planned loss: '+str(sum(r['loss_exceeded_planned'] for r in rows)), '',
                '| Trade | Symbol | Setup | Hold lower–upper, min | Gross P&L | Spread | Slippage | Fees | Net | Exit reason |',
                '|---:|---|---|---|---:|---:|---:|---:|---:|---|']
        for r in rows[:200]:
            values=[r['trade_number'],r['symbol'],r['strategy'],f"{r['hold_minutes_lower_bound']:.0f}–{r['hold_minutes_upper_bound']:.0f}",
                    *[money(r[k]) for k in ('gross_price_pnl','modeled_spread_cost','modeled_slippage_cost','fees','net_pnl')],r['exit_reason']]
            lines.append('| '+' | '.join(cell(v) for v in values)+' |')
        if len(rows)>200:
            lines+=['','First 200 rows shown; every trade is in execution-audit.csv and run.json.']
    if not found:
        lines+=['','No completed audited portfolios found; inspect logs and coverage. No execution metrics fabricated.']
    lines+=['','Costs are hypothetical attribution at recorded fills, not measured historical quotes. Order time assumes zero modeled latency at the signal boundary. Partial-session/quote fills, point-in-time selection, OTC execution and holdout validation are still not implemented.']
    text='\n'.join(lines)+'\n'
    (out/'EXECUTION_AUDIT.md').write_text(text)
    with (out/'SUMMARY.md').open('a') as f:
        f.write('\n'+text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(text)

if __name__=='__main__':
    main()
