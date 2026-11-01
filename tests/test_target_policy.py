"""Synthetic fixtures; no market-performance evidence."""
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pytest
from penny_lab.config import Config
from penny_lab.models import Bar,Signal
from penny_lab.engine import run
from penny_lab.target_policy import POLICY,previous_high,raw_price_allowed,net_plan

def test_inclusive_raw_price_range():
    assert raw_price_allowed(1.,POLICY) and raw_price_allowed(35.,POLICY)
    assert not raw_price_allowed(.999,POLICY)
    assert not raw_price_allowed(35.001,POLICY)

def test_target_excludes_pullback_and_confirmation():
    t=datetime(2026,1,5,15,0,tzinfo=timezone.utc)
    history=[Bar('FIXTURE',t+timedelta(minutes=5*i),2,2.4 if i<12 else 9,1.9,2,100000) for i in range(14)]
    assert previous_high(history,12)['target']==2.4
    assert previous_high(history[:3],12) is None

def test_reward_accounts_for_costs_and_fees():
    plan=net_plan(10,9.7,10.45,10,4,Config(fee_per_order=.1))
    assert plan['expected_net_reward']<4.5
    assert plan['expected_net_rr']==pytest.approx(plan['expected_net_reward']/4)

def test_engine_freezes_target_and_closes_same_day():
    t=datetime(2026,1,5,19,45,tzinfo=timezone.utc)
    bars=[Bar('FIXTURE',t+timedelta(minutes=5*i),2,2.4 if i<12 else 2.03,1.99,2,100000) for i in range(16)]
    def scanner(history,cfg):
        return [Signal('FIXTURE','uptrend_pullback',history[-1].timestamp,1.9,1,'fixture')] if len(history)==14 else []
    manifest={'universe':'listed_under_10','session_closes':{'2026-01-05':'16:00'},'entry_policy':dict(POLICY)}
    with patch('penny_lab.engine.scan',side_effect=scanner):
        result=run(bars,Config(max_price=35),manifest)
    assert len(result['trades'])==1
    trade=result['trades'][0]
    assert trade['target']==2.4
    assert trade['exit_reason']=='session_end'
    assert result['execution_audit'][0]['expected_net_rr']>=1
    assert result['execution_audit'][0]['reference_time']<trade['signal_time']
