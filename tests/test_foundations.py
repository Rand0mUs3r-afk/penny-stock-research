"""Small invented FIXTURES for software correctness; never market data/performance evidence."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch
import pytest
from penny_lab.config import Config, load_config
from penny_lab.engine import run, rank_trades
from penny_lab.models import Bar, Signal
from penny_lab.providers.base import CoverageError, OTCProvider
from penny_lab.providers.csv_data import read_dataset
from penny_lab.providers.alpaca import AlpacaData
from penny_lab.risk import adverse_price, size_position
from penny_lab.strategies import scan

T = datetime(2026, 1, 5, 20, 50, tzinfo=timezone.utc) # 15:50 New York
MANIFEST = {"source": "UNIT_TEST_FIXTURE_NOT_MARKET_DATA", "feed": "fixture", "universe": "listed_under_10",
            "price_adjustment": "raw", "timeframe_minutes": 5, "timestamp_convention": "bar_end",
            "symbols": {"FIXTURE": "NASDAQ"}, "survivorship_warning": "fixture only",
            "corporate_actions_reviewed": True, "session_closes": {"2026-01-05": "16:00"}}


def bar(minutes=0, symbol="FIXTURE", o=2, h=2.02, l=1.98, c=2, volume=100000):
    return Bar(symbol, T + timedelta(minutes=minutes), o, h, l, c, volume)


def signal_for(history, cfg):
    if len(history) == 1:
        return [Signal(history[-1].symbol, "support_bounce", history[-1].timestamp, 1.9, 1, "FIXTURE")]
    return []


def test_defaults_and_toml():
    cfg = load_config("config/default.toml")
    assert cfg.starting_equity == 2000 and cfg.risk_per_position == 20
    assert set(cfg.strategies) == {"breakout_retest", "uptrend_pullback", "support_bounce", "vwap_reclaim"}


@pytest.mark.parametrize("values", [{"allocation": -1}, {"risk_per_position": float("nan")},
    {"max_volume_fraction": 0}, {"strategies": ("unknown",)}, {"timeframe_minutes": 1},
    {"portfolio_risk_cap": -1}, {"slippage_bps": 10001}])
def test_reject_bad_config(values):
    with pytest.raises(ValueError):
        Config(**values)


@pytest.mark.parametrize("cash", [0, 1, 100, 2000])
@pytest.mark.parametrize("entry,stop", [(0.3, 0.2), (2, 1.9), (9, 8.9)])
def test_sizing_respects_all_budgets(cash, entry, stop):
    cfg = Config(fee_per_order=0.25)
    shares, risk = size_position(entry, stop, cash, 15, 10000, cfg)
    assert shares >= 0 and risk <= 15 + 1e-9
    if shares:
        assert shares * entry + cfg.fee_per_order <= min(cash, cfg.allocation) + 1e-9
        assert shares <= 100


def test_stop_must_be_below_entry():
    assert size_position(2, 2.1, 2000, 20, 10000, Config()) == (0, 0.0)


def test_cost_direction():
    cfg = Config()
    assert adverse_price(2, True, cfg) > 2 > adverse_price(2, False, cfg)


def test_otc_fails_closed():
    with pytest.raises(CoverageError, match="OTC"):
        OTCProvider().bars([], "", "")
    with pytest.raises(CoverageError, match="OTC"):
        run([], Config(universe="otc"), {"universe": "otc"})


def test_credentials_required(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(CoverageError, match="Credentials missing"):
        AlpacaData()


def test_provider_paginates_and_converts_start_to_end(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "UNIT_TEST_NOT_A_KEY")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "UNIT_TEST_NOT_A_SECRET")
    provider = AlpacaData()
    calls = []
    def get(url, params):
        calls.append(dict(params))
        row = {"t": "2026-01-05T15:00:00Z", "o": 2, "h": 2, "l": 2, "c": 2, "v": 1}
        return {"bars": {"FIXTURE": [row]}, "next_page_token": "page2"} if len(calls) == 1 else {"bars": {}, "next_page_token": None}
    monkeypatch.setattr(provider, "_get", get)
    rows = provider.bars(["FIXTURE"], "start", "end")
    assert len(calls) == 2 and calls[1]["page_token"] == "page2"
    assert rows[0].timestamp.minute == 5 and calls[0]["adjustment"] == "raw"


def test_invalid_bar_and_duplicate():
    with pytest.raises(ValueError):
        Bar("FIXTURE", datetime(2026, 1, 1), 2, 2, 2, 2, 1)
    with pytest.raises(ValueError, match="Duplicate"):
        run([bar(), bar()], Config(), MANIFEST)


def test_missing_close_or_calendar_rejected():
    with pytest.raises(CoverageError, match="session-close"):
        run([bar()], Config(), MANIFEST)
    with pytest.raises(CoverageError, match="session_closes"):
        run([bar(10)], Config(), {"universe": "listed_under_10"})


def test_no_data_no_fabricated_results():
    with pytest.raises(CoverageError, match="No regular-hours"):
        run([], Config(), MANIFEST)


def test_signal_fills_only_next_bar_and_ambiguous_exit_is_stop():
    bars = [bar(), bar(5, h=2.5, l=1.8), bar(10)]
    with patch("penny_lab.engine.scan", side_effect=signal_for):
        result = run(bars, Config(spread_bps=0, slippage_bps=0), MANIFEST)
    trade = result["trades"][0]
    assert trade["entry_time"] == T.isoformat()
    assert trade["exit_time"] == (T + timedelta(minutes=5)).isoformat()
    assert trade["exit"] == 1.9 and trade["net_pnl"] < 0
    assert result["equity_curve"][0]["cash"] == 2000


def test_shared_cash_no_leverage():
    rows = [bar(m, symbol=s) for m in (0, 5, 10) for s in ("A", "B", "C")]
    cfg = Config(starting_equity=500, allocation=300, spread_bps=0, slippage_bps=0)
    with patch("penny_lab.engine.scan", side_effect=signal_for):
        result = run(rows, cfg, MANIFEST)
    assert min(x["cash"] for x in result["equity_curve"]) >= 0
    assert sum(t["entry"] * t["shares"] for t in result["trades"]) == 500


def test_combined_risk_cap():
    rows = [bar(m, symbol=s) for m in (0, 5, 10) for s in ("A", "B", "C")]
    cfg = Config(portfolio_risk_cap=20, spread_bps=0, slippage_bps=0)
    with patch("penny_lab.engine.scan", side_effect=signal_for):
        result = run(rows, cfg, MANIFEST)
    assert max(x["planned_open_risk"] for x in result["equity_curve"]) <= 20 + 1e-9


def test_price_filter_applies_at_execution():
    with patch("penny_lab.engine.scan", side_effect=signal_for):
        result = run([bar(), bar(5, o=11, h=11, l=11, c=11), bar(10)], Config(), MANIFEST)
    assert not result["trades"] and result["rejections"]


def test_missing_next_bar_does_not_fill_late():
    with patch("penny_lab.engine.scan", side_effect=signal_for):
        result = run([bar(), bar(10)], Config(), MANIFEST)
    assert not result["trades"] and "expired" in result["rejections"][0]["reason"]


def test_no_signal_without_warmup_and_no_history_mutation():
    data = [bar()]
    original = list(data)
    assert scan(data, Config()) == [] and data == original


def test_no_trade_rank_not_infinite():
    assert all(r["expectancy"] is None and r["profit_factor"] is None
               for r in rank_trades([], Config().strategies))


def test_manifest_blocks_unreviewed_actions(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({**MANIFEST, "corporate_actions_reviewed": False}))
    with pytest.raises(CoverageError, match="corporate actions"):
        read_dataset(str(tmp_path / "none.csv"), str(p))


def history_from_values(values):
    start = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    return [Bar("FIXTURE", start + timedelta(minutes=5*i), *row) for i, row in enumerate(values)]


def test_actual_breakout_retest_rule():
    values = [(2, 2.02, 1.98, 2, 10000)] * 7
    values += [(2.01, 2.1, 2, 2.08, 20000), (2.03, 2.08, 2.02, 2.06, 15000)]
    found = scan(history_from_values(values), Config(lookback=6))
    assert "breakout_retest" in {s.strategy for s in found}


def test_actual_support_bounce_rule():
    values = [(2, 2.02, 1.98, 2, 10000)] * 8
    values += [(1.99, 2.04, 1.98, 2.03, 15000)]
    found = scan(history_from_values(values), Config(lookback=6))
    assert "support_bounce" in {s.strategy for s in found}


def test_actual_vwap_reclaim_rule():
    values = [(2, 2.02, 1.98, 2, 10000)] * 7
    values += [(2, 2.01, 1.95, 1.96, 10000), (1.97, 2.12, 1.96, 2.1, 20000)]
    found = scan(history_from_values(values), Config(lookback=6))
    assert "vwap_reclaim" in {s.strategy for s in found}


def test_actual_uptrend_pullback_rule():
    values = [(2, 2.03, 1.98, 2.01, 10000)]
    values += [(2.01, 2.04, 1.99, 2.02, 10000)] * 3
    values += [(2.05, 2.1, 2.03, 2.08, 10000)] * 3
    values += [(2.07, 2.08, 2.04, 2.06, 10000), (2.07, 2.12, 2.05, 2.11, 15000)]
    found = scan(history_from_values(values), Config(lookback=6))
    assert "uptrend_pullback" in {s.strategy for s in found}


def test_zero_volume_bars_fail_instead_of_fabricating_fills():
    with pytest.raises(CoverageError, match="Zero-volume"):
        run([bar(volume=0), bar(10)], Config(), MANIFEST)


def test_gap_exit_can_exceed_planned_risk():
    cfg = Config(spread_bps=0, slippage_bps=0)
    with patch("penny_lab.engine.scan", side_effect=signal_for):
        result = run([bar(), bar(5), bar(10, o=1, h=1.01, l=0.99, c=1)], cfg, MANIFEST)
    trade = result["trades"][0]
    assert trade["net_pnl"] < -trade["planned_risk"] and trade["exit_reason"] == "gap_through_stop"
