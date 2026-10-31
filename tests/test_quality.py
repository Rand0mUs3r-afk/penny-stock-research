"""Synthetic software fixtures, not financial results."""
from penny_lab.quality import select_coverage, reference_mean

def test_incomplete_primary_escalates_without_profit_selection():
    frame,name,feed,reports=select_coverage([('Yahoo','Y',lambda:.1),('Alpaca','sip',lambda:.9)],lambda x:(x,{}))
    assert name=='Alpaca' and frame==.9 and len(reports)==2

def test_good_primary_does_not_fetch_secondary():
    def forbidden():
        raise AssertionError('unexpected secondary request')
    result=select_coverage([('Yahoo','Y',lambda:1),('Alpaca','sip',forbidden)],lambda x:(x,{}))
    assert result[1]=='Yahoo' and len(result[3])==1

def test_no_coverage_is_explicit():
    frame,name,feed,reports=select_coverage([('Yahoo','Y',lambda:0)],lambda x:(x,{}))
    assert frame is None and name is None

def test_reference_missing_day_not_twenty_day_cascade():
    days=[f'2026-01-{i:02d}' for i in range(1,23)]
    cumulative={(d,'12:00'):100 for d in days[:20] if d!=days[5]}
    avg,count=reference_mean(days,days[20],'12:00',cumulative,set(),minimum=12)
    assert avg==100 and count==19
    assert reference_mean(days,days[20],'12:00',cumulative,set(),minimum=20)[0] is None

def test_future_and_split_history_excluded():
    days=[f'2026-01-{i:02d}' for i in range(1,23)]
    cumulative={(d,'12:00'):100 for d in days}
    cumulative[(days[21],'12:00')]=999999
    assert reference_mean(days,days[20],'12:00',cumulative,set(),minimum=20)==(100,20)
    assert reference_mean(days,days[20],'12:00',cumulative,{days[15]},minimum=12)[0] is None
