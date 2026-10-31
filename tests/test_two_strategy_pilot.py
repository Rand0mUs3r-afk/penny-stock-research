from dataclasses import replace
from penny_lab.config import Config
from penny_lab import multi_pilot
from penny_lab.two_strategy_pilot import EXPERIMENT_STRATEGIES, experiment_config, main

def test_only_strategy_selection_changes():
    baseline = Config(allocation=250, max_price=25)
    experiment = experiment_config(allocation=250, max_price=25)
    assert experiment.strategies == ('uptrend_pullback',)
    assert replace(experiment, strategies=baseline.strategies) == baseline

def test_wrapper_uses_uptrend_only_and_restores_factory(monkeypatch):
    original = multi_pilot.Config
    seen = []
    def fake_main():
        seen.append(multi_pilot.Config(allocation=300, max_price=25))
    monkeypatch.setattr(multi_pilot, 'main', fake_main)
    main()
    assert seen[0].strategies == EXPERIMENT_STRATEGIES == ('uptrend_pullback',)
    assert seen[0].starting_equity == 2000
    assert seen[0].risk_per_position == 20
    assert seen[0].max_price == 25
    assert multi_pilot.Config is original

def test_other_strategies_cannot_be_reenabled_through_factory():
    cfg = experiment_config(strategies=('vwap_reclaim', 'support_bounce', 'breakout_retest'))
    assert cfg.strategies == ('uptrend_pullback',)
