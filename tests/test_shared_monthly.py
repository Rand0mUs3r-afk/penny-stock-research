"""One-capital-deposit, FIFO dates and shared-strategy accounting."""
from datetime import date,timedelta
import pytest
from penny_lab.shared_monthly import Ledger,replay,render


def fixture():
    days=[]
    day=date(2024,1,1)
    while day<=date(2026,3,31):
        if day.weekday()<5:
            days.append(day.isoformat())
        day+=timedelta(days=1)
    months={d[:7]:d for d in days}
    data={s:{d:{'open':100+(int(d[:4])-2024)*12+int(d[5:7]),'close':100.1+(int(d[:4])-2024)*12+int(d[5:7])} for d in days} for s in ('A','B','C','D','E')}
    return data,set(months.values())


def test_single_starting_account_for_both_strategies():
    data,ends=fixture()
    r=replay(data,ends,'2025-01-02','2026-03-31')
    assert r['summary']['starting_equity']==2000
    assert r['settings']['starting_capital_deposits']==1
    first=[f for f in r['fills'] if f['day']=='2025-01-02']
    assert {f['strategy'] for f in first}=={'buy_hold','monthly_trend'}
    assert abs(sum(f['notional']+f['cost'] for f in first)-1500)<1e-7
    assert abs(r['equity'][0]['cash']-500)<1e-7


def test_shared_cash_and_combined_ticker_cap():
    data,ends=fixture()
    r=replay(data,ends,'2025-01-02','2026-03-31')
    assert all(e['cash']>=-1e-7 for e in r['equity'])
    assert all(f['combined_ticker_value_after']<=300+1e-7 for f in r['fills'] if f['side']=='buy')


def test_fifo_partial_sales_have_exact_dates_and_days():
    ledger=Ledger(.005)
    ledger.transact('monthly_trend','A',2,100,'2025-01-01','test')
    ledger.transact('monthly_trend','A',3,110,'2025-01-11','test')
    ledger.transact('monthly_trend','A',-4,120,'2025-01-21','test')
    assert len(ledger.trades)==2
    assert [t['hold_calendar_days'] for t in ledger.trades]==[20,10]
    assert [t['units'] for t in ledger.trades]==[2,2]
    opened=ledger.marked_positions({'A':120},'2025-01-31')
    assert opened[0]['units']==1
    assert opened[0]['exit_date'] is None and opened[0]['hold_calendar_days']==20
    assert abs(ledger.cash+opened[0]['marked_value']-2000-sum(t['net_pnl'] for t in ledger.trades)-opened[0]['unrealized_pnl'])<1e-7


def test_cannot_spend_other_fictitious_account():
    ledger=Ledger(.005)
    ledger.transact('buy_hold','A',10,100,'2025-01-01','test')
    with pytest.raises(ValueError,match='shared cash'):
        ledger.transact('monthly_trend','B',10,100,'2025-01-01','test')


def test_strategy_pnl_adds_to_single_portfolio_pnl():
    data,ends=fixture()
    r=replay(data,ends,'2025-01-02','2026-03-31')
    assert abs(sum(a['total_pnl'] for a in r['strategy_attribution'])-r['summary']['net_pnl'])<1e-7
    assert abs(r['summary']['realized_pnl']+r['summary']['unrealized_pnl']-r['summary']['net_pnl'])<1e-7


def test_periods_do_not_restart_cash():
    data,ends=fixture()
    r=replay(data,ends,'2025-01-02','2026-03-31')
    earlier,later=r['periods']
    assert later['starting_equity']==earlier['final_equity']
    assert not earlier['cash_reset'] and not later['cash_reset']


def test_all_trade_holding_days_match_dates():
    data,ends=fixture()
    r=replay(data,ends,'2025-01-02','2026-03-31')
    assert r['trades']
    assert all(t['hold_calendar_days']==(date.fromisoformat(t['exit_date'])-date.fromisoformat(t['entry_date'])).days for t in r['trades'])
    assert all(p['exit_date'] is None for p in r['open_positions'])


def test_summary_has_requested_sections():
    data,ends=fixture()
    text=render(replay(data,ends,'2025-01-02','2026-03-31'))
    for label in ('Starting equity','Final equity','Entry date','Exit date','Calendar hold days','Exact ticker holding ledger','Strategy P&L within the same account'):
        assert label in text


def test_strategy_weights_do_not_add_capital():
    data,ends=fixture()
    for weight in (0.,1.):
        r=replay(data,ends,'2025-01-02','2026-03-31',trend_weight=weight)
        assert r['summary']['starting_equity']==2000
        assert all(e['cash']>=-1e-7 for e in r['equity'])
        assert len({f['strategy'] for f in r['fills']})==1
