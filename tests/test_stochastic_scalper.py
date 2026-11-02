"""Signal causality, one-minute execution and bounded holding time."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from penny_lab.models import Bar
from penny_lab.stochastic_scalper import oscillator,signal,replay

START=datetime(2026,1,5,14,31,tzinfo=timezone.utc)
def candles(values,symbol='X'):
    return [Bar(symbol,START+timedelta(minutes=i),*v,10000) for i,v in enumerate(values)]

def test_positive_oversold_cross_in_trend():
    values=[(2+i*.01,2+i*.01+.02,2+i*.01-.02,2+i*.01) for i in range(40)]
    rows=candles(values+[(2.4,2.72,2.39,2.7),(2.4,2.42,2.30,2.32),(2.32,2.34,2.29,2.31),(2.32,2.44,2.31,2.42)])
    found=signal(rows)
    assert found is not None and found['stop']<rows[-1].close
    assert signal(rows[:-1]) is None

def test_flat_range_has_no_oscillator():
    assert oscillator(candles([(3,3,3,3)]*30)) is None
    assert signal(candles([(3,3,3,3)]*30)) is None

def fixture(count=9):
    rows=candles([(3,3.04,2.99,3.02)]*count)
    closes={'2026-01-05':rows[-1].timestamp}
    def once(history):
        return {'stop':2.9,'score':1} if history[-1].timestamp==START else None
    return rows,closes,once

def test_next_open_five_minute_exit_and_costs():
    rows,closes,once=fixture()
    result=replay(rows,closes,signal_fn=once)
    assert len(result['trades'])==1
    trade=result['trades'][0]
    assert trade['entry_time']==rows[0].timestamp.isoformat()
    assert trade['exit_reason']=='five_minute_limit'
    assert trade['hold_minutes_upper_bound']==5
    assert trade['planned_risk']<=20
    assert trade['shares']*trade['entry']<=300
    assert abs(trade['reconciliation_error'])<1e-8
    assert abs(result['summary']['net_pnl']-trade['net_pnl'])<1e-8

def test_stop_on_entry_bar():
    rows,closes,once=fixture()
    rows[1]=replace(rows[1],low=2.8)
    result=replay(rows,closes,signal_fn=once)
    assert result['trades'][0]['exit_reason']=='stop'

def test_session_close_forces_exit():
    rows,closes,once=fixture(4)
    result=replay(rows,closes,signal_fn=once)
    assert result['trades'][0]['exit_reason']=='session_end'

def test_no_fake_fill_across_missing_minute():
    rows,closes,once=fixture()
    with pytest.raises(ValueError,match='gap'):
        replay(rows[:3]+rows[4:],closes,signal_fn=once)

def test_missing_next_bar_expires_pending():
    rows,closes,once=fixture()
    result=replay(rows[:1]+rows[2:],closes,signal_fn=once)
    assert result['trades']==[]
    assert result['rejections'][0]['reason']=='missing_next_bar'

def test_duplicate_bars_rejected():
    rows,closes,once=fixture()
    with pytest.raises(ValueError):
        replay(rows+[rows[0]],closes,signal_fn=once)

def test_late_signal_blocked():
    rows=candles([(3,3.1,2.9,3)]*30)
    rows=[replace(b,timestamp=b.timestamp+timedelta(hours=7)) for b in rows]
    assert signal(rows) is None


def test_oscillator_prefix_has_no_future_dependence():
    rows=candles([(3,3.1,2.9,3.02)]*30)
    earlier=oscillator(rows)
    future=replace(rows[-1],timestamp=rows[-1].timestamp+timedelta(minutes=1),high=30,close=30)
    assert oscillator((rows+[future])[:-1])==earlier


def test_shared_cash_never_multiplied_per_symbol():
    rows,closes,once=fixture()
    combined=[replace(b,symbol=str(i)) for i in range(10) for b in rows]
    result=replay(combined,closes,signal_fn=once)
    assert all(r['cash']>=0 for r in result['equity'])
    assert sum(t['shares']*t['entry'] for t in result['trades'])<=2000
