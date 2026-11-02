"""Monthly signal timing, cost accounting and holding-policy comparisons."""
from datetime import date,timedelta
import pytest
from penny_lab.monthly_trend import replay,summary_text


def fixture():
    first,last=date(2024,1,1),date(2026,3,31)
    days=[]
    day=first
    while day<=last:
        if day.weekday()<5:
            days.append(day.isoformat())
        day+=timedelta(days=1)
    months={}
    for day in days:
        months[day[:7]]=day
    data={s:{day:{'open':factor*(100+((int(day[:4])-2024)*12+int(day[5:7]))),'close':factor*(100+((int(day[:4])-2024)*12+int(day[5:7]))+.1)} for day in days} for s,factor in (('A',1.),('B',2.))}
    return data,set(months.values())


def test_buy_and_hold_buys_once():
    data,ends=fixture()
    result=replay(data,ends,'2025-01-02','2026-03-31','buy_hold')
    assert len(result['fills'])==2
    assert all(t['side']=='buy' for t in result['fills'])


def test_monthly_orders_use_following_session():
    data,ends=fixture()
    result=replay(data,ends,'2025-01-02','2026-03-31')
    days=list(data['A'])
    next_days={days[i+1] for i,d in enumerate(days[:-1]) if d in ends}
    assert all(t['day']=='2025-01-02' or t['day'] in next_days for t in result['fills'])


def test_flat_price_not_above_average():
    data,ends=fixture()
    for values in data.values():
        for row in values.values():
            row.update(open=100.,close=100.)
    result=replay(data,ends,'2025-01-02','2026-03-31')
    assert result['fills']==[]
    assert result['summary']['final_equity']==2000


def test_requires_ten_completed_months():
    data,ends=fixture()
    result=replay(data,ends,'2024-02-01','2024-06-28')
    assert result['fills']==[]
    assert all(not r['invest_next_session'] for r in result['signals'])


def test_45_day_expiry_separate_from_monthly_rule():
    data,ends=fixture()
    result=replay(data,ends,'2025-01-02','2026-03-31','trend_45day_cap')
    assert any(t['reason']=='45_calendar_day_expiry' for t in result['fills'])
    regular=replay(data,ends,'2025-01-02','2026-03-31')
    assert not any(t['reason']=='45_calendar_day_expiry' for t in regular['fills'])


def test_cash_allocation_and_cost_identity():
    data,ends=fixture()
    result=replay(data,ends,'2025-01-02','2026-03-31')
    r=result['summary']
    assert all(t['notional']+t['execution_cost']<=300+1e-7 for t in result['fills'] if t['side']=='buy')
    assert all(t['cash']>=-1e-7 for t in result['equity'])
    assert abs(r['net_pnl']-(r['gross_pnl_on_actual_positions']-r['paid_execution_costs']-r['ending_exit_cost_reserve']))<1e-8


def test_zero_cost_control_has_no_costs():
    data,ends=fixture()
    r=replay(data,ends,'2025-01-02','2026-03-31',cost_multiple=0)['summary']
    assert r['paid_execution_costs']==r['ending_exit_cost_reserve']==0
    assert r['gross_pnl_on_actual_positions']==r['net_pnl']


def test_final_equity_includes_open_units():
    data,ends=fixture()
    result=replay(data,ends,'2025-01-02','2026-03-31')
    assert result['open_positions']
    assert result['summary']['final_equity']>result['summary']['cash']


def test_future_prices_do_not_change_earlier_result():
    data,ends=fixture()
    original=replay(data,ends,'2025-01-02','2025-08-29')
    for values in data.values():
        for day,row in values.items():
            if day>'2025-08-29':
                row.update(open=900.,close=950.)
    changed=replay(data,ends,'2025-01-02','2025-08-29')
    assert changed==original


def test_missing_asset_date_rejected():
    data,ends=fixture()
    del data['A']['2025-01-02']
    with pytest.raises(ValueError):
        replay(data,ends,'2025-01-02','2026-03-31')


def test_high_price_etf_uses_disclosed_fractional_units():
    data,ends=fixture()
    for values in data.values():
        for row in values.values():
            row['open']*=10
            row['close']*=10
    result=replay(data,ends,'2025-01-02','2026-03-31','buy_hold')
    assert all(0<t['units']<1 for t in result['fills'])
    assert 'fractional' in result['settings']['units']


def test_summary_reports_start_final_and_costs():
    data,ends=fixture()
    r=replay(data,ends,'2025-01-02','2026-03-31')['summary']
    text=summary_text([{'period':'test','case':'monthly_trend','cost_multiple':1,**r}])
    assert all(label in text for label in ('Starting equity','Final equity','Paid costs','Drawdown','2000.00'))
