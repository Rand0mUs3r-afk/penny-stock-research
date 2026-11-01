"""Synthetic software fixtures only."""
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from penny_lab.config import Config
from penny_lab.models import Bar,Signal
from penny_lab.engine import run
from penny_lab.target_policy import POLICY

def simulate(threshold):
    start=datetime(2026,1,5,19,45,tzinfo=timezone.utc)
    bars=[Bar('FIXTURE',start+timedelta(minutes=5*i),2,2.04 if i<12 else 2.02,1.99,2,100000) for i in range(16)]
    def scanner(history,cfg):
        return [Signal('FIXTURE','uptrend_pullback',history[-1].timestamp,1.9,1,'fixture')] if len(history)==14 else []
    policy={**POLICY,'minimum_net_rr':threshold}
    manifest={'universe':'listed_under_10','session_closes':{'2026-01-05':'16:00'},'entry_policy':policy}
    with patch('penny_lab.engine.scan',side_effect=scanner):
        return run(bars,Config(max_price=35),manifest)

def test_sub_one_rr_trade_is_allowed():
    assert POLICY['minimum_net_rr'] is None
    result=simulate(None)
    assert len(result['trades'])==1
    audit=result['execution_audit'][0]
    assert 0<audit['expected_net_rr']<1
    assert audit['minimum_rr_filter_enabled'] is False

def test_explicit_legacy_gate_still_supported():
    result=simulate(1.)
    assert not result['trades']
    assert any(r['reason']=='historical_high_insufficient_net_rr' for r in result['rejections'])
