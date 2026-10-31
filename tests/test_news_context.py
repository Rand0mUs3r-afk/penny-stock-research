from penny_lab.news_context import eligible_articles, normalize, timestamp, coverage_request

def article(**overrides):
    row = dict(published_at='2023-01-03T12:00:00Z', available_at='2023-01-03T12:01:00Z', historical_availability_verified=True, relevance_verified=True, verified_symbols=['TEST'])
    row.update(overrides)
    return row

def test_historical_gate():
    assert len(eligible_articles([article()], 'TEST', '2023-01-03T13:00:00Z')) == 1
    for row in [article(available_at='2023-01-03T14:00:00Z'), article(published_at='2023-01-04T12:00:00Z'), article(historical_availability_verified=False), article(relevance_verified=False), article(verified_symbols=['OTHER']), article(published_at='2022-12-01T12:00:00Z')]:
        assert eligible_articles([row], 'TEST', '2023-01-03T13:00:00Z') == []

def test_current_news_never_passes_historical_gate():
    row = normalize({'content': {'title': 'Example', 'pubDate': '2023-01-03T12:00:00Z'}}, 'TEST', '2026-10-31T06:00:00Z')
    assert not row['historical_availability_verified']
    assert eligible_articles([row], 'TEST', '2023-01-03T13:00:00Z') == []

def test_naive_timestamp_rejected():
    assert timestamp('2023-01-01') is None

def test_2023_request_not_claimed_as_tested():
    report = coverage_request('2023-01-01', [])
    assert report['status'] == 'unsupported_yahoo_intraday_range'
    assert report['earliest_returned_date'] is None
    assert not report['full_requested_history_validated']
