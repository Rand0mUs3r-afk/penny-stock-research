"""The active CLI never starts funded replay before September 1, 2026."""
import pytest
from penny_lab.shared_monthly import entry_start_date


@pytest.mark.parametrize('requested,expected', [
    ('2016-11-01','2026-09-01'),
    ('2026-08-31','2026-09-01'),
    ('2026-09-01','2026-09-01'),
    ('2026-09-02','2026-09-02'),
    ('2027-01-01','2027-01-01'),
])
def test_entry_start_is_september_or_later(requested,expected):
    assert entry_start_date(requested)==expected


def test_invalid_entry_date_is_rejected():
    with pytest.raises(ValueError):
        entry_start_date('not-a-date')
