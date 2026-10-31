"""Synthetic unit-test fixtures only; never performance evidence."""
from datetime import datetime, timedelta, timezone
from penny_lab.models import Bar
from penny_lab.filter_comparison import filter_decision, comparison_sample, vwap

def history(price=2., count=5, volume=100.):
    start = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    return [Bar('FIXTURE', start + timedelta(minutes=5*i), price, price, price, price, volume) for i in range(count)]

def test_same_time_volume_boundary():
    rows = history()
    assert filter_decision(rows, 250., 'B_rvol')[0]
    assert not filter_decision(rows, 251., 'B_rvol')[0]
    assert not filter_decision(rows, None, 'B_rvol')[0]

def test_vwap_is_filter_not_reclaim_entry():
    assert not filter_decision(history(), 250., 'C_rvol_vwap')[0]
    assert filter_decision(history(), 250., 'B_rvol')[0]
    assert vwap(history()) == 2.

def test_no_future_volume_used_and_warmup_not_traded():
    groups = {}
    days = []
    start = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
    for i in range(22):
        stamp = start + timedelta(days=i)
        day = stamp.date().isoformat()
        days.append(day)
        groups[('FIXTURE', day)] = [Bar('FIXTURE', stamp, 2, 2, 2, 2, 100 if i < 21 else 1000000)]
    bars, denominators, eligibility = comparison_sample(groups, days)
    assert len(bars) == 2
    assert sum(r['eligible'] for r in eligibility) == 2
    assert denominators[('FIXTURE', days[20], '10:00')] == 100
    assert denominators[('FIXTURE', days[21], '10:00')] == 100

def test_missing_prior_session_blocks_same_sample():
    groups = {('FIXTURE', '2026-01-01'): history()}
    bars, denominators, eligibility = comparison_sample(groups, ['2026-01-01'])
    assert not bars and not denominators
    assert not eligibility[0]['eligible']
