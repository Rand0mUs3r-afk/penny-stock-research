"""Render existing backtest output; never invent results for a failed run."""
import argparse
import html
import json
import os
from pathlib import Path
from statistics import mean

def cell(value):
    return html.escape(str(value)).replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ')

def money(value):
    return 'N/A' if value is None else f'${value:,.2f}'

def statistics(trades):
    pnl = [float(t['net_pnl']) for t in trades]
    wins = [v for v in pnl if v > 0]
    losses = [v for v in pnl if v < 0]
    gross_loss = -sum(losses)
    return {'trades': len(pnl), 'wins': len(wins), 'losses': len(losses),
            'breakeven': sum(v == 0 for v in pnl),
            'win_rate': len(wins) / len(pnl) if pnl else None,
            'average_win': mean(wins) if wins else None,
            'average_loss': mean(losses) if losses else None,
            'expectancy': mean(pnl) if pnl else None,
            'best': max(pnl) if pnl else None, 'worst': min(pnl) if pnl else None,
            'gross_profit': sum(wins), 'gross_loss': gross_loss,
            'profit_factor': sum(wins) / gross_loss if gross_loss else None,
            'no_losses': bool(wins) and not losses}

def render(result=None, coverage=None):
    lines = ['# Yahoo pilot results', '',
             'Exploratory listed-stock backtest only. OTC downloads are coverage-only. Costs and fills are modeled; these are not broker executions.', '']
    if result is None:
        lines += ['## No completed backtest', '',
                  'No final equity or trade statistics are available. This is not a zero-trade performance result. Check coverage below and the workflow logs.', '']
    else:
        trades = result.get('trades', [])
        stats = statistics(trades)
        summary = result['summary']
        start, end = summary['starting_equity'], summary['ending_equity']
        pf = f"{stats['profit_factor']:.2f}" if stats['profit_factor'] is not None else ('N/A (no losing trades)' if stats['no_losses'] else 'N/A')
        rate = f"{100 * stats['win_rate']:.2f}%" if stats['win_rate'] is not None else 'N/A'
        rows = [
            ('Starting equity', money(start)), ('Final equity', money(end)),
            ('Net P&L', money(end - start)), ('Return', f'{100 * (end / start - 1):.2f}%' if start else 'N/A'),
            ('Closed trades', stats['trades']), ('Winning trades', stats['wins']),
            ('Losing trades', stats['losses']), ('Breakeven trades', stats['breakeven']),
            ('Win percentage', rate), ('Average winning trade', money(stats['average_win'])),
            ('Average losing trade (signed)', money(stats['average_loss'])),
            ('Average P&L per trade', money(stats['expectancy'])),
            ('Gross profit', money(stats['gross_profit'])), ('Gross loss magnitude', money(stats['gross_loss'])),
            ('Profit factor', pf), ('Best trade', money(stats['best'])), ('Worst trade', money(stats['worst'])),
            ('Maximum equity drawdown', f"{100 * summary['max_drawdown']:.2f}%")]
        lines += ['## Portfolio performance', '', '| Metric | Value |', '|---|---:|']
        lines += [f'| {key} | {value} |' for key, value in rows]
        lines += ['', 'Win percentage = positive-net-P&L trades / all closed trades, including breakevens. All trade statistics use net P&L after the simulator’s costs. N/A means the relevant sample or denominator does not exist.', '']
        config = result.get('config', {})
        lines += [f"Allocation ceiling: {money(config.get('allocation'))}; planned risk per position: {money(config.get('risk_per_position'))}. Realized losses can exceed planned risk.", '']
        lines += ['## Strategy attribution', '', 'Strategies share one cash portfolio; this is not an independent strategy comparison.', '', '| Strategy | Trades | Net P&L | Win rate | Average P&L |', '|---|---:|---:|---:|---:|']
        for r in result.get('strategy_ranking', []):
            wr = f"{100 * r['win_rate']:.2f}%" if r.get('win_rate') is not None else 'N/A'
            lines.append(f"| {cell(r['strategy'])} | {r['trades']} | {money(r['net_pnl'])} | {wr} | {money(r.get('expectancy'))} |")
        lines += ['', '## Trades', '']
        if not trades:
            lines += ['Backtest completed, but no trades met the entry and risk rules.', '']
        else:
            limit = 500
            lines += ['Timestamps retain their recorded timezone offsets. Exit times are bar-end approximations, not exact intrabar fill times.', '', '| # | Symbol | Setup | Entry time | Exit time | Shares | Entry | Exit | Stop | Target | Net P&L | Exit reason |', '|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---|']
            for n, t in enumerate(trades[:limit], 1):
                values = [n, t['symbol'], t['strategy'], t['entry_time'], t['exit_time'], t['shares'],
                          f"{t['entry']:.6f}", f"{t['exit']:.6f}", f"{t['stop']:.6f}", f"{t['target']:.6f}",
                          money(t['net_pnl']), t['exit_reason']]
                lines.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
            if len(trades) > limit:
                lines += ['', f'Showing the first {limit} of {len(trades)} trades to keep the Actions summary within size limits. The artifact contains every trade.']
            lines += ['', 'Entry explanations, signal times, and planned risk for every trade are in trades.csv and run.json.', '']
    if coverage:
        rows = coverage.get('coverage', [])
        lines += ['## Data coverage', '', f'Candidates checked: {len(rows)}. Listed accepted: {sum(r.get("status") == "accepted_listed" for r in rows)}. OTC coverage-only: {sum(r.get("status") == "coverage_only" for r in rows)}.', '', '| Symbol | Market | Status | Reason |', '|---|---|---|---|']
        for r in rows[:200]:
            lines.append('| ' + ' | '.join(cell(r.get(k, '')) for k in ('symbol', 'market', 'status', 'reason')) + ' |')
        for event in coverage.get('discovery', []):
            if event.get('status') == 'failed':
                lines += ['', f"Scanner failure ({cell(event.get('source'))}): {cell(event.get('error'))}"]
    lines += ['', '## Limitations', '', 'Current-symbol selection and complete-session filtering create selection bias. Rankings are exploratory/in-sample, not evidence of future profitability. No live orders or historical news signals. Download the run artifact for the full audit and trade ledger.', '']
    return '\n'.join(lines)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='results/yahoo-pilot')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    def read(name):
        path = out / name
        return json.loads(path.read_text()) if path.exists() else None
    text = render(read('run.json'), read('coverage.json'))
    (out / 'SUMMARY.md').write_text(text, encoding='utf-8')
    target = os.environ.get('GITHUB_STEP_SUMMARY')
    if target:
        with open(target, 'a', encoding='utf-8') as f:
            f.write(text)
    else:
        print(text)

if __name__ == '__main__':
    main()
