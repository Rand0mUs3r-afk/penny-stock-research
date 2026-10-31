"""Yahoo-first recent history, Alpaca secondary; no orders or OTC simulation."""
import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .config import Config
from .engine import run
from .models import Bar
from .report import cell, money, statistics
from .yahoo_pilot import classify, write_table

def price_band(entry):
    return 'below_5' if entry < 5 else ('5_to_below_10' if entry < 10 else '10_to_below_25')

def select_history(attempts, evaluate):
    errors = []
    for provider, feed, fetch in attempts:
        try:
            frame = fetch()
            validated = evaluate(frame)
            return frame, validated, provider, feed, errors
        except Exception as exc:
            errors.append({'provider': provider, 'feed': feed, 'reason': str(exc)})
    raise ValueError(json.dumps(errors))

def discover(yf, limit):
    symbols, events = [], []
    for label, otc in (('otc_under_25', True), ('us_under_25', False)):
        try:
            rules = [yf.EquityQuery('eq', ['region', 'us']), yf.EquityQuery('btwn', ['intradayprice', 0.000001, 24.999999])]
            if otc:
                rules.append(yf.EquityQuery('eq', ['exchange', 'PNK']))
            response = yf.screen(yf.EquityQuery('and', rules), size=limit, sortField='dayvolume', sortAsc=False)
            found = [r['symbol'] for r in response.get('quotes', []) if r.get('symbol')]
            symbols.extend(found)
            events.append({'source': label, 'status': 'ok', 'count': len(found)})
        except Exception as exc:
            events.append({'source': label, 'status': 'failed', 'error': str(exc)})
    return list(dict.fromkeys(symbols)), events

def validate_sessions(frame, calendar, symbol):
    import pandas as pd
    if frame.empty or frame.index.tz is None or frame.index.has_duplicates:
        raise ValueError('Empty, timezone-naive, or duplicate history')
    bars, closes, rejected = [], {}, 0
    for day, session in calendar.items():
        piece = frame[(frame.index >= session.market_open) & (frame.index < session.market_close)]
        expected = pd.date_range(session.market_open, session.market_close, freq='5min', inclusive='left')
        valid = len(piece) == len(expected) and piece.index.tz_convert('UTC').equals(expected.tz_convert('UTC'))
        if valid:
            values = piece[['Open', 'High', 'Low', 'Close', 'Volume']]
            valid = all(math.isfinite(float(v)) and float(v) > 0 for v in values.to_numpy().ravel())
            valid = valid and all(r.Low <= min(r.Open, r.Close) <= max(r.Open, r.Close) <= r.High for r in piece.itertuples())
        if not valid:
            rejected += 1
            continue
        for stamp, row in piece.iterrows():
            bars.append(Bar(symbol, (stamp + pd.Timedelta(minutes=5)).to_pydatetime(), *[float(row[c]) for c in ('Open', 'High', 'Low', 'Close', 'Volume')]))
        closes[day] = session.market_close.tz_convert('America/New_York').strftime('%H:%M')
    if not bars:
        raise ValueError('No complete positive-volume sessions; no synthetic fills')
    return bars, closes, rejected

