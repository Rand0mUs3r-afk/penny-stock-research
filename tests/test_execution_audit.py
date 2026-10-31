"""Synthetic software fixtures only, never performance evidence."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from penny_lab.config import Config
from penny_lab.models import Bar,Signal
from penny_lab.engine import run,exit_decision
from penny_lab.providers.base import CoverageError

T=datetime(2026,1,5,20,50,tzinfo=timezone.utc)
MANIFEST={'universe':'listed_under_10','session_closes':{'2026-01-05':'16:00'}}
def bar(i=0,o=2,h=2.02,l=1.98,c=2,volume=100000):
    return Bar('FIXTURE',T+timedelta(minutes=i),o,h,l,c,volume)
def signal(history,cfg):
    return [Signal('FIXTURE','uptrend_pullback',history[-1].timestamp,1.9,1,'fixture')] if len(history)==1 else []

def test_stop_labels_distinguish_collisions():
    p=SimpleNamespace(stop=1.9,target=2.2)
    assert exit_decision(bar(l=1.8),p,False)==(1.9,'stop')
    assert exit_decision(bar(h=2.3,l=1.8),p,False)==(1.9,'stop_and_target_same_bar')
    assert exit_decision(bar(o=1.8,l=1.7),p,False)==(1.8,'gap_through_stop')

def test_costs_reconcile_and_timing_is_bounded():
    cfg=Config(fee_per_order=.1)
    with patch('penny_lab.engine.scan',side_effect=signal):
        result=run([bar(),bar(5,l=1.8),bar(10)],cfg,MANIFEST)
    row=result['execution_audit'][0]
    assert row['net_pnl']==pytest.approx(row['gross_price_pnl']-row['modeled_spread_cost']-row['modeled_slippage_cost']-row['fees'])
    assert abs(result['cost_attribution']['reconciliation_error'])<1e-8
    assert row['hold_minutes_lower_bound']==0
    assert row['hold_minutes_upper_bound']==5
    assert row['signal_available_at']==row['modeled_entry_at']

def test_execution_bar_final_volume_does_not_set_share_size():
    sizes=[]
    for volume in (1,1000000):
        with patch('penny_lab.engine.scan',side_effect=signal):
            result=run([bar(),bar(5,l=1.8,volume=volume),bar(10)],Config(),MANIFEST)
        sizes.append(result['trades'][0]['shares'])
    assert sizes[0]==sizes[1]

def test_raw_open_below_stop_is_rejected_even_with_entry_costs():
    with patch('penny_lab.engine.scan',side_effect=signal):
        result=run([bar(),bar(5,o=1.899,l=1.89,h=1.91,c=1.9),bar(10)],Config(),MANIFEST)
    assert not result['trades']
    assert any(r['reason']=='gap_invalidated_price_or_stop' for r in result['rejections'])

def test_open_position_data_gap_fails_instead_of_guessed_execution():
    start=T-timedelta(minutes=10)
    rows=[Bar('FIXTURE',start+timedelta(minutes=i),2,2.02,1.98,2,100000) for i in (0,5,20)]
    with patch('penny_lab.engine.scan',side_effect=signal):
        with pytest.raises(CoverageError,match='gap while position open'):
            run(rows,Config(),MANIFEST)
