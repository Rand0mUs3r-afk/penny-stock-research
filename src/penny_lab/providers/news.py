from datetime import datetime, timezone


def current_news(symbol: str, count: int = 10) -> dict:
    """Current context only; never used by the historical signal engine."""
    import yfinance as yf
    return {"symbol": symbol, "first_observed_at": datetime.now(timezone.utc).isoformat(),
            "historical_signal_eligible": False, "source": "yfinance",
            "items": yf.Ticker(symbol).get_news(count=count)}
