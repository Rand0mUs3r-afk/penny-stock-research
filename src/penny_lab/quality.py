"""Explicit data-quality and historical reference policies."""
from collections import Counter
from math import isfinite

def inspect_session(frame, expected):
    if frame.index.has_duplicates:
        return 'duplicate_timestamp'
    actual = frame.index.tz_convert('UTC')
    expected = expected.tz_convert('UTC')
    if not actual.equals(expected):
        return 'missing_or_misaligned_bars'
    values = frame[['Open', 'High', 'Low', 'Close', 'Volume']]
    if not all(isfinite(float(v)) for v in values.to_numpy().ravel()):
        return 'nonfinite_value'
    if (values.Volume <= 0).any():
        return 'zero_or_negative_volume'
    if (values[['Open', 'High', 'Low', 'Close']] <= 0).any().any():
        return 'nonpositive_price'
    if not all(r.Low <= min(r.Open, r.Close) <= max(r.Open, r.Close) <= r.High for r in frame.itertuples()):
        return 'invalid_ohlc'
    return 'usable'

def select_coverage(attempts, assess, minimum_fraction=.95):
    """Escalate inadequate primary coverage; never select on trading returns."""
    reports, candidates = [], []
    for name, feed, fetch in attempts:
        try:
            frame = fetch()
            score, detail = assess(frame)
            reports.append({'provider': name, 'feed': feed, 'coverage_fraction': score, 'quality_counts': detail})
            if score > 0:
                candidates.append((score, frame, name, feed))
            if score >= minimum_fraction:
                break
        except Exception as exc:
            reports.append({'provider': name, 'feed': feed, 'error': str(exc)})
    if not candidates:
        return None, None, None, reports
    score, frame, name, feed = max(candidates, key=lambda c: c[0])
    return frame, name, feed, reports

def reference_mean(history, today, slot, cumulative, action_days, minimum=12, lookback=20):
    """Use valid prefixes from previous calendar sessions, not full future days."""
    if not 1 <= minimum <= lookback:
        raise ValueError('minimum must be in 1..lookback')
    previous = [day for day in history if day < today][-lookback:]
    last_action = max((d for d in action_days if d <= today), default='')
    values = [cumulative[(day, slot)] for day in previous if day > last_action and (day, slot) in cumulative]
    return ((sum(values) / len(values)) if len(values) >= minimum else None), len(values)

def reason_counts(rows):
    return dict(Counter(r['reason'] for r in rows))
