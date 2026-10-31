from penny_lab.yahoo_pilot import classify, discover

def test_unknown_not_listed():
    assert classify({}) == ('unknown', '')

def test_otc_not_listed_or_verified_pink():
    assert classify({'exchange': 'PNK'}) == ('otc', 'PNK')

def test_listed_mapping():
    assert classify({'exchange': 'NCM'}) == ('listed', 'NASDAQ')

def test_discovery_failures_explicit():
    class FakeYahoo:
        @staticmethod
        def EquityQuery(*args):
            return args
        @staticmethod
        def screen(*args, **kwargs):
            raise RuntimeError('rate limited')
    events = []
    assert discover(FakeYahoo, 2, events) == []
    assert len(events) == 2
    assert all(e['status'] == 'failed' for e in events)
