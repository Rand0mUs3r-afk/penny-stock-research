"""Current news is display-only. Historical news gating is not enabled."""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .report import cell

def timestamp(value):
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None

def eligible_articles(articles, symbol, entry_time, hours=24):
    """Future archive contract: availability and relevance must be independently verified."""
    entry = timestamp(entry_time)
    if entry is None or hours <= 0:
        raise ValueError('Require timezone-aware entry and positive freshness window')
    accepted = []
    for article in articles:
        published = timestamp(article.get('published_at'))
        available = timestamp(article.get('available_at'))
        if (article.get('historical_availability_verified') is True
                and article.get('relevance_verified') is True
                and symbol in article.get('verified_symbols', [])
                and published is not None and available is not None
                and entry - timedelta(hours=hours) <= published <= available <= entry):
            accepted.append(article)
    return accepted

def normalize(item, symbol, observed_at):
    content = item.get('content') or item
    provider = content.get('provider') or {}
    canonical = content.get('canonicalUrl') or {}
    if not isinstance(provider, dict):
        provider = {}
    if not isinstance(canonical, dict):
        canonical = {}
    published = timestamp(content.get('pubDate') or content.get('providerPublishTime'))
    return {'queried_symbol': symbol, 'title': content.get('title', ''),
            'publisher': provider.get('displayName') or content.get('publisher', ''),
            'url': canonical.get('url') or content.get('link', ''),
            'published_at': published.isoformat() if published else None,
            'observed_at': observed_at, 'available_at': observed_at,
            'historical_availability_verified': False, 'relevance_verified': False,
            'verified_symbols': [], 'status': 'current_context_only_unverified'}

def coverage_request(requested_start, rows):
    requested = datetime.strptime(requested_start, '%Y-%m-%d').date()
    firsts = [timestamp(row.get('first_bar')) for row in rows]
    firsts = [v.date() for v in firsts if v is not None]
    return {'requested_start': requested.isoformat(), 'interval': '5m',
            'earliest_returned_date': min(firsts).isoformat() if firsts else None,
            'full_requested_history_validated': False,
            'status': 'unsupported_yahoo_intraday_range' if requested < datetime.now(timezone.utc).date() - timedelta(days=60) else 'not_validated',
            'note': 'Recent pilot remains a separate run. No daily-bar substitution, synthetic intraday bars, or claimed 2023 performance. Earliest returned date is not proof of continuous coverage.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='results/yahoo-pilot')
    parser.add_argument('--requested-start', default='2023-01-01')
    parser.add_argument('--count', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.count <= 30:
        parser.error('count must be 1..30')
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'coverage.json'
    coverage = json.loads(path.read_text()) if path.exists() else {}
    rows = coverage.get('coverage', [])
    request = coverage_request(args.requested_start, rows)
    (out / 'historical-request.json').write_text(json.dumps(request, indent=2))
    observed = datetime.now(timezone.utc).isoformat()
    news, errors = [], []
    import yfinance as yf
    for symbol in dict.fromkeys(r['symbol'] for r in rows if r.get('symbol')):
        try:
            items = yf.Ticker(symbol).get_news(count=args.count, tab='news')
            news.extend(normalize(item, symbol, observed) for item in items if isinstance(item, dict))
        except Exception as exc:
            errors.append({'symbol': symbol, 'error': str(exc)})
    payload = {'observed_at': observed, 'mode': 'display_only',
               'historical_filter_enabled': False, 'articles': news, 'errors': errors,
               'warning': 'Headlines do not prove genuine breakouts. Missing news is unknown, not fake. Current news cannot approve historical entries.'}
    (out / 'current-news.json').write_text(json.dumps(payload, indent=2))
    lines = ['## Requested historical coverage', '',
             '| Requested start | Earliest five-minute date returned | Status |', '|---|---|---|',
             f"| {cell(request['requested_start'])} | {cell(request['earliest_returned_date'] or 'None')} | {cell(request['status'])} |", '',
             request['note'], '',
             '## Current Yahoo news — NOT used in historical trades', '',
             'Historical catalyst filter: disabled. All items are unverified current context; publication timestamps alone do not establish historical availability. No headline can certify a real breakout.', '',
             '| Queried ticker | Publication time | Publisher | Headline |', '|---|---|---|---|']
    for article in news[:100]:
        lines.append('| ' + ' | '.join(cell(article.get(k) or 'Unknown') for k in ('queried_symbol', 'published_at', 'publisher', 'title')) + ' |')
    if not news:
        lines += ['', 'No current articles retrieved. This does not establish that no news exists.']
    if len(news) > 100:
        lines += ['', 'First 100 articles shown; all returned articles and URLs are in current-news.json.']
    for error in errors[:30]:
        lines += ['', f"News retrieval failed for {cell(error['symbol'])}: {cell(error['error'])}"]
    text = '\n'.join(lines) + '\n'
    (out / 'NEWS_AND_COVERAGE.md').write_text(text, encoding='utf-8')
    summary = out / 'SUMMARY.md'
    with summary.open('a', encoding='utf-8') as handle:
        handle.write('\n' + text)
    target = os.environ.get('GITHUB_STEP_SUMMARY')
    if target:
        with open(target, 'a', encoding='utf-8') as handle:
            handle.write(text)
    print(json.dumps({'articles': len(news), 'errors': len(errors), 'historical_request': request}, indent=2))

if __name__ == '__main__':
    main()
