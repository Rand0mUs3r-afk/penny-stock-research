"""Causal feature, setup, registration and benchmark accounting tests."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from penny_lab.models import Bar
from penny_lab.config import Config
from penny_lab.sip_setups import COMPONENTS,CASES,detect,vw
from penny_lab.sip_selection import make_selection,catalyst_present
from penny_lab.sip_benchmark import bands,run
from penny_lab.sip_inputs import news_events

START=datetime(2026,1,5,14,35,tzinfo=timezone.utc)
def candles(values,symbol='X',start=START):
    return [Bar(symbol,start+timedelta(minutes=5*i),*v) for i,v in enumerate(values)]

def test_registration():
    assert Config(strategies=COMPONENTS).strategies==COMPONENTS
    assert len(CASES)==10

def test_orb_five_not_fifteen():
    rows=candles([(3,3.1,2.9,3,10000),(3,3.25,3,3.2,20000)])
    assert detect(rows,'sip_orb5',{}) is not None
    assert detect(rows,'sip_orb15',{}) is None

def test_orb_stop_variants():
    rows=candles([(3,3.1,2.9,3,10000)]*3+[(3.1,3.3,3.05,3.25,20000)])
    narrow=detect(rows,'sip_orb15',{},'signal')
    wide=detect(rows,'sip_orb15',{},'range')
    assert wide['stop']<narrow['stop']

def test_earlier_pullback_entry_below_impulse_high():
    rows=candles([(3,3.1,2.9,3,10000)]*6+[(3.12,3.5,3.09,3.48,20000),(3.46,3.46,3.32,3.38,10000),(3.38,3.42,3.31,3.36,10000),(3.36,3.47,3.33,3.45,15000)])
    signal=detect(rows,'sip_pullback',{})
    assert signal is not None and rows[-1].close<3.5
    assert detect(rows[:-1],'sip_pullback',{}) is None
    rows[-2]=replace(rows[-2],low=3.2)
    assert detect(rows,'sip_pullback',{}) is None

def test_reclaim_separate_from_bounce():
    rows=candles([(3,3.1,2.9,3,10000)]*12+[(3.01,3.02,2.92,2.94,10000),(2.95,3.06,2.94,3.04,15000)])
    assert detect(rows,'sip_vwap_reclaim',{}) is not None
    assert detect(rows,'sip_vwap_bounce',{}) is None

def test_gap_requires_premarket_and_gap():
    rows=candles([(3.2,3.25,3.15,3.22,10000),(3.22,3.4,3.2,3.38,20000)])
    assert detect(rows,'sip_gap_go',{}) is None
    assert detect(rows,'sip_gap_go',{'gap':.05,'premarket_high':3.3}) is not None
    assert detect(rows,'sip_gap_go',{'gap':.01,'premarket_high':3.3}) is None

def test_ranking_and_future_prefix_invariance():
    stamp=START
    rows=[Bar('A',stamp,3,3.1,2.9,3,30000),Bar('B',stamp,3,3.1,2.9,3,20000)]
    refs={(s,'2026-01-05','09:35'):10000 for s in ('A','B')}
    features,_=make_selection(rows,refs,{},top_n=1)
    assert features[('A',stamp)]['stocks_in_play_eligible']
    assert not features[('B',stamp)]['stocks_in_play_eligible']
    future=replace(rows[1],timestamp=stamp+timedelta(minutes=5),volume=1000000)
    changed,_=make_selection(rows+[future],refs,{},top_n=1)
    assert changed[('A',stamp)]==features[('A',stamp)]
    assert changed[('B',stamp)]==features[('B',stamp)]

def test_missing_reference_is_not_zero_rvol():
    rows=candles([(3,3.1,2.9,3,10000)])
    features,decisions=make_selection(rows,{}, {})
    assert features[('X',START)]['rvol'] is None
    assert decisions[0]['reason']=='missing_rvol_reference'

def test_news_cannot_arrive_from_future():
    events=[{'symbol':'X','published_at':START+timedelta(minutes=5)}]
    assert not catalyst_present(events,'X',START)
    assert catalyst_present(events,'X',START+timedelta(minutes=5))

def test_news_requires_timezone(tmp_path):
    path=tmp_path/'news.csv'
    path.write_text('symbol,published_at,source,headline\nX,2026-01-05T09:30:00,test,test\n')
    with pytest.raises(ValueError):
        news_events(str(path))

def test_noise_bands_use_prior_days_only():
    rows=candles([(100,101,99,100,10000),(100,102,99,101,10000)])
    mapping={'09:35':rows[0],'09:40':rows[1]}
    assert bands([mapping],100,100,'09:40',minimum=2) is None
    assert bands([mapping,mapping],100,100,'09:40',minimum=2)==101

def benchmark_fixture():
    rows=[]
    closes={}
    for day in range(3):
        start=START+timedelta(days=day)
        values=[]
        for i in range(78):
            price=100 if day<2 or i<5 else 101+(i-5)*.01
            values.append((price,price+.1,price-.05,price+.02,10000))
        rows+=candles(values,symbol='SPY',start=start)
        closes[start.date().isoformat()]='16:00'
    return rows,closes

def test_benchmark_cash_reconciles_and_liquidates():
    rows,closes=benchmark_fixture()
    cfg=Config(allocation=2000,spread_bps=10,slippage_bps=5,fee_per_order=.5)
    result=run(rows,cfg,closes,minimum=2,evaluation_start='2026-01-07')
    assert result['trades']
    assert abs(result['summary']['net_pnl']-sum(t['net_pnl'] for t in result['trades']))<1e-8
    assert result['trades'][-1]['exit_reason']=='session_end'
    assert result['trades'][-1]['hold_minutes']>5

def test_benchmark_warmup_not_traded():
    rows,closes=benchmark_fixture()
    assert run(rows,Config(allocation=2000),closes,minimum=2,evaluation_start='2026-02-01')['trades']==[]

def test_corporate_action_resets_benchmark_history():
    rows,closes=benchmark_fixture()
    assert run(rows,Config(allocation=2000),closes,minimum=2,action_days=('2026-01-06',))['trades']==[]
