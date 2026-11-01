"""Software correctness fixtures, not market performance."""
from penny_lab import engine,range_runner,lab_setups,strategy_lab
from penny_lab.config import Config
from penny_lab.new_strategy_lab import NEW_MIXTURES,SnapshotReady,descriptor,acquire,compare

def test_mixtures_are_new_setups_not_old_uptrend():
    assert len(NEW_MIXTURES)==2
    for names in NEW_MIXTURES.values():
        assert len(names)>=2
        assert 'uptrend_pullback' not in names
        assert 'vwap_reclaim' not in names
        assert Config(strategies=names).strategies==names

def test_acquisition_descriptor_has_no_fake_performance():
    data=descriptor(SnapshotReady(Config(),{'universe':'fixture'},5))
    assert data['strategy_execution_performed'] is False
    assert 'summary' not in data and 'trades' not in data
    assert 'ending_equity' not in data

def test_acquisition_intercepts_before_any_old_engine_run(monkeypatch,tmp_path):
    original=engine.run
    def fake_source():
        engine.run([],Config(),{'universe':'fixture'})
        raise AssertionError('Capture must interrupt before a simulation result is returned')
    monkeypatch.setattr(range_runner,'main',fake_source)
    acquire(['--output',str(tmp_path)])
    assert engine.run is original
    assert (tmp_path/'snapshot.json').exists()
    assert not (tmp_path/'A_baseline'/'trades.csv').exists()

def test_compare_adds_seven_cases_then_restores_registry(monkeypatch,tmp_path):
    before=dict(lab_setups.CASES)
    seen=[]
    def fake_compare():
        seen.append(dict(lab_setups.CASES))
    monkeypatch.setattr(strategy_lab,'main',fake_compare)
    compare(['--input',str(tmp_path)])
    assert len(seen[0])==7
    assert set(NEW_MIXTURES)<=set(seen[0])
    assert lab_setups.CASES==before
