"""GET-only standard-library adapter. No brokerage order endpoints.

This is a connection-ready adapter, not a historical security master.
"""
import json
import os
import time
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .base import CoverageError
from ..models import Bar


class AlpacaData:
    DATA = "https://data.alpaca.markets"
    ASSETS = "https://paper-api.alpaca.markets/v2/assets"

    def __init__(self, feed: str = "sip"):
        if feed not in ("sip", "iex"):
            raise ValueError("Select sip or iex explicitly; no silent feed fallback")
        self.feed = feed
        self._key = os.environ.get("ALPACA_API_KEY", "")
        self._secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if not self._key or not self._secret:
            raise CoverageError("Credentials missing; set ALPACA_API_KEY and ALPACA_SECRET_KEY privately")

    def _get(self, url: str, params: dict):
        request = Request(url + "?" + urlencode(params), headers={
            "APCA-API-KEY-ID": self._key, "APCA-API-SECRET-KEY": self._secret}, method="GET")
        for attempt in range(4):
            try:
                with urlopen(request, timeout=45) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise CoverageError(f"Alpaca HTTP {exc.code}; check access/parameters. No feed fallback.") from None
        raise CoverageError("Alpaca request failed")

    def assets(self) -> list[dict]:
        out = []
        for status in ("active", "inactive"):
            response = self._get(self.ASSETS, {"status": status, "asset_class": "us_equity"})
            out.extend(response)
        return out

    def bars(self, symbols: list[str], start: str, end: str) -> list[Bar]:
        if not symbols:
            raise ValueError("Specify symbols")
        params = {"symbols": ",".join(symbols), "start": start, "end": end,
                  "timeframe": "5Min", "adjustment": "raw", "feed": self.feed,
                  "limit": 10000, "sort": "asc"}
        bars, tokens = [], set()
        while True:
            data = self._get(self.DATA + "/v2/stocks/bars", params)
            for symbol, items in data.get("bars", {}).items():
                for item in items:
                    # Alpaca timestamps bar starts; internal contract uses ends.
                    stamp = datetime.fromisoformat(item["t"].replace("Z", "+00:00")) + timedelta(minutes=5)
                    bars.append(Bar(symbol, stamp, *(float(item[k]) for k in ("o", "h", "l", "c", "v"))))
            token = data.get("next_page_token")
            if not token:
                break
            if token in tokens:
                raise CoverageError("Repeated pagination token")
            tokens.add(token)
            params["page_token"] = token
        if not bars:
            raise CoverageError("No bars returned; confirm feed entitlement and date range")
        missing = set(symbols) - {b.symbol for b in bars}
        if missing:
            raise CoverageError(f"No history for requested symbols: {', '.join(sorted(missing))}")
        return sorted(bars, key=lambda b: (b.timestamp, b.symbol))
