# Implementation roadmap

## Foundation committed

Configuration, provider boundaries, read-only Alpaca adapter, optional current Yahoo news, four initial rules, shared-cash exploratory engine, risk controls, CSV/JSON audit outputs and offline CI.

## Next: real data

Verify user's entitlements, intended listed versus true OTC coverage, point-in-time universe, inactive/delisted histories, session calendar and corporate actions. Calibrate realistic cost assumptions using permitted historical quotes. Do not silently change source or fabricate missing observations.

## Next: execution fidelity

Aggregate causal five-minute signals from one-minute data. Add quote-aware spreads, participation/partial fills, halt handling, robust close failures, settlement/account constraints and persistent pending cash/risk reservations if orders span events.

## Next: honest evaluation

Chronological training/validation/untouched test split; walk-forward evaluation; fees/spread/slippage sensitivity; independent per-strategy and combined portfolio runs; uncertainty and minimum-sample flags; trial registry to expose selection bias. No optimizing on the final test set.

## Next: visualization

Interactive dashboard for experiment settings, candlestick entries/exits, stops/targets, reasons, rejected signals, equity/drawdown, per-strategy rankings and downloadable audits. No dashboard or charts are claimed in v0.1.

## Separate OTC milestone

Only add OTC mode after an authorized provider demonstrates tickers, historical coverage, quotes, delistings, corporate actions and licensing. Do not label Alpaca-listed under-USD-10 results as OTC results.
