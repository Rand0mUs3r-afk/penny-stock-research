"""Synthetic correctness fixtures, not market performance."""
from datetime import datetime,timedelta,timezone
import pytest
from penny_lab import engine,range_runner,lab_setups,strategy_lab,replacement_setups
from penny_lab.config import Config,PRICE_ACTION_STRATEGIES
from penny_lab.models import Bar
from penny_lab.new_strategy_lab import NEW_MIXTURES,SnapshotReady,descriptor,acquire,compare

def fixture(tail):
    values=[(3,3.1,2.9,3)]*13+tail
    start=datetime(2026,1,5,14,35,tzinfo=timezone.utc)
    return [Bar('FIXTURE',start+timedelta(minutes=5*i),*ohlc,10000) for i,ohlc in enumerate(values)]

def test_active_cases_are_price_action_only():
    assert len(replacement_setups.CASES)==5 and len(NEW_MIXTURES)==2
    assert set(n for names in replacement_setups.CASES.values() for n in names)==set(PRICE_ACTION_STRATEGIES)
    for names in replacement_setups.CASES.values():
        assert Config(strategies=names).strategies==names

@pytest.mark.parametrize('name,tail',[
 ('engulfing_at_low',[(3,3.02,2.8,2.85),(2.84,3.08,2.79,3.05)]),
 ('three_candle_reversal',[(3.1,3.12,2.9,2.95),(2.95,2.98,2.8,2.94),(2.94,3.16,2.9,3.15)]),
 ('stair_step_continuation',[(3,3.1,2.95,3.05),(3.05,3.2,3,3.15),(3.15,3.3,3.1,3.25),(3.25,3.4,3.2,3.35)])])
def test_patterns_signal_only_on_confirmation(name,tail):
    rows=fixture(tail)
    found=replacement_setups.pattern(rows,name)
    assert found is not None and 0<found['stop']<rows[-1].close
    assert replacement_setups.pattern(rows[:-1],name) is None
    assert replacement_setups.pattern(rows[:5],name) is None

def test_flat_market_has_no_signals():
    for name in PRICE_ACTION_STRATEGIES:
        assert replacement_setups.pattern(fixture([]),name) is None

def test_descriptor_is_not_performance():
    row=descriptor(SnapshotReady(Config(),{},5))
    assert row['strategy_execution_performed'] is False
    assert 'summary' not in row and 'trades' not in row

def test_acquisition_interrupts_old_engine(monkeypatch,tmp_path):
    old=engine.run
    def fake():
        engine.run([],Config(),{})
        raise AssertionError('Must not return a simulation')
    monkeypatch.setattr(range_runner,'main',fake)
    acquire(['--output',str(tmp_path)])
    assert engine.run is old
    assert (tmp_path/'snapshot.json').exists()

def test_compare_replaces_cases_and_restores_adapters(monkeypatch,tmp_path):
    before=dict(lab_setups.CASES)
    old_pattern,old_names=strategy_lab.pattern,strategy_lab.names_at
    def fake():
        assert lab_setups.CASES==replacement_setups.CASES
        assert strategy_lab.pattern is replacement_setups.pattern
        assert strategy_lab.names_at is replacement_setups.names_at
    monkeypatch.setattr(strategy_lab,'main',fake)
    compare(['--input',str(tmp_path)])
    assert lab_setups.CASES==before
    assert strategy_lab.pattern is old_pattern and strategy_lab.names_at is old_names
