"""Synthetic software fixtures only."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import pytest
from penny_lab.config import Config
from penny_lab.models import Bar
from penny_lab.validation import split_days,stressed_config,checked_bytes,gate

def test_chronological_split_has_no_overlap():
    days=[f'2026-01-{i:02d}' for i in range(1,11)]
    result=split_days(days[::-1])
    assert len(result['development'])==7
    assert len(result['later_period'])==3
    assert max(result['development'])<min(result['later_period'])
    assert not set(result['development'])&set(result['later_period'])

def test_insufficient_dates_are_not_a_holdout():
    assert split_days(['2026-01-01'])=={'full_sample_only':['2026-01-01']}

def test_stress_changes_only_spread_and_slippage():
    cfg=Config(allocation=250,fee_per_order=.2)
    stressed=stressed_config(cfg,2)
    assert stressed.spread_bps==2*cfg.spread_bps
    assert stressed.slippage_bps==2*cfg.slippage_bps
    assert stressed.allocation==cfg.allocation
    assert stressed.fee_per_order==cfg.fee_per_order
    assert stressed.risk_per_position==20

def test_corrupt_snapshot_fails(tmp_path):
    path=tmp_path/'bars.csv'
    path.write_bytes(b'fixture')
    assert checked_bytes(path,sha256(b'fixture').hexdigest())==b'fixture'
    with pytest.raises(ValueError,match='hash mismatch'):
        checked_bytes(path,sha256(b'changed').hexdigest())

def test_volume_and_vwap_gates():
    t=datetime(2026,1,5,15,0,tzinfo=timezone.utc)
    history=[Bar('FIXTURE',t+timedelta(minutes=5*i),2,2,2,2,100) for i in range(5)]
    assert gate(history,None,'A_baseline')
    assert gate(history,250,'B_rvol')
    assert not gate(history,251,'B_rvol')
    assert not gate(history,250,'C_rvol_vwap')
