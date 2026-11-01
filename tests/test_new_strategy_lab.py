"""Software fixtures only, not evidence of a profitable strategy."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from penny_lab import engine,range_runner,lab_setups,strategy_lab,replacement_setups
from penny_lab.config import Config
from penny_lab.models import Bar
from penny_lab.new_strategy_lab import NEW_MIXTURES,SnapshotReady,descriptor,acquire,compare

def fixture():
    values=[(3,3.1,2.9,3)]*12+[(3.12,3.5,3.09,3.48),(3.46,3.46,3.32,3.38),(3.38,3.55,3.35,3.52)]
    start=datetime(2026,1,5,14,35,tzinfo=timezone.utc)
    return [Bar('FIXTURE',start+timedelta(minutes=5*i),*ohlc,10000) for i,ohlc in enumerate(values)]

def test_only_one_context_case_no_mixtures():
    assert replacement_setups.CASES=={'impulse_first_pullback':('impulse_first_pullback',)}
    assert NEW_MIXTURES=={}
    assert Config(strategies=('impulse_first_pullback',)).strategies==('impulse_first_pullback',)

def test_signal_requires_completed_confirmation():
    rows=fixture()
    result=replacement_setups.pattern(rows,'impulse_first_pullback')
    assert result is not None
    assert abs(result['stop']-3.32*.999)<1e-10
    assert replacement_setups.pattern(rows[:-1],'impulse_first_pullback') is None

def test_deep_pullback_rejected():
    rows=fixture()
    rows[-2]=replace(rows[-2],low=3.2)
    assert replacement_setups.pattern(rows,'impulse_first_pullback') is None

def test_no_breakout_confirmation_rejected():
    rows=fixture()
    rows[-1]=replace(rows[-1],close=3.49)
    assert replacement_setups.pattern(rows,'impulse_first_pullback') is None

def test_weak_impulse_rejected():
    rows=fixture()
    rows[-3]=replace(rows[-3],open=3.4)
    assert replacement_setups.pattern(rows,'impulse_first_pullback') is None

def test_late_entry_rejected():
    rows=fixture()
    rows=[replace(b,timestamp=b.timestamp+timedelta(hours=2)) for b in rows]
    assert replacement_setups.pattern(rows,'impulse_first_pullback') is None

def test_same_impulse_does_not_emit_again_on_next_bar():
    rows=fixture()
    rows.append(Bar('FIXTURE',rows[-1].timestamp+timedelta(minutes=5),3.52,3.65,3.50,3.6,10000))
    assert replacement_setups.pattern(rows,'impulse_first_pullback') is None

def test_old_pattern_names_not_active():
    for name in ('engulfing_at_low','three_candle_reversal','stair_step_continuation','ema_trend_cross','bollinger_rsi_reentry','double_bottom_neckline'):
        assert replacement_setups.pattern(fixture(),name) is None

def test_descriptor_is_not_performance():
    row=descriptor(SnapshotReady(Config(),{},5))
    assert row['strategy_execution_performed'] is False
    assert 'summary' not in row and 'trades' not in row

def test_acquisition_interrupts_old_engine(monkeypatch,tmp_path):
    old=engine.run
    def fake():
        engine.run([],Config(),{})
        raise AssertionError('Must not return simulation')
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
    monkeypatch.setattr(strategy_lab,'main',fake)
    compare(['--input',str(tmp_path)])
    assert lab_setups.CASES==before
    assert strategy_lab.pattern is old_pattern and strategy_lab.names_at is old_names
