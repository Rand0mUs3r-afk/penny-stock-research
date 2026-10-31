"""Coverage-first diagnostic research. Existing execution model is retained."""
import argparse
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from . import engine
from .config import Config
from .models import Bar
from .multi_pilot import discover
from .providers.alpaca import AlpacaData
from .quality import inspect_session, select_coverage, reference_mean, reason_counts
from .report import render, money, statistics, cell
from .yahoo_pilot import classify, write_table

NY = ZoneInfo('America/New_York')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', default='')
    parser.add_argument('--start', default='', help='Evaluation start YYYY-MM-DD, default 14 calendar days before end')
    parser.add_argument('--end', default='', help='Exclusive evaluation end YYYY-MM-DD, default current UTC date')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--allocation', type=float, choices=(250., 300.), default=300.)
    parser.add_argument('--feed', choices=('sip', 'iex'), default='sip')
    parser.add_argument('--min-reference', type=int, choices=(12, 20), default=12)
    parser.add_argument('--output', default='results/research-v2')
    args = parser.parse_args()
    import pandas as pd
    import pandas_market_calendars as mcal
    import yfinance as yf
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    def save(name, obj):
        (out / name).write_text(json.dumps(obj, indent=2, allow_nan=False))
    def publish(text):
        (out / 'SUMMARY.md').write_text(text)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
                handle.write(text)
    now = pd.Timestamp.now(tz='UTC')
    end = pd.Timestamp(args.end, tz='UTC') if args.end else now.normalize()
    start = pd.Timestamp(args.start, tz='UTC') if args.start else end - pd.Timedelta(days=14)
    if start >= end or end > now or start.year < 2016 or not 1 <= args.limit <= 25:
        parser.error('Require 2016 <= start < end <= now and limit 1..25')
    full = mcal.get_calendar('NYSE').schedule(start_date=(start - pd.Timedelta(days=90)).date(), end_date=end.date())
    before = full[full.market_close < start].tail(20)
    if len(before) < 20:
        parser.error('Insufficient exchange-calendar warmup')
    data_start = before.iloc[0].market_open
    schedule = full[(full.market_open >= data_start) & (full.market_close < end)]
    calendar = {s.market_open.date().isoformat(): s for _, s in schedule.iterrows()}
    days = sorted(calendar)
    evaluation_days = [d for d, s in calendar.items() if s.market_open >= start]
    credential_status = bool(os.environ.get('ALPACA_API_KEY') and os.environ.get('ALPACA_SECRET_KEY'))
    alpaca = AlpacaData(args.feed) if credential_status else None
    if args.symbols:
        symbols = list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(',') if s.strip()))
        discovery = [{'source': 'fixed_user_symbols', 'status': 'ok', 'count': len(symbols)}]
    else:
        symbols, discovery = discover(yf, args.limit)
    if len(symbols) > 50:
        parser.error('Maximum 50 symbols; use smaller fixed batches for long history')
    save('universe.json', {'symbols': symbols, 'discovery': discovery, 'point_in_time': False, 'captured_at': now.isoformat()})
    report = {'evaluation_start': start.isoformat(), 'evaluation_end_exclusive': end.isoformat(), 'download_start': data_start.isoformat(), 'warmup_sessions_requested': 20, 'minimum_reference_sessions': args.min_reference, 'credential_pair_present': credential_status, 'providers': [], 'coverage': [], 'metadata_verified': 0, 'action_checks_verified': 0, 'discovery': discovery, 'warnings': ['Current universe, not point-in-time historical selection', 'Complete-session simulation remains retrospective and biased', 'Raw Alpaca prices; Yahoo prices are as supplied, not independently certified as-traded', 'No OTC simulation, no historical-news gating, no broker orders', 'Legacy five-minute engine still has coarse fill assumptions and execution-bar volume check', 'No walk-forward validation or historical quote calibration'] }
    quality_rows, eligible_rows, feature_rows = [], [], []
    bars, denominators, sessions = [], {}, {}
    providers, hashes = {}, {}
    def assess(frame):
        if frame.empty or frame.index.tz is None:
            raise ValueError('No timezone-aware history')
        reasons = []
        for day, session in calendar.items():
            piece = frame[(frame.index >= session.market_open) & (frame.index < session.market_close)]
            expected = pd.date_range(session.market_open, session.market_close, freq='5min', inclusive='left')
            reasons.append({'reason': inspect_session(piece, expected)})
        return sum(r['reason'] == 'usable' for r in reasons) / len(calendar), reason_counts(reasons)
    for symbol in symbols:
        entry = {'symbol': symbol, 'status': 'rejected', 'reason': '', 'market': 'unknown'}
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.get_info()
            market, exchange = classify(info)
            entry.update(market=market, exchange=exchange)
            if market == 'otc':
                entry.update(status='otc_not_simulated', reason='Dedicated OTC execution/data integration required')
                continue
            if market != 'listed' or info.get('quoteType') != 'EQUITY' or info.get('currency') != 'USD':
                raise ValueError('USD listed-equity metadata not verified')
            report['metadata_verified'] += 1
            actions = ticker.history(start=data_start, end=end, interval='1d', auto_adjust=False, actions=True, raise_errors=True)
            if actions.empty or not {'Stock Splits', 'Dividends'} <= set(actions):
                raise ValueError('Corporate-action reference unavailable; fail closed')
            action_rows = []
            for stamp, row in actions.iterrows():
                for col in ('Stock Splits', 'Dividends'):
                    if pd.notna(row[col]) and float(row[col]) != 0:
                        action_rows.append({'day': stamp.date().isoformat(), 'type': col, 'value': float(row[col])})
            report['action_checks_verified'] += 1
            split_days = {a['day'] for a in action_rows if a['type'] == 'Stock Splits'}
            action_days = {a['day'] for a in action_rows}
            entry['actions'] = action_rows
            def yahoo():
                if (now - data_start).days > 59:
                    raise ValueError('Yahoo intraday retention inadequate for requested warmup plus evaluation')
                if split_days:
                    raise ValueError('Split in window: require Alpaca raw history, not unverified Yahoo raw convention')
                return ticker.history(start=data_start, end=end, interval='5m', auto_adjust=False, back_adjust=False, actions=True, prepost=False, raise_errors=True)
            def secondary():
                if alpaca is None:
                    raise ValueError('Alpaca credentials absent')
                items = alpaca.bars([symbol], data_start.isoformat(), end.isoformat())
                return pd.DataFrame([{'Open': b.open, 'High': b.high, 'Low': b.low, 'Close': b.close, 'Volume': b.volume} for b in items], index=pd.DatetimeIndex([b.timestamp - timedelta(minutes=5) for b in items])).sort_index()
            frame, provider, feed, attempts = select_coverage([('Yahoo/yfinance', 'Yahoo aggregates', yahoo), ('Alpaca', args.feed, secondary)], assess)
            report['providers'].append({'symbol': symbol, 'attempts': attempts, 'selected_provider': provider, 'selected_feed': feed})
            if frame is None:
                raise ValueError('Neither provider supplied usable sessions; see provider attempts')
            safe = ''.join(c for c in symbol if c.isalnum() or c in '-_.')
            path = out / ('history-' + safe + '.csv')
            frame.to_csv(path)
            hashes[symbol] = hashlib.sha256(path.read_bytes()).hexdigest()
            providers[symbol] = {'provider': provider, 'feed': feed, 'exchange': exchange}
            cumulative, groups = {}, {}
            for day, session in calendar.items():
                piece = frame[(frame.index >= session.market_open) & (frame.index < session.market_close)]
                expected = pd.date_range(session.market_open, session.market_close, freq='5min', inclusive='left')
                reason = inspect_session(piece, expected)
                quality_rows.append({'symbol': symbol, 'day': day, 'evaluation': day in evaluation_days, 'reason': reason, 'expected_bars': len(expected), 'returned_bars': len(piece), 'provider': provider})
                total, prefix_ok = 0.0, not piece.index.has_duplicates
                for stamp in expected:
                    if not prefix_ok or stamp not in piece.index:
                        prefix_ok = False
                        continue
                    r = piece.loc[stamp]
                    if not all(pd.notna(r[c]) and float(r[c]) > 0 for c in ('Open', 'High', 'Low', 'Close', 'Volume')):
                        prefix_ok = False
                        continue
                    total += float(r.Volume)
                    cumulative[(day, (stamp + pd.Timedelta(minutes=5)).tz_convert('America/New_York').strftime('%H:%M'))] = total
                if reason == 'usable' and day not in action_days:
                    groups[day] = [Bar(symbol, (stamp + pd.Timedelta(minutes=5)).to_pydatetime(), *[float(r[c]) for c in ('Open', 'High', 'Low', 'Close', 'Volume')]) for stamp, r in piece.iterrows()]
            used = 0
            for day in evaluation_days:
                today = groups.get(day)
                if not today:
                    eligible_rows.append({'symbol': symbol, 'day': day, 'reason': 'action_day_excluded' if day in action_days else 'unusable_execution_session'})
                    continue
                day_features = []
                available = True
                for b in today:
                    slot = b.timestamp.astimezone(NY).strftime('%H:%M')
                    avg, count = reference_mean(days, day, slot, cumulative, split_days, minimum=args.min_reference)
                    if avg is None:
                        available = False
                    day_features.append((b, avg, count, slot))
                if not available:
                    eligible_rows.append({'symbol': symbol, 'day': day, 'reason': 'insufficient_prior_prefix_history'})
                    continue
                for b, avg, count, slot in day_features:
                    denominators[(symbol, day, slot)] = avg
                    feature_rows.append({'symbol': symbol, 'day': day, 'slot': slot, 'prior_session_count': count, 'average_cumulative_volume': avg})
                bars.extend(today)
                sessions[day] = calendar[day].market_close.tz_convert('America/New_York').strftime('%H:%M')
                used += 1
                eligible_rows.append({'symbol': symbol, 'day': day, 'reason': 'eligible'})
            entry.update(status='data_selected', reason='See session and eligibility diagnostics', provider=provider, feed=feed, evaluation_sessions_used=used, first_returned=str(frame.index.min()), last_returned=str(frame.index.max()))
        except Exception as exc:
            entry['reason'] = str(exc)
        finally:
            report['coverage'].append(entry)
    save('coverage.json', report)
    save('config.json', vars(args))
    save('input-hashes.json', hashes)
    for name, rows, fields in [('sessions', quality_rows, ['symbol','day','evaluation','reason','expected_bars','returned_bars','provider']), ('eligibility', eligible_rows, ['symbol','day','reason']), ('rvol-reference', feature_rows, ['symbol','day','slot','prior_session_count','average_cumulative_volume'])]:
        write_table(out / (name + '.csv'), rows, fields)
    lines = ['# Research diagnostics v2', '', f'Evaluation: {start.date()} through {(end - pd.Timedelta(days=1)).date()}; exclusive end {end.date()}. Download begins {data_start.date()} for 20 requested warmup sessions. RVOL policy: at least {args.min_reference} valid prior same-time prefixes from the preceding 20 sessions.', '', 'Exploratory listed-stock research, not validated profitability. No OTC trades or historical news decisions.', '', '## Data funnel', '', '| Stage | Count |', '|---|---:|', f'| Candidate symbols | {len(symbols)} |', f"| Metadata verified | {report['metadata_verified']} |", f"| Action reference verified | {report['action_checks_verified']} |", f'| Provider selected | {len(providers)} |', f"| Usable full sessions including warmup | {sum(r['reason'] == 'usable' for r in quality_rows)} |", f"| Evaluation symbol-days eligible | {sum(r['reason'] == 'eligible' for r in eligible_rows)} |", f'| Simulation candles | {len(bars)} |', '', '## Session quality reasons', '', '| Reason | Count |', '|---|---:|']
    for reason, count in reason_counts(quality_rows).items():
        lines.append(f'| {reason} | {count} |')
    lines += ['', '## Evaluation eligibility reasons', '', '| Reason | Count |', '|---|---:|']
    for reason, count in reason_counts(eligible_rows).items():
        lines.append(f'| {reason} | {count} |')
    lines += ['', '## Symbol outcomes', '', '| Symbol | Status | Provider | Evaluation sessions | Reason |', '|---|---|---|---:|---|']
    for row in report['coverage']:
        lines.append('| ' + ' | '.join(cell(row.get(k, '')) for k in ('symbol','status','provider','evaluation_sessions_used','reason')) + ' |')
    lines += ['', '## Provider attempts', '', '| Symbol | Provider | Feed | Usable-session fraction | Outcome |', '|---|---|---|---:|---|']
    for row in report['providers']:
        for attempt in row['attempts']:
            fraction = attempt.get('coverage_fraction')
            fraction = f'{fraction:.1%}' if fraction is not None else 'N/A'
            lines.append(f"| {cell(row['symbol'])} | {cell(attempt['provider'])} | {cell(attempt['feed'])} | {fraction} | {cell(attempt.get('error') or attempt.get('quality_counts'))} |")
    if not bars:
        lines += ['', '## No evaluable sample', '', 'No returns or final equity fabricated. Review the funnel, coverage.json, sessions.csv and eligibility.csv.']
        publish('\n'.join(lines))
        return
    cfg = Config(allocation=args.allocation, max_price=25., strategies=('uptrend_pullback',))
    manifest = {'universe': cfg.universe, 'source': 'coverage_selected', 'feed': 'per_symbol', 'session_closes': sessions, 'provider_by_symbol': providers, 'historical_entry_ceiling': 25., 'price_adjustment': 'provider_reported', 'automated_action_check': True, 'corporate_actions_reviewed': False}
    original_scan = engine.scan
    comparisons = []
    lines += ['', '## Independent portfolios', '', '| Variant | Signals evaluated | Filter passes | Trades | Final equity | Net P&L | Win rate | Profit factor | Drawdown |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for variant in ('A_baseline','B_rvol','C_rvol_vwap'):
        signals_log = []
        def scanner(history, config):
            found = original_scan(history, config)
            if not found:
                return []
            b = history[-1]
            local = b.timestamp.astimezone(NY)
            key = (b.symbol, local.date().isoformat(), local.strftime('%H:%M'))
            denominator = denominators.get(key)
            ratio = sum(x.volume for x in history) / denominator if denominator else None
            def vw(items):
                volume = sum(x.volume for x in items)
                return sum((x.high+x.low+x.close)/3*x.volume for x in items)/volume if volume else None
            reason = 'passed'
            if variant != 'A_baseline' and (ratio is None or ratio < 2):
                reason = 'rvol_below_2'
            elif variant == 'C_rvol_vwap':
                current, earlier = vw(history), vw(history[:-3])
                if current is None or earlier is None or not b.close > current > earlier:
                    reason = 'vwap_trend_failed'
            signals_log.append({'symbol':b.symbol,'timestamp':b.timestamp.isoformat(),'same_time_rvol':ratio,'reason':reason})
            return [replace(s, reason=s.reason + f';variant={variant};rvol={ratio:.4f}') for s in found] if reason == 'passed' else []
        try:
            engine.scan = scanner
            result = engine.run(bars, cfg, manifest)
        finally:
            engine.scan = original_scan
        result['limitations'].extend(report['warnings'])
        result['evaluation_dates'] = {'start':start.isoformat(),'end_exclusive':end.isoformat()}
        folder = out / variant
        folder.mkdir(exist_ok=True)
        (folder / 'run.json').write_text(json.dumps(result,indent=2,allow_nan=False))
        for filename,key in [('trades','trades'),('equity','equity_curve'),('rejections','rejections')]:
            rows=result[key]
            write_table(folder/(filename+'.csv'),rows,list(rows[0]) if rows else ['status'])
        write_table(folder/'signals.csv',signals_log,['symbol','timestamp','same_time_rvol','reason'])
        stats=statistics(result['trades'])
        summary=result['summary']
        win=f"{stats['win_rate']:.1%}" if stats['win_rate'] is not None else 'N/A'
        pf=f"{stats['profit_factor']:.2f}" if stats['profit_factor'] is not None else 'N/A'
        lines.append(f"| {variant} | {len(signals_log)} | {sum(r['reason']=='passed' for r in signals_log)} | {len(result['trades'])} | {money(summary['ending_equity'])} | {money(summary['net_pnl'])} | {win} | {pf} | {summary['max_drawdown']:.2%} |")
        comparisons.append({'variant':variant,**summary,'signals_evaluated':len(signals_log),'filter_counts':reason_counts(signals_log),'engine_rejection_counts':reason_counts(result['rejections']),'statistics':stats})
        (folder/'SUMMARY.md').write_text(render(result))
    save('comparison.json',comparisons)
    for comparison in comparisons:
        lines += ['', '## '+comparison['variant']+' decisions', '', 'Filter outcomes: '+cell(comparison['filter_counts']), '', 'Engine/risk rejection outcomes: '+cell(comparison['engine_rejection_counts'])]
        result=json.loads((out/comparison['variant']/'run.json').read_text())
        section=render(result).replace('# Yahoo pilot results','# '+comparison['variant']+' full trade report',1)
        lines += ['',section]
    lines += ['', '## Audit limits', '', *['- '+w for w in report['warnings']], '', 'Signal counts are signals considered while the engine is flat, not every theoretical pattern while positions are open. Corporate-action dates are excluded; split reference warmup restarts without deleting the entire ticker. Dividend dates are excluded conservatively for this intraday-only experiment. Missing pre-signal history cannot become zero-volume tradable candles. Execution still uses complete sessions and the legacy simulator; partial-session fills, exact quote costs, and holdout validation are not fixed by this patch. All outputs are diagnostic research, not investment recommendations.']
    publish('\n'.join(lines))

if __name__=='__main__':
    main()