def append_provider_report(out):
    path = out / 'coverage.json'
    if not path.exists():
        return
    audit = json.loads(path.read_text())
    rows = audit.get('coverage', [])
    lines = ['## Multi-provider coverage and price bands', '',
             f"Actual requested start: {cell(audit.get('requested_start'))}. Historical entry ceiling: USD 25 (exclusive).", '',
             'The Yahoo-only history warning above describes Yahoo retention, not Alpaca coverage. The table below records actual provider outcomes. Full-history validity is NOT established by a successful download.', '',
             '| Symbol | Provider | Feed | Status | Sessions used | Sessions rejected | First returned | Last returned |', '|---|---|---|---|---:|---:|---|---|']
    for row in rows[:200]:
        lines.append('| ' + ' | '.join(cell(row.get(k, '')) for k in ('symbol', 'provider', 'feed', 'status', 'sessions_used', 'sessions_rejected', 'first_bar', 'last_bar')) + ' |')
    lines += ['', f"Alpaca credential configuration: {cell(audit.get('alpaca_configuration'))}. Credentials are never printed.", '',
              '## Entry-price band attribution', '', '| Entry-price band | Trades | Net P&L | Win rate | Average loss |', '|---|---:|---:|---:|---:|']
    result_path = out / 'run.json'
    if result_path.exists():
        trades = json.loads(result_path.read_text()).get('trades', [])
        for band in ('below_5', '5_to_below_10', '10_to_below_25'):
            chosen = [t for t in trades if price_band(t['entry']) == band]
            stats = statistics(chosen)
            wr = f"{100 * stats['win_rate']:.2f}%" if stats['win_rate'] is not None else 'N/A'
            lines.append(f"| {band} | {len(chosen)} | {money(sum(t['net_pnl'] for t in chosen))} | {wr} | {money(stats['average_loss'])} |")
    lines += ['', 'All price bands share one cash portfolio. Current-symbol selection, automatic action checks, and complete-session filtering limit interpretation. OTC is still coverage-only; news remains display-only.', '']
    text = '\n'.join(lines)
    (out / 'PROVIDERS.md').write_text(text)
    with (out / 'SUMMARY.md').open('a') as handle:
        handle.write('\n' + text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            handle.write(text)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', default='')
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--start', default='', help='Optional actual historical start YYYY-MM-DD; long ranges use Alpaca')
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--allocation', type=float, choices=(250., 300.), default=300.)
    parser.add_argument('--feed', choices=('sip', 'iex'), default='sip')
    parser.add_argument('--output', default='results/yahoo-pilot')
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if args.report_only:
        append_provider_report(out)
        return
    if not 1 <= args.days <= 59 or not 1 <= args.limit <= 100:
        parser.error('days must be 1..59 and limit 1..100')
    import pandas as pd
    import pandas_market_calendars as mcal
    import yfinance as yf
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = datetime.strptime(args.start, '%Y-%m-%d').replace(tzinfo=timezone.utc) if args.start else end - timedelta(days=args.days)
    if start >= end or start.year < 2016:
        parser.error('Start must be before end and no earlier than 2016; actual provider coverage is checked separately')
    long_range = (end - start).days > 59
    scan_limit = min(args.limit, 5) if long_range else args.limit
    events = []
    if args.symbols:
        symbols = list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(',') if s.strip()))
    else:
        symbols, events = discover(yf, scan_limit)
    if len(symbols) > (10 if long_range else 200):
        parser.error('Long historical pilots allow at most 10 symbols; recent pilots at most 200')
    schedule = mcal.get_calendar('NYSE').schedule(start_date=start.date(), end_date=end.date())
    calendar = {session.market_open.date().isoformat(): session for _, session in schedule.iterrows() if session.market_open >= pd.Timestamp(start) and session.market_close < pd.Timestamp(end)}
    if not calendar:
        parser.error('No complete calendar sessions in requested range')
    alpaca = None
    credential_status = 'missing_one_or_both_secrets'
    if os.environ.get('ALPACA_API_KEY') and os.environ.get('ALPACA_SECRET_KEY'):
        from .providers.alpaca import AlpacaData
        alpaca = AlpacaData(args.feed)
        credential_status = 'both_present_access_not_assumed'
    def alpaca_frame(symbol):
        if alpaca is None:
            raise ValueError('Alpaca credentials missing; add ALPACA_API_KEY and ALPACA_SECRET_KEY')
        bars = alpaca.bars([symbol], start.isoformat(), end.isoformat())
        return pd.DataFrame([{'Open': b.open, 'High': b.high, 'Low': b.low, 'Close': b.close, 'Volume': b.volume} for b in bars], index=pd.DatetimeIndex([b.timestamp - timedelta(minutes=5) for b in bars])).sort_index()
    accepted, sessions, coverage = [], {}, []
    for symbol in symbols:
        row = {'symbol': symbol, 'status': 'rejected', 'market': 'unknown', 'exchange': '', 'provider': '', 'feed': '', 'sessions_used': 0, 'sessions_rejected': 0, 'bars_returned': 0}
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.get_info()
            market, exchange = classify(info)
            row.update(market=market, exchange=exchange)
            if info.get('quoteType') != 'EQUITY' or info.get('currency') != 'USD':
                raise ValueError('Yahoo metadata must verify a USD equity; unknown symbols fail closed')
            def yahoo_frame():
                if long_range:
                    raise ValueError('Requested range exceeds Yahoo intraday retention; use Alpaca')
                return ticker.history(start=start, end=end, interval='5m', auto_adjust=False, back_adjust=False, actions=True, repair=False, prepost=False, raise_errors=True)
            if market == 'otc':
                frame = yahoo_frame()
                if frame.empty:
                    raise ValueError('No Yahoo OTC five-minute data')
                row.update(status='coverage_only', provider='Yahoo/yfinance', feed='Yahoo aggregates', bars_returned=len(frame), first_bar=str(frame.index.min()), last_bar=str(frame.index.max()), reason='OTC not simulated; Alpaca retail OTC not assumed')
            elif market == 'listed':
                actions = ticker.history(start=start, end=end, interval='1d', auto_adjust=False, actions=True, raise_errors=True)
                if actions.empty or not {'Stock Splits', 'Dividends'} <= set(actions.columns):
                    raise ValueError('Corporate-action checks unavailable; fail closed')
                if any(float(actions[c].fillna(0).abs().sum()) > 0 for c in ('Stock Splits', 'Dividends')):
                    raise ValueError('Corporate action in requested window; manual review required')
                attempts = [('Yahoo/yfinance', 'Yahoo aggregates', yahoo_frame), ('Alpaca', args.feed, lambda: alpaca_frame(symbol))]
                frame, checked, provider, feed, failures = select_history(attempts, lambda f: validate_sessions(f, calendar, symbol))
                bars, closes, rejected = checked
                accepted.extend(bars)
                sessions.update(closes)
                row.update(status='accepted_listed', provider=provider, feed=feed, provider_attempt_failures=failures, sessions_used=len(closes), sessions_rejected=rejected, bars_returned=len(frame), first_bar=str(frame.index.min()), last_bar=str(frame.index.max()), all_requested_sessions_usable=(rejected == 0), reason='Complete sessions only; automatic action checks, not full provenance review')
            else:
                raise ValueError('Unknown market classification')
            frame.to_csv(out / ('history-' + ''.join(c for c in symbol if c.isalnum() or c in '-_.') + '.csv'))
        except Exception as exc:
            row['reason'] = str(exc)
        coverage.append(row)
    warnings = ['Current-symbol selection is not a point-in-time universe', 'Complete-session filtering creates selection bias', 'Corporate-action checks depend on Yahoo and are not a comprehensive review', 'OTC is coverage-only; news never gates historical trades', 'Costs are uncalibrated; mixed providers across symbols are disclosed; no within-symbol candle patching', 'Historical range requested is not evidence of complete coverage']
    audit = {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'requested_start': start.isoformat(), 'requested_end': end.isoformat(), 'alpaca_configuration': credential_status, 'historical_scan_limit_per_screen': scan_limit, 'coverage': coverage, 'discovery': events, 'warnings': warnings, 'arguments': vars(args)}
    (out / 'coverage.json').write_text(json.dumps(audit, indent=2))
    write_table(out / 'coverage.csv', coverage, ['symbol', 'market', 'exchange', 'provider', 'feed', 'status', 'reason', 'sessions_used', 'sessions_rejected', 'bars_returned', 'first_bar', 'last_bar'])
    if not accepted:
        (out / 'SUMMARY.txt').write_text('No eligible data; no performance fabricated. Check coverage.json.\n')
        return
    cfg = Config(allocation=args.allocation, max_price=25.)
    manifest = {'source': 'Per-symbol provider selection', 'feed': 'See provider_by_symbol', 'universe': cfg.universe, 'historical_entry_ceiling': 25., 'price_adjustment': 'raw', 'timeframe_minutes': 5, 'timestamp_convention': 'bar_end', 'session_closes': sessions, 'corporate_actions_reviewed': False, 'automated_action_check': True, 'symbols': {r['symbol']: r['exchange'] for r in coverage if r['status'] == 'accepted_listed'}, 'provider_by_symbol': {r['symbol']: {'provider': r['provider'], 'feed': r['feed']} for r in coverage if r['status'] == 'accepted_listed'}, 'survivorship_warning': warnings}
    result = run(accepted, cfg, manifest)
    result['limitations'].extend(warnings)
    (out / 'run.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    for name, key in (('trades', 'trades'), ('ranking', 'strategy_ranking'), ('equity', 'equity_curve'), ('rejections', 'rejections')):
        rows = result[key]
        write_table(out / (name + '.csv'), rows, list(rows[0]) if rows else ['status'])
    (out / 'SUMMARY.txt').write_text(json.dumps(result['summary'], indent=2))
    print(json.dumps(result['summary'], indent=2))

if __name__ == '__main__':
    main()
