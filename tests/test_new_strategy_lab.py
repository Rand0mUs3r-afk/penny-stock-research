"""Deterministic software fixtures for the blended portfolio."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
import pytest
from penny_lab import engine,range_runner,lab_setups,strategy_lab,replacement_setups as rules
from penny_lab.config import Config
from penny_lab.models import Bar
from penny_lab.new_strategy_lab import NEW_MIXTURES,SnapshotReady,descriptor,acquire,compare

def bars(values):
    start=datetime(2026,1,5,14,35,tzinfo=timezone.utc)
    return [Bar('FIXTURE',start+timedelta(minutes=5*i),*v) for i,v in enumerate(values)]

def impulse():
    return bars([(3,3.1,2.9,3,10000)]*12+[(3.12,3.5,3.09,3.48,10000),(3.46,3.46,3.32,3.38,10000),(3.38,3.55,3.35,3.52,10000)])

def test_one_blend_with_supported_components():
    assert NEW_MIXTURES=={'classic_blend_mix':rules.COMPONENTS}
    assert Config(strategies=rules.COMPONENTS).strategies==rules.COMPONENTS
    assert len(rules.COMPONENTS)==3

def test_orb_first_breakout():
    rows=bars([(3,3.1,2.9,3,10000)]*3+[(3,3.22,3,3.2,20000)])
    assert rules.pattern(rows,'opening_range_breakout') is not None
    rows.append(replace(rows[-1],timestamp=rows[-1].timestamp+timedelta(minutes=5),open=3.2,close=3.21))
    assert rules.pattern(rows,'opening_range_breakout') is None

def test_first_pullback_confirmation_and_depth():
    rows=impulse()
    found=rules.pattern(rows,'impulse_first_pullback')
    assert found is not None and abs(found['stop']-3.32*.999)<1e-10
    assert rules.pattern(rows[:-1],'impulse_first_pullback') is None
    rows[-2]=replace(rows[-2],low=3.2)
    assert rules.pattern(rows,'impulse_first_pullback') is None

def test_vwap_reclaim():
    rows=bars([(3,3.1,2.9,3,10000)]*12+[(3.01,3.02,2.92,2.94,10000),(2.95,3.06,2.94,3.04,15000)])
    result=rules.pattern(rows,'vwap_reclaim')
    assert result is not None and result['stop']<rows[-1].close
    rows[-2]=replace(rows[-2],close=3.01)
    assert rules.pattern(rows,'vwap_reclaim') is None

def test_vwap_uses_only_supplied_prefix():
    rows=impulse()
    values=rules.session_vwap(rows)
    assert values[:-1]==rules.session_vwap(rows[:-1])
    expected=sum((b.high+b.low+b.close)/3*b.volume for b in rows)/sum(b.volume for b in rows)
    assert abs(values[-1]-expected)<1e-10

def test_time_windows():
    late=impulse()[-1].timestamp+timedelta(hours=5)
    assert rules.names_at('classic_blend_mix',late)==()
    for name in rules.COMPONENTS:
        rows=[replace(b,timestamp=b.timestamp+timedelta(hours=5)) for b in impulse()]
        assert rules.pattern(rows,name) is None

def test_descriptor_is_acquisition_only():
    row=descriptor(SnapshotReady(Config(),{},5))
    assert row['strategy_execution_performed'] is False
    assert 'summary' not in row and 'trades' not in row

def test_acquisition_intercepts_engine(monkeypatch,tmp_path):
    original=engine.run
    def fake():
        engine.run([],Config(),{})
        raise AssertionError('No simulation may return')
    monkeypatch.setattr(range_runner,'main',fake)
    acquire(['--output',str(tmp_path)])
    assert engine.run is original
    assert (tmp_path/'snapshot.json').exists()

@pytest.mark.parametrize('fail',[False,True])
def test_compare_installs_blend_and_restores_on_error(monkeypatch,tmp_path,fail):
    old_cases=dict(lab_setups.CASES)
    old_pattern,old_names=strategy_lab.pattern,strategy_lab.names_at
    def fake():
        assert lab_setups.CASES==rules.CASES
        assert strategy_lab.pattern is rules.pattern
        if fail:
            raise RuntimeError('fixture')
    monkeypatch.setattr(strategy_lab,'main',fake)
    if fail:
        with pytest.raises(RuntimeError):
            compare(['--input',str(tmp_path)])
    else:
        compare(['--input',str(tmp_path)])
    assert lab_setups.CASES==old_cases
    assert strategy_lab.pattern is old_pattern and strategy_lab.names_at is old_names
    selected=json.loads((tmp_path/'active-setups.json').read_text())
    assert selected['portfolio_mode']=='shared_cash_one_position_per_symbol'
    assert 'removed_from_active_lab' not in selected
