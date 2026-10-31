"""Read-only Yahoo coverage pilot. OTC simulation remains explicitly blocked."""
import argparse
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .config import Config
from .engine import run
from .models import Bar

EXCHANGES = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NYQ": "NYSE", "ASE": "AMEX", "PCX": "ARCA", "BTS": "BATS"}

def classify(info):
    code = info.get("exchange", "")
    if code in EXCHANGES:
        return "listed", EXCHANGES[code]
    if code in {"PNK", "OQB", "OQX", "OTC"}:
        return "otc", code
    return "unknown", code

def write_table(path, rows, fields):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def discover(yf, limit, events):
    symbols = []
    queries = [
        ("otc", yf.EquityQuery("and", [yf.EquityQuery("eq", ["region", "us"]), yf.EquityQuery("eq", ["exchange", "PNK"]), yf.EquityQuery("btwn", ["intradayprice", 0.000001, 9.999999])])),
        ("us_under_10", yf.EquityQuery("and", [yf.EquityQuery("eq", ["region", "us"]), yf.EquityQuery("btwn", ["intradayprice", 0.000001, 9.999999])]))]
    for name, query in queries:
        try:
            response = yf.screen(query, size=limit, sortField="dayvolume", sortAsc=False)
            found = [r["symbol"] for r in response.get("quotes", []) if r.get("symbol")]
            events.append({"source": name, "status": "ok", "count": len(found)})
            symbols.extend(found)
        except Exception as exc:
            events.append({"source": name, "status": "failed", "error": str(exc)})
    return list(dict.fromkeys(symbols))[:2 * limit]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="", help="Optional comma-separated Yahoo symbols; empty uses Yahoo screens")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=25, help="Candidates per screen, maximum 100")
    parser.add_argument("--allocation", type=float, choices=(250., 300.), default=300.)
    parser.add_argument("--output", default="results/yahoo-pilot")
    args = parser.parse_args()
    if not 1 <= args.days <= 59 or not 1 <= args.limit <= 100:
        parser.error("days must be 1..59 and limit 1..100")
    import yfinance as yf
    import pandas as pd
    import pandas_market_calendars as mcal
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    schedule = mcal.get_calendar("NYSE").schedule(start_date=start.date(), end_date=end.date())
    calendar = {}
    for _, session in schedule.iterrows():
        if session.market_open >= pd.Timestamp(start) and session.market_close < pd.Timestamp(end):
            calendar[session.market_open.date().isoformat()] = session
    events, coverage, accepted, sessions = [], [], [], {}
    symbols = list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(",") if s.strip())) if args.symbols else discover(yf, args.limit, events)
    if len(symbols) > 200:
        parser.error("Maximum 200 explicit symbols per pilot run")
    for symbol in symbols:
        row = {"symbol": symbol, "status": "rejected", "provider": "Yahoo/yfinance", "market": "unknown", "exchange": "", "bars_returned": 0, "sessions_used": 0, "sessions_rejected": 0}
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.get_info()
            market, exchange = classify(info)
            row.update(market=market, exchange=exchange)
            if info.get("quoteType") != "EQUITY" or info.get("currency") != "USD":
                raise ValueError("Require verified USD equity metadata")
            frame = ticker.history(start=start, end=end, interval="5m", auto_adjust=False, back_adjust=False, actions=True, repair=False, prepost=False, raise_errors=True)
            if frame.empty:
                raise ValueError("No five-minute history returned")
            if frame.index.tz is None:
                raise ValueError("Missing timestamp timezone")
            row.update(bars_returned=len(frame), first_bar=str(frame.index.min()), last_bar=str(frame.index.max()))
            frame.to_csv(out / ("history-" + ''.join(c for c in symbol if c.isalnum() or c in '-_.') + ".csv"))
            if market == "otc":
                row.update(status="coverage_only", reason="OTC data downloaded; existing engine does not yet support OTC simulation. Pink tier not verified.")
                continue
            if market != "listed":
                raise ValueError("Unknown venue; never substitute a listed classification")
            if any(float(frame.get(col, pd.Series(dtype=float)).fillna(0).abs().sum()) > 0 for col in ("Stock Splits", "Dividends")):
                raise ValueError("Corporate action within window; manual review required")
            symbol_bars = []
            for day, session in calendar.items():
                piece = frame[(frame.index >= session.market_open) & (frame.index < session.market_close)]
                expected = pd.date_range(session.market_open, session.market_close, freq="5min", inclusive="left")
                valid = len(piece) == len(expected) and piece.index.tz_convert("UTC").equals(expected.tz_convert("UTC"))
                values = piece[["Open", "High", "Low", "Close", "Volume"]]
                valid = valid and all(math.isfinite(float(v)) and float(v) > 0 for v in values.to_numpy().ravel())
                valid = valid and all(r.Low <= min(r.Open, r.Close) <= max(r.Open, r.Close) <= r.High for r in piece.itertuples())
                if not valid:
                    row["sessions_rejected"] += 1
                    continue
                for stamp, r in piece.iterrows():
                    symbol_bars.append(Bar(symbol, (stamp + pd.Timedelta(minutes=5)).to_pydatetime(), *[float(r[c]) for c in ("Open", "High", "Low", "Close", "Volume")]))
                sessions[day] = session.market_close.tz_convert("America/New_York").strftime("%H:%M")
                row["sessions_used"] += 1
            if not symbol_bars:
                raise ValueError("No complete positive-volume sessions; no invented fills")
            accepted.extend(symbol_bars)
            row.update(status="accepted_listed", reason="Exploratory complete-session sample; automated action checks only")
        except Exception as exc:
            row["reason"] = str(exc)
        finally:
            coverage.append(row)
    audit = {"retrieved_at": end.isoformat(), "discovery": events, "coverage": coverage, "warnings": ["Today's screened/manual symbols are not a point-in-time universe", "Complete-session filtering creates selection bias", "OTC histories are coverage-only; no OTC strategy performance is claimed", "Yahoo bars have no verified historical spreads; costs are uncalibrated", "Automated corporate-action checks are not a comprehensive review", "No historical news features; no live or paper broker orders"], "arguments": vars(args)}
    (out / "coverage.json").write_text(json.dumps(audit, indent=2))
    write_table(out / "coverage.csv", coverage, ["symbol", "market", "exchange", "status", "reason", "bars_returned", "sessions_used", "sessions_rejected", "first_bar", "last_bar"])
    if accepted:
        cfg = Config(allocation=args.allocation)
        manifest = {"source": "Yahoo/yfinance", "feed": "Yahoo historical aggregates", "universe": "listed_under_10", "price_adjustment": "raw", "timeframe_minutes": 5, "timestamp_convention": "bar_end", "session_closes": sessions, "corporate_actions_reviewed": False, "automated_action_check": True, "symbols": {r["symbol"]: r["exchange"] for r in coverage if r["status"] == "accepted_listed"}, "survivorship_warning": audit["warnings"]}
        result = run(accepted, cfg, manifest)
        result["limitations"].extend(audit["warnings"])
        (out / "run.json").write_text(json.dumps(result, indent=2, allow_nan=False))
        for name, key in (("trades", "trades"), ("ranking", "strategy_ranking"), ("equity", "equity_curve"), ("rejections", "rejections")):
            rows = result[key]
            write_table(out / (name + ".csv"), rows, list(rows[0]) if rows else ["status"])
        (out / "SUMMARY.txt").write_text(json.dumps(result["summary"], indent=2) + "\nExploratory LISTED-only shared-portfolio ranking. OTC coverage is separate. Read coverage.json.\n")
    else:
        (out / "SUMMARY.txt").write_text("No eligible listed data. No performance fabricated. Check coverage.json for OTC coverage and failures.\n")
    print((out / "SUMMARY.txt").read_text())

if __name__ == "__main__":
    main()
