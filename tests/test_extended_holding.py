"""Overnight holding, calendar deadlines and final-equity reporting."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from penny_lab.models import Bar
from penny_lab.extended_holding import replay,summary_text
from penny_lab import extended_holding


def fixture(days=55,start=datetime(2026,1,5,14,30,tzinfo=timezone.utc)):
    rows,sessions=[],{}
    for i in range(days):
        opened=start+timedelta(days=i)
        if opened.weekday()>=5:
            continue
        sessions[opened.date().isoformat()]={'open':opened,'close':opened+timedelta(minutes=2)}
        for minute in (1,2):
            rows.append(Bar('X',opened+timedelta(minutes=minute),3,3.03,2.95,3.01,10000))
    first=rows[0].timestamp
    def once(history):
        return {'stop':2.8,'score':1} if history[-1].timestamp==first else None
    return rows,sessions,once


def test_holds_overnight_and_exits_at_45_days():
    rows,sessions,once=fixture()
    result=replay(rows,sessions,signal_fn=once)
    assert len(result['trades'])==1
    trade=result['trades'][0]
    assert trade['exit_reason']=='holding_limit'
    assert trade['holding_calendar_days']==45
    assert result['summary']['open_positions']==0


def test_expiry_on_weekend_exits_next_regular_open():
    rows,sessions,once=fixture(start=datetime(2026,1,7,14,30,tzinfo=timezone.utc))
    result=replay(rows,sessions,signal_fn=once)
    trade=result['trades'][0]
    assert trade['exit_reason']=='holding_limit'
    assert datetime.fromisoformat(trade['exit_time_upper_bound']).weekday()==0
    assert 45<trade['holding_calendar_days']<48


def test_final_equity_includes_unclosed_positions():
    rows,sessions,once=fixture(days=6)
    result=replay(rows,sessions,signal_fn=once)
    summary=result['summary']
    assert summary['closed_trades']==0 and summary['open_positions']==1
    assert summary['final_cash']<summary['final_equity']
    assert abs(summary['final_equity']-summary['starting_equity']-summary['unrealized_pnl'])<1e-8
    assert summary['realized_pnl']==0
    assert summary['final_equity']==summary['ending_equity']


def test_overnight_gap_uses_actual_open_not_stop():
    rows,sessions,once=fixture(days=3)
    rows[2]=replace(rows[2],open=2.7,high=2.75,low=2.65,close=2.72)
    result=replay(rows,sessions,signal_fn=once)
    assert result['trades'][0]['exit_reason']=='gap_stop'
    assert abs(result['trades'][0]['exit']-2.7*.995)<1e-10
    assert abs(result['trades'][0]['reconciliation_error'])<1e-8


def test_missing_session_while_holding_rejected():
    rows,sessions,once=fixture(days=4)
    rows=[b for b in rows if b.timestamp.date().isoformat()!='2026-01-06']
    with pytest.raises(ValueError,match='Missing expected'):
        replay(rows,sessions,signal_fn=once)


def test_fast_oscillator_exit_is_optional(monkeypatch):
    rows,sessions,once=fixture(days=4)
    monkeypatch.setattr(extended_holding,'exit_signal',lambda history:True)
    slow=replay(rows,sessions,signal_fn=once)
    fast=replay(rows,sessions,fast_exits=True,signal_fn=once)
    assert slow['summary']['open_positions']==1
    assert fast['trades'][0]['exit_reason']=='oscillator_next_open'


def test_summary_explicitly_shows_start_and_final():
    rows,sessions,once=fixture(days=3)
    result=replay(rows,sessions,signal_fn=once)
    text=summary_text([(1,result)])
    assert 'Starting equity' in text and 'Final equity' in text
    assert '2000.00' in text and 'Return' in text


def test_realized_plus_unrealized_reconciles():
    rows,sessions,once=fixture()
    result=replay(rows,sessions,signal_fn=once,cost_multiple=2)
    summary=result['summary']
    assert abs(summary['net_pnl']-sum(t['net_pnl'] for t in result['trades']))<1e-7
    assert summary['open_positions']==0
    assert all(t['planned_risk']<=20 for t in result['trades'])
