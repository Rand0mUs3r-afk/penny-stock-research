"""Three independent exploratory portfolios on identical warmup-eligible data."""
import argparse
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo
from . import engine
from .config import Config
from .multi_pilot import validate_sessions
from .report import render, statistics, money
from .yahoo_pilot import write_table

NY = ZoneInfo('America/New_York')
VARIANTS = ('A_baseline', 'B_rvol', 'C_rvol_vwap')

def vwap(history):
    volume = sum(b.volume for b in history)
    return sum((b.high + b.low + b.close) / 3 * b.volume for b in history) / volume if volume > 0 else None

def filter_decision(history, denominator, variant):
    if variant not in VARIANTS:
        raise ValueError('Unknown experiment variant')
    ratio = sum(b.volume for b in history) / denominator if denominator and denominator > 0 else None
    if variant == 'A_baseline':
        return True, 'baseline', ratio
    if ratio is None or ratio < 2.0:
        return False, 'same_time_rvol_below_2_or_unavailable', ratio
    if variant == 'C_rvol_vwap':
        current = vwap(history)
        earlier = vwap(history[:-3]) if len(history) > 3 else None
        if current is None or earlier is None or not (history[-1].close > current > earlier):
            return False, 'not_above_rising_session_vwap', ratio
    return True, 'filters_passed', ratio

