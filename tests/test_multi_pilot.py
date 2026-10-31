import pytest
from penny_lab.multi_pilot import price_band, select_history
from penny_lab.config import Config

def test_price_bands_and_ceiling():
    assert price_band(4.99) == 'below_5'
    assert price_band(5) == '5_to_below_10'
    assert price_band(10) == '10_to_below_25'
    assert Config(max_price=25).max_price == 25

def test_yahoo_primary_without_alpaca_call():
    def forbidden():
        raise AssertionError('Should not fetch secondary')
    result = select_history([('Yahoo', 'Y', lambda: 'whole yahoo window'), ('Alpaca', 'sip', forbidden)], lambda frame: frame)
    assert result[2] == 'Yahoo'
    assert result[4] == []

def test_validation_failure_triggers_whole_window_fallback():
    def validate(frame):
        if frame == 'bad':
            raise ValueError('No complete sessions')
        return frame
    result = select_history([('Yahoo', 'Y', lambda: 'bad'), ('Alpaca', 'sip', lambda: 'whole alpaca window')], validate)
    assert result[0] == 'whole alpaca window'
    assert result[2:4] == ('Alpaca', 'sip')
    assert len(result[4]) == 1

def test_all_providers_fail_explicitly():
    def fail():
        raise ValueError('missing credentials')
    with pytest.raises(ValueError, match='missing credentials'):
        select_history([('Alpaca', 'sip', fail)], lambda frame: frame)
