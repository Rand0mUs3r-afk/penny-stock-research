"""Causal monthly decisions, benchmarks, costs and constrained execution."""
import calendar
from dataclasses import replace
from datetime import date,timedelta
import pytest
from penny_lab.monthly_trend import Daily,month_signals,partitions,replay,summary_text


def fixture():
    warm=[]
    for i in range(13):
        year=2020+i//12
        month=i%12+1
        day=date(year,month,calendar.monthrange(year,month)[1]).isoformat()
        p=100+i
        warm.append(Daily(day,p,p+1,p-1,p))
    ends={b.day for b in warm}|{'2021-02-26','2021-03-31'}
    days=[]
    current=date(2021,2,1)
    while current<=date(2021,3,19):
        if current.weekday()<5:
            days.append(current.isoformat())
        current+=timedelta(days=1)
    data={'A':warm+[Daily(d,114,115,113,114) for d in days]}
    return data,days,ends


def test_ten_completed_months_and_strict_greater():
    data,days,ends=fixture()
    warm=data['A'][:13]
    signals=month_signals(warm,ends)
    assert warm[8].day not in signals
    assert signals[warm[9].day]
    flat=[replace(b,open=100,high=101,low=99,close=100) for b in warm]
    assert not any(month_signals(flat,ends).values())


def test_partial_month_not_used():
    data,days,ends=fixture()
    signals=month_signals(data['A'],ends)
    assert days[-1] not in signals


def test_future_price_cannot_change_earlier_portfolio():
    data,days,ends=fixture()
    first=replay(data,days[:2],ends)
    changed={'A':[replace(b,open=900,high=901,low=899,close=900) if b.day=='2021-02-26' else b for b in data['A']]}
    second=replay(changed,days[:2],ends)
    assert first['orders']==second['orders']
    assert first['summary']==second['summary']


def test_month_end_signal_executes_next_session():
    data,days,ends=fixture()
    data['A']=[replace(b,low=.5,close=1) if b.day=='2021-02-26' else b for b in data['A']]
    result=replay(data,['2021-02-01','2021-02-26','2021-03-01'],ends,spread_bps=0,slippage_bps=0)
    sells=[o for o in result['orders'] if o['side']=='sell']
    assert any(o['day']=='2021-03-01' and o['reason']=='trend_off' for o in sells)
    assert not any(o['day']=='2021-02-26' for o in sells)


def test_zero_cost_flat_returns_match_start():
    data,days,ends=fixture()
    result=replay(data,days,ends,spread_bps=0,slippage_bps=0)
    assert result['summary']['final_equity']==pytest.approx(2000)
    assert result['summary']['total_modeled_costs']==0


def test_costs_not_removed_to_manufacture_profit():
    data,days,ends=fixture()
    result=replay(data,days,ends)
    s=result['summary']
    assert s['net_pnl']<0
    assert s['gross_pnl_same_positions']==pytest.approx(0,abs=1e-8)
    assert s['gross_pnl_same_positions']-s['total_modeled_costs']==pytest.approx(s['net_pnl'])


def test_45_day_cap_and_no_same_day_reentry():
    data,days,ends=fixture()
    result=replay(data,days,ends,'trend_45_capped')
    limited=[o for o in result['orders'] if o['reason']=='45_day_limit']
    assert limited and limited[0]['day']=='2021-03-18'
    assert not any(o['day']=='2021-03-18' and o['side']=='buy' for o in result['orders'])


def test_capped_profile_retains_cash_and_position_ceiling():
    data,days,ends=fixture()
    result=replay(data,days[:2],ends,'buy_hold_capped')
    assert result['summary']['final_cash']>=1700-1e-7
    assert all(o['notional']+o['modeled_cost']<=300+1e-8 for o in result['orders'] if o['side']=='buy')


def test_buy_hold_does_not_monthly_rebalance():
    data,days,ends=fixture()
    result=replay(data,days,ends,'buy_hold')
    assert len(result['orders'])==1
    assert result['orders'][0]['side']=='buy'


def test_overnight_stop_gap_uses_open():
    data,days,ends=fixture()
    data['A']=[replace(b,open=80,high=81,low=79,close=80) if b.day==days[1] else b for b in data['A']]
    result=replay(data,days[:2],ends,'trend_45_capped')
    sale=[o for o in result['orders'] if o['side']=='sell'][0]
    assert sale['reason']=='gap_stop' and sale['raw_unit_price']==80
    assert sale['realized_pnl'] < -20


def test_equity_reconciles_realized_and_unrealized():
    data,days,ends=fixture()
    for profile in ('trend','buy_hold','trend_45_capped','buy_hold_capped'):
        s=replay(data,days,ends,profile)['summary']
        assert s['starting_equity']+s['realized_pnl']+s['unrealized_pnl']==pytest.approx(s['final_equity'])


def test_normalization_scale_does_not_change_fractional_returns():
    data,days,ends=fixture()
    scaled={'A':[Daily(b.day,b.open*7,b.high*7,b.low*7,b.close*7) for b in data['A']]}
    assert replay(data,days,ends)['summary']['final_equity']==pytest.approx(replay(scaled,days,ends)['summary']['final_equity'])


def test_summary_and_periods():
    data,days,ends=fixture()
    s=replay(data,days,ends)['summary']
    text=summary_text([{'period':'full','profile':'trend','cost_multiple':1,**s}])
    assert 'Starting equity' in text and 'Final equity' in text and 'Gross P&L' in text
    parts=partitions(days)
    assert not set(parts['earlier'])&set(parts['later'])
    assert parts['earlier']+parts['later']==parts['full']


def test_missing_bars_fail_closed():
    data,days,ends=fixture()
    with pytest.raises(ValueError,match='missing'):
        replay({'A':data['A'][:-1]},days,ends)
