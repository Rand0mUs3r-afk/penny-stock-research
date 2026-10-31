"""Coarse five-minute bar simulation. NOT quote-accurate execution."""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, time, timedelta
from statistics import mean
from zoneinfo import ZoneInfo
from .config import Config
from .models import Bar, Position, Trade
from .providers.base import CoverageError
from .risk import adverse_price, size_position
from .strategies import scan

NY = ZoneInfo("America/New_York")


def rank_trades(trades: list[Trade], strategies: tuple[str, ...]) -> list[dict]:
    rows = []
    for name in strategies:
        chosen = [t for t in trades if t.strategy == name]
        gains = sum(max(t.net_pnl, 0) for t in chosen)
        losses = -sum(min(t.net_pnl, 0) for t in chosen)
        expectancy = mean(t.net_pnl for t in chosen) if chosen else None
        rows.append({"strategy": name, "trades": len(chosen), "net_pnl": sum(t.net_pnl for t in chosen),
                     "expectancy": expectancy,
                     "win_rate": sum(t.net_pnl > 0 for t in chosen) / len(chosen) if chosen else None,
                     "profit_factor": gains / losses if losses else None,
                     "status": "exploratory_in_sample" if chosen else "no_trades"})
    return sorted(rows, key=lambda r: (r["expectancy"] is None, -(r["expectancy"] or 0), r["strategy"]))