def comparison_sample(groups, days):
    """Require the preceding 20 calendar sessions, never future sessions."""
    bars, denominators, eligibility = [], {}, []
    symbols = sorted({symbol for symbol, day in groups})
    for i, day in enumerate(days):
        for symbol in symbols:
            today = groups.get((symbol, day))
            if not today:
                continue
            prior = [groups.get((symbol, d)) for d in days[max(0, i - 20):i]]
            minute = lambda b: b.timestamp.astimezone(NY).strftime('%H:%M')
            current_slots = {minute(b) for b in today}
            available = len(prior) == 20 and all(p and current_slots <= {minute(b) for b in p} for p in prior)
            eligibility.append({'symbol': symbol, 'day': day, 'eligible': bool(available), 'reason': 'eligible' if available else 'need_20_prior_complete_same_time_sessions'})
            if not available:
                continue
            totals = defaultdict(list)
            for past in prior:
                cumulative = 0.0
                for bar in past:
                    cumulative += bar.volume
                    totals[minute(bar)].append(cumulative)
            for bar in today:
                denominators[(symbol, day, minute(bar))] = mean(totals[minute(bar)])
            bars.extend(today)
    return sorted(bars, key=lambda b: (b.timestamp, b.symbol)), denominators, eligibility

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='results/yahoo-pilot')
    parser.add_argument('--output', default='results/filter-comparison')
    args = parser.parse_args()
    source, out = Path(args.input), Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    def publish(text):
        (out / 'SUMMARY.md').write_text(text)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
                f.write(text)
    if not (source / 'run.json').exists():
        publish('# Uptrend filter comparison\n\nNo completed source backtest. No comparison performance fabricated. Inspect source coverage and workflow logs.\n')
        return
    import pandas as pd
    import pandas_market_calendars as mcal
    baseline = json.loads((source / 'run.json').read_text())
    audit = json.loads((source / 'coverage.json').read_text())
    cfg_values = baseline['config']
    cfg_values['strategies'] = ('uptrend_pullback',)
    cfg = Config(**cfg_values)
    start, end = pd.Timestamp(audit['requested_start']), pd.Timestamp(audit['requested_end'])
    schedule = mcal.get_calendar('NYSE').schedule(start_date=start.date(), end_date=end.date())
    calendar = {s.market_open.date().isoformat(): s for _, s in schedule.iterrows() if s.market_open >= start and s.market_close < end}
    days = sorted(calendar)
    groups = defaultdict(list)
    closes, hashes = {}, {}
    for row in audit['coverage']:
        if row.get('status') != 'accepted_listed':
            continue
        symbol = row['symbol']
        safe = ''.join(c for c in symbol if c.isalnum() or c in '-_.')
        path = source / ('history-' + safe + '.csv')
        hashes[symbol] = hashlib.sha256(path.read_bytes()).hexdigest()
        frame = pd.read_csv(path, index_col=0)
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame = frame.sort_index()
        validated, session_closes, rejected = validate_sessions(frame, calendar, symbol)
        closes.update(session_closes)
        for bar in validated:
            groups[(symbol, bar.timestamp.astimezone(NY).date().isoformat())].append(bar)
    bars, denominators, eligibility = comparison_sample(groups, days)
    write_table(out / 'eligibility.csv', eligibility, ['symbol', 'day', 'eligible', 'reason'])
    experiment_audit = {'variants': VARIANTS, 'history_sha256': hashes, 'source_provenance': baseline['provenance'], 'rules': {'lookback_sessions': 20, 'same_time_rvol_minimum': 2.0, 'vwap_slope_bars': 3}, 'warmup_traded': False, 'identical_input_bars_per_variant': len(bars), 'limitations': ['Current universe, complete-session filtering, and corporate-action exclusions create bias', 'First 20 sessions and unavailable prior sessions are excluded from ALL variants', 'Provider/feeds must match within each symbol history; see source provenance', 'Candle-typical-price VWAP is an approximation, not trade-level VWAP', 'No quote spreads, no live orders, no historical news gating', 'Exploratory development test; no holdout validation or statistical significance claim']}
    (out / 'experiment.json').write_text(json.dumps(experiment_audit, indent=2))
    if not bars:
        publish('# Uptrend filter comparison\n\nNo sessions have 20 prior complete same-time sessions. Increase history; try 59 recent days or Alpaca historical start. No performance fabricated. See eligibility.csv.\n')
        return
    manifest = dict(baseline['provenance'])
    manifest['session_closes'] = closes
    manifest['filter_comparison'] = experiment_audit['rules']
    manifest['sample_note'] = 'Same warmup-eligible bars in every portfolio; no warmup trades'
    original_scan = engine.scan
    summaries, sections = [], []
    for variant in VARIANTS:
        blocked = []
        def filtered_scan(history, config):
            signals = original_scan(history, config)
            if not signals:
                return []
            bar = history[-1]
            local = bar.timestamp.astimezone(NY)
            key = (bar.symbol, local.date().isoformat(), local.strftime('%H:%M'))
            allowed, reason, ratio = filter_decision(history, denominators.get(key), variant)
            if not allowed:
                blocked.append({'timestamp': bar.timestamp.isoformat(), 'symbol': bar.symbol, 'reason': reason, 'same_time_rvol': ratio})
                return []
            return [replace(s, reason=s.reason + f'; experiment={variant}; same_time_rvol={ratio:.4f}') for s in signals]
        try:
            engine.scan = filtered_scan
            result = engine.run(bars, cfg, manifest)
        finally:
            engine.scan = original_scan
        result['limitations'].extend(experiment_audit['limitations'])
        result['experiment_variant'] = variant
        folder = out / variant
        folder.mkdir(exist_ok=True)
        (folder / 'run.json').write_text(json.dumps(result, indent=2, allow_nan=False))
        for filename, key in (('trades', 'trades'), ('equity', 'equity_curve'), ('rejections', 'rejections'), ('ranking', 'strategy_ranking')):
            rows = result[key]
            write_table(folder / (filename + '.csv'), rows, list(rows[0]) if rows else ['status'])
        write_table(folder / 'filter-rejections.csv', blocked, ['timestamp', 'symbol', 'reason', 'same_time_rvol'])
        trades = result['trades']
        stats = statistics(trades)
        pnl_by_symbol = defaultdict(float)
        for trade in trades:
            pnl_by_symbol[trade['symbol']] += trade['net_pnl']
        pnl = result['summary']['net_pnl']
        summaries.append({'variant': variant, 'trades': len(trades), 'ending_equity': result['summary']['ending_equity'], 'net_pnl': pnl, 'win_rate': stats['win_rate'], 'expectancy': stats['expectancy'], 'profit_factor': stats['profit_factor'], 'max_drawdown': result['summary']['max_drawdown'], 'filter_rejections': len(blocked), 'pnl_excluding_best_trade_attribution': pnl - max((t['net_pnl'] for t in trades), default=0), 'pnl_excluding_best_ticker_attribution': pnl - max(pnl_by_symbol.values(), default=0)})
        report = render(result).replace('# Yahoo pilot results', '# ' + variant, 1)
        (folder / 'SUMMARY.md').write_text(report)
        sections.append(report)
    write_table(out / 'comparison.csv', summaries, list(summaries[0]))
    lines = ['# Uptrend filter comparison', '', 'A: baseline. B: A + same-time RVOL >= 2. C: B + above/rising VWAP. Independent accounts, identical eligible candles, unchanged sizing/stops/targets/costs.', '', f'Evaluation sessions: {min(b.timestamp.astimezone(NY).date() for b in bars)} through {max(b.timestamp.astimezone(NY).date() for b in bars)}. Warmup is excluded from every variant.', '', '| Variant | Trades | Final equity | Net P&L | Win rate | Avg P&L | Max drawdown | Blocked signals |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in summaries:
        win = f"{100 * row['win_rate']:.2f}%" if row['win_rate'] is not None else 'N/A'
        lines.append(f"| {row['variant']} | {row['trades']} | {money(row['ending_equity'])} | {money(row['net_pnl'])} | {win} | {money(row['expectancy'])} | {100 * row['max_drawdown']:.2f}% | {row['filter_rejections']} |")
    lines += ['', 'Full per-variant trade tables and reports are in the artifact. Concentration diagnostics in comparison.csv remove recorded P&L only; they are NOT rerun counterfactual portfolios. Filters are hypotheses, not validated edges. A no-trade variant is not a profitable strategy. ORB and additional volume-sequence filters are not included.', '']
    publish('\n'.join(lines))

if __name__ == '__main__':
    main()
