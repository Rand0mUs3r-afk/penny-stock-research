import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from .config import load_config
from .engine import run
from .providers.csv_data import read_dataset


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Research-only backtesting foundation; no live orders")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="Validate configuration without keys or market data")
    status.add_argument("--config")
    bt = sub.add_parser("backtest", help="Exploratory run on user-provided raw five-minute bars")
    bt.add_argument("--bars", required=True)
    bt.add_argument("--manifest", required=True)
    bt.add_argument("--config")
    bt.add_argument("--output", default="results/run")
    assets = sub.add_parser("assets", help="Read Alpaca active/inactive asset metadata; no trading")
    assets.add_argument("--output", default="data/assets.json")
    fetch = sub.add_parser("fetch", help="Download Alpaca bars and a NON-approved provenance manifest")
    fetch.add_argument("--symbols", required=True, help="Comma-separated symbols; never a claim of a complete historical universe")
    fetch.add_argument("--start", required=True)
    fetch.add_argument("--end", required=True)
    fetch.add_argument("--feed", choices=("sip", "iex"), default="sip")
    fetch.add_argument("--output", default="data/bars.csv")
    news = sub.add_parser("news", help="Fetch current Yahoo context; not a historical signal")
    news.add_argument("--symbol", required=True)
    news.add_argument("--output", default="data/current-news.json")
    args = parser.parse_args()
    if args.command == "status":
        cfg = load_config(args.config)
        print(json.dumps({"mode": "backtest_only", "live_orders": "not_implemented",
                          "data_connected": False, "otc": "not_configured", "config": cfg.to_dict()}, indent=2))
    elif args.command == "backtest":
        cfg = load_config(args.config)
        bars, manifest = read_dataset(args.bars, args.manifest)
        result = run(bars, cfg, manifest)
        result["audit"] = {"run_at": datetime.now(timezone.utc).isoformat(),
                           "bars_sha256": hashlib.sha256(Path(args.bars).read_bytes()).hexdigest(),
                           "manifest_sha256": hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest()}
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)
        (out / "run.json").write_text(json.dumps(result, indent=2, allow_nan=False))
        write_csv(out / "trades.csv", result["trades"], ["symbol", "strategy", "signal_time", "entry_time", "exit_time", "entry", "exit", "shares", "stop", "target", "planned_risk", "net_pnl", "exit_reason", "entry_reason"])
        write_csv(out / "equity.csv", result["equity_curve"], ["timestamp", "equity", "cash", "open_positions", "planned_open_risk"])
        write_csv(out / "ranking.csv", result["strategy_ranking"], ["strategy", "trades", "net_pnl", "expectancy", "win_rate", "profit_factor", "status"])
        write_csv(out / "rejections.csv", result["rejections"], ["timestamp", "symbol", "reason"])
        print(json.dumps(result["summary"], indent=2))
    elif args.command in ("fetch", "assets"):
        from .providers.alpaca import AlpacaData
        provider = AlpacaData(getattr(args, "feed", "sip"))
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        if args.command == "assets":
            path.write_text(json.dumps({"retrieved_at": datetime.now(timezone.utc).isoformat(),
                "warning": "Current active/inactive catalog is NOT a point-in-time historical universe",
                "assets": provider.assets()}, indent=2))
            print(f"Saved current asset catalog to {path}")
        else:
            symbols = sorted(set(s.strip().upper() for s in args.symbols.split(",") if s.strip()))
            bars = provider.bars(symbols, args.start, args.end)
            write_csv(path, [{**asdict(b), "timestamp": b.timestamp.isoformat()} for b in bars],
                      ["symbol", "timestamp", "open", "high", "low", "close", "volume"])
            manifest = {"source": "Alpaca", "feed": args.feed, "universe": "listed_under_10",
                        "price_adjustment": "raw", "timeframe_minutes": 5, "timestamp_convention": "bar_end",
                        "symbols": {s: "VERIFY_LISTED_EXCHANGE" for s in symbols}, "session_closes": {},
                        "corporate_actions_reviewed": False,
                        "survivorship_warning": "Manually selected/current symbols; historical universe completeness not established",
                        "retrieved_at": datetime.now(timezone.utc).isoformat()}
            path.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))
            print("Bars downloaded. Manifest deliberately blocks backtests until exchanges, sessions and corporate actions are reviewed.")
    else:
        from .providers.news import current_news
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current_news(args.symbol), indent=2))
        print("Saved current news context; excluded from historical signals.")


if __name__ == "__main__":
    main()
