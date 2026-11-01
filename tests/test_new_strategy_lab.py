"""Synthetic software fixtures, not performance evidence."""
from datetime import datetime,timedelta,timezone
from penny_lab import engine,range_runner,lab_setups,strategy_lab,replacement_setups
from penny_lab.config import Config
from penny_lab.models import Bar
from penny_lab.new_strategy_lab import NEW_MIXTURES,SnapshotReady,descriptor,acquire,compare

def test_mixtures_exclude_every_old_setup():
    old={'uptrend_pullback','vwap_reclaim','opening_range_breakout','opening_range_pullback','failed_breakdown_recovery','compression_continuation'}
    assert len(NEW_MIXTURES)==2
    for names in replacement_setups.CASES.values():
        assert not set(names)&old
        assert Config(strategies=names).strategies==names

def test_descriptor_is_not_fake_performance():
    row=descriptor(SnapshotReady(Config(),{'universe':'fixture'},5))
    assert row['strategy_execution_performed'] is False
    assert 'summary' not in row and 'trades' not in row

def test_acquisition_never_runs_old_engine(monkeypatch,tmp_path):
    old=engine.run
    def fake():
        engine.run([],Config(),{'universe':'fixture'})
        raise AssertionError('Must stop before returning simulated results')
    monkeypatch.setattr(range_runner,'main',fake)
    acquire(['--output',str(tmp_path)])
    assert engine.run is old
    assert (tmp_path/'snapshot.json').exists()

def test_compare_REPLACES_cases_and_restores_every_adapter(monkeypatch,tmp_path):
    before=dict(lab_setups.CASES)
    before_pattern=strategy_lab.pattern
    seen=[]
    def fake():
        seen.append(dict(lab_setups.CASES))
        assert strategy_lab.pattern is replacement_setups.pattern
    monkeypatch.setattr(strategy_lab,'main',fake)
    compare(['--input',str(tmp_path)])
    assert seen==[replacement_setups.CASES]
    assert len(seen[0])==5
    assert lab_setups.CASES==before and strategy_lab.pattern is before_pattern

def test_indicators_on_flat_prices():
    assert replacement_setups.ema([2]*40,21)==[2.]*40
    assert replacement_setups.rsi([2]*20)==50

def test_double_bottom_neckline_fixture():
    start=datetime(2026,1,5,14,35,tzinfo=timezone.utc)
    rows=[]
    for i in range(24):
        low=2.8 if i==5 else (2.81 if i==12 else 2.95)
        rows.append(Bar('FIXTURE',start+timedelta(minutes=5*i),3,3.05,low,3,10000))
    rows.append(Bar('FIXTURE',start+timedelta(minutes=120),3,3.10,2.96,3.08,20000))
    assert replacement_setups.pattern(rows,'double_bottom_neckline') is not None
    assert replacement_setups.pattern(rows[:10],'double_bottom_neckline') is None