def run(bars: list[Bar], cfg: Config, manifest: dict) -> dict:
    if cfg.universe != "listed_under_10" or manifest.get("universe") != cfg.universe:
        raise CoverageError("OTC requires a dedicated data integration; no silent substitution")
    sessions = manifest.get("session_closes", {})
    if not sessions:
        raise CoverageError("Explicit exchange-calendar session_closes required in manifest")
    # Calendar is input provenance, not guessed from weekdays.
    groups = defaultdict(list)
    seen = set()
    for bar in bars:
        key = (bar.symbol, bar.timestamp)
        if key in seen:
            raise ValueError("Duplicate bar")
        seen.add(key)
        local = bar.timestamp.astimezone(NY)
        day = local.date().isoformat()
        if day not in sessions:
            raise CoverageError(f"Calendar missing for {day}")
        close_time = time.fromisoformat(sessions[day])
        if not time(9, 35) <= close_time <= time(16):
            raise CoverageError("Invalid session close")
        if time(9, 35) <= local.time() <= close_time:
            if bar.volume <= 0:
                raise CoverageError("Zero-volume bars cannot establish executable fills; clean or investigate input")
            if local.second or local.microsecond or local.minute % 5:
                raise ValueError("Bars must align to five-minute boundaries")
            groups[(day, bar.symbol)].append(bar)
    if not groups:
        raise CoverageError("No regular-hours bars")
    for (day, symbol), items in groups.items():
        items.sort(key=lambda b: b.timestamp)
        if items[-1].timestamp.astimezone(NY).time() != time.fromisoformat(sessions[day]):
            raise CoverageError(f"{symbol} {day}: missing session-close bar; cannot fabricate liquidation")
    events = defaultdict(list)
    for items in groups.values():
        for bar in items:
            events[bar.timestamp].append(bar)
    cash = cfg.starting_equity
    positions, pending, histories, last_prices = {}, {}, {}, {}
    trades, rejects, curve = [], [], []
    max_equity, max_drawdown = cash, 0.0

    def reject(stamp, symbol, reason):
        rejects.append({"timestamp": stamp.isoformat(), "symbol": symbol, "reason": reason})

    for stamp, batch in sorted(events.items()):
        batch.sort(key=lambda b: b.symbol)
        current = {b.symbol: b for b in batch}
        # Entries processed before any same-bar exits: no reuse of future proceeds.
        waiting, pending = pending, {}
        for symbol, (signal, prior_volume) in sorted(waiting.items(), key=lambda item: (-item[1][0].score, item[0])):
            bar = current.get(symbol)
            if bar is None or stamp - signal.timestamp != timedelta(minutes=cfg.timeframe_minutes):
                reject(stamp, symbol, "missing_next_bar; pending signal expired")
                continue
            if symbol in positions:
                reject(stamp, symbol, "duplicate_position")
                continue
            entry = adverse_price(bar.open, True, cfg)
            if bar.volume <= 0 or entry >= cfg.max_price or entry <= signal.stop:
                reject(stamp, symbol, "zero_volume_or_gap_invalidated_price_or_stop")
                continue
            open_risk = sum(p.planned_risk for p in positions.values())
            room = cfg.risk_per_position if cfg.portfolio_risk_cap is None else max(0, cfg.portfolio_risk_cap - open_risk)
            shares, risk = size_position(entry, signal.stop, cash, room, prior_volume, cfg)
            if shares <= 0:
                reject(stamp, symbol, "cash_risk_or_prior_volume_limit")
                continue
            cash -= shares * entry + cfg.fee_per_order
            target = entry + cfg.reward_risk * (entry - signal.stop)
            positions[symbol] = Position(signal, stamp - timedelta(minutes=cfg.timeframe_minutes),
                                         entry, shares, signal.stop, target, risk, cfg.fee_per_order)
        for bar in batch:
            symbol = bar.symbol
            local = stamp.astimezone(NY)
            day = local.date().isoformat()
            at_close = local.time() == time.fromisoformat(sessions[day])
            position = positions.get(symbol)
            if position:
                raw_exit, why = None, ""
                if bar.open <= position.stop:
                    raw_exit, why = bar.open, "gap_through_stop"
                elif bar.low <= position.stop:
                    raw_exit, why = position.stop, "stop_conservative_if_target_also_touched"
                elif bar.high >= position.target:
                    raw_exit, why = position.target, "target"
                elif at_close:
                    raw_exit, why = bar.close, "session_end"
                if raw_exit is not None:
                    exit_price = adverse_price(raw_exit, False, cfg)
                    cash += position.shares * exit_price - cfg.fee_per_order
                    pnl = position.shares * (exit_price - position.entry) - position.entry_fee - cfg.fee_per_order
                    trades.append(Trade(symbol, position.signal.strategy, position.signal.timestamp.isoformat(),
                                        position.entry_time.isoformat(), stamp.isoformat(), position.entry,
                                        exit_price, position.shares, position.stop, position.target,
                                        position.planned_risk, pnl, why, position.signal.reason))
                    del positions[symbol]
            last_prices[symbol] = bar.close
            key = (day, symbol)
            history = histories.setdefault(key, [])
            if history and stamp - history[-1].timestamp != timedelta(minutes=cfg.timeframe_minutes):
                reject(stamp, symbol, "history_gap; setup warmup reset")
                history.clear()
            history.append(bar)
            if not at_close and symbol not in positions:
                found = scan(history, cfg)
                if found:
                    best = sorted(found, key=lambda s: (-s.score, s.strategy))[0]
                    pending[symbol] = (best, bar.volume)
                    for other in found:
                        if other is not best:
                            reject(stamp, symbol, f"overlapping_setup:{other.strategy};selected:{best.strategy}")
        equity = cash + sum(p.shares * adverse_price(last_prices[s], False, cfg) - cfg.fee_per_order
                            for s, p in positions.items())
        max_equity = max(max_equity, equity)
        max_drawdown = max(max_drawdown, (max_equity - equity) / max_equity)
        curve.append({"timestamp": stamp.isoformat(), "equity": equity, "cash": cash,
                      "open_positions": len(positions), "planned_open_risk": sum(p.planned_risk for p in positions.values())})
    if positions:
        raise CoverageError("Unclosed positions; no artificial end-of-data exits allowed")
    return {"summary": {"starting_equity": cfg.starting_equity, "ending_equity": cash,
                        "net_pnl": cash - cfg.starting_equity, "trades": len(trades),
                        "max_drawdown": max_drawdown,
                        "evaluation": "exploratory_in_sample_not_validated"},
            "trades": [asdict(t) for t in trades], "rejections": rejects, "equity_curve": curve,
            "strategy_ranking": rank_trades(trades, cfg.strategies), "config": cfg.to_dict(),
            "provenance": manifest,
            "limitations": ["Five-minute bars only; not one-minute/quote-accurate execution",
                            "No modeled queue priority, real depth, halt resumption or partial fills",
                            "Prior-bar participation cap is an assumption, not proof of fillability",
                            "Same-bar stop/target ambiguity resolves to stop first",
                            "Bar-end exit timestamps; intrabar exact exit time unknown",
                            "No settlement/margin/PDT account-rule simulation; immediate reuse is research-only",
                            "News never used by historical signals",
                            "No point-in-time security master or walk-forward validation yet",
                            "No profitability evidence until supplied real data is tested"]}
