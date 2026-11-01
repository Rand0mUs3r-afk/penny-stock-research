"""Synthetic correctness fixtures, not financial-performance evidence."""
from datetime import datetime,timedelta,timezone
from penny_lab.models import Bar
from penny_lab.config import Config,STRATEGIES,LAB_STRATEGIES
from penny_lab.lab_setups import pattern,overhead_reference,names_at

def bars(rows):
    start=datetime(2026,1,5,14,35,tzinfo=timezone.utc)
    return [Bar('FIXTURE',start+timedelta(minutes=5*i),*row) for i,row in enumerate(rows)]

def test_registry_keeps_old_defaults():
    assert Config().strategies==STRATEGIES
    assert Config(strategies=LAB_STRATEGIES).strategies==LAB_STRATEGIES

def test_orb_requires_opening_range_then_first_break():
    h=bars([(2,2.02,1.98,2,10000)]*3+[(2,2.08,1.99,2.07,20000)])
    assert pattern(h,'opening_range_breakout') is not None
    h+=bars([(2,2.1,1.99,2.09,20000)])
    assert pattern(h[:3],'opening_range_breakout') is None

def test_failed_breakdown_recovery_is_not_an_ordinary_bounce():
    h=bars([(2,2.04,1.98,2,10000)]*12+[(1.99,2.03,1.95,2.02,15000),(2.02,2.08,1.99,2.07,20000)])
    assert pattern(h,'failed_breakdown_recovery') is not None
    assert pattern(h[:12],'failed_breakdown_recovery') is None

def test_overhead_high_must_be_above_price_and_confirmed():
    h=bars([(2,2.02,1.98,2,10000)]*6)
    assert overhead_reference(h) is None
    ref={'target':2.5,'reference_time':'2026-01-02T16:00:00-05:00','reference_rule':'previous_session'}
    assert overhead_reference(h,ref)==ref
    assert overhead_reference(h,{**ref,'target':1.5}) is None

def test_mix_windows_are_separate():
    assert names_at('time_separated_mix',datetime(2026,1,5,15,0,tzinfo=timezone.utc))==('opening_range_breakout',)
    assert names_at('time_separated_mix',datetime(2026,1,5,18,0,tzinfo=timezone.utc))==('compression_continuation',)

def test_compression_requires_rising_impulse_and_volume():
    h=bars([(2,2.05,1.95,2,10000)]*4+[(2.1,2.3,2.08,2.25,10000)]*4+[(2.2,2.24,2.18,2.21,10000)]*4+[(2.22,2.28,2.20,2.27,20000)])
    assert pattern(h,'compression_continuation') is not None
