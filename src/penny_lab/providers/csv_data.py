import csv
import json
from datetime import datetime
from pathlib import Path
from ..models import Bar
from .base import CoverageError


def read_dataset(csv_path: str, manifest_path: str) -> tuple[list[Bar], dict]:
    manifest = json.loads(Path(manifest_path).read_text())
    required = ("source", "feed", "universe", "price_adjustment", "timeframe_minutes",
                "timestamp_convention", "symbols", "survivorship_warning", "corporate_actions_reviewed")
    if any(k not in manifest for k in required):
        raise CoverageError("Incomplete provenance manifest; see docs/DATA_CONTRACT.md")
    if manifest["universe"] != "listed_under_10":
        raise CoverageError("OTC input is unsupported until a dedicated provider is implemented")
    if manifest["price_adjustment"] != "raw" or manifest["timestamp_convention"] != "bar_end":
        raise CoverageError("Require raw prices and bar_end timestamps")
    if manifest["timeframe_minutes"] != 5:
        raise CoverageError("Only five-minute input is supported in the foundation")
    if manifest["corporate_actions_reviewed"] is not True:
        raise CoverageError("Review corporate actions and partition split-affected sessions before running")
    symbols = manifest["symbols"]
    allowed_exchanges = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "NYSEARCA", "NYSEAMERICAN"}
    if not symbols or any(v not in allowed_exchanges for v in symbols.values()):
        raise CoverageError("Manifest must identify listed exchanges; OTC/unknown are not allowed")
    bars = []
    with Path(csv_path).open(newline="") as f:
        reader = csv.DictReader(f)
        if not {"timestamp", "symbol", "open", "high", "low", "close", "volume"} <= set(reader.fieldnames or []):
            raise ValueError("Invalid CSV columns")
        for row in reader:
            if row["symbol"] not in symbols:
                raise CoverageError("CSV symbol missing exchange provenance")
            bars.append(Bar(row["symbol"], datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                            *(float(row[k]) for k in ("open", "high", "low", "close", "volume"))))
    if not bars:
        raise CoverageError("No bars; no results will be fabricated")
    bars.sort(key=lambda b: (b.timestamp, b.symbol))
    keys = [(b.timestamp, b.symbol) for b in bars]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate symbol/timestamp bars")
    return bars, manifest
