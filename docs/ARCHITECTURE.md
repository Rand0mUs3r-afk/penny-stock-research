# Architecture

`config` -> `providers` -> validated `Bar` -> causal `strategies.scan` -> ranked transient candidates -> `risk.size_position` -> shared-cash `engine` -> ledgers and exploratory metrics.

- `models.py`: bars, signals, positions, completed trades.
- `config.py`: immutable validated experiment configuration.
- `providers/base.py`: provider protocol and fail-closed OTC placeholder.
- `providers/alpaca.py`: GET-only credential-gated HTTP adapter, pagination/retries, no trading client and no order endpoint.
- `providers/csv_data.py`: input/provenance checks.
- `providers/news.py`: isolated optional current-news context.
- `strategies.py`: four deterministic completed-bar hypotheses.
- `risk.py`: allocation/cash/stop/participation sizing, cost-aware planned risk.
- `engine.py`: shared portfolio, next-bar fills, stop/target/EOD exits, rejected candidates and metrics.
- `cli.py`: keyless status, private data download, imported-data backtest and exports.
- `tests/`: offline correctness fixtures only; never evidence of trading returns.

A signal is created only at completed bar end. The next bar open is that same wall-clock boundary; its signal information is already available, with adverse-cost assumptions standing in for latency. Marking and exit decisions occur during the next bar and are timestamped at its end. All new entries are allocated before any same-bar exits are credited to avoid spending future proceeds.

Fixed USD 250/300 allocation means compounding increases the number of fundable positions, not unlimited growth of every position. Liquidity/risk/signal availability may leave cash idle. No rule forces capital into unqualified setups.

Data, environment files and result directories are ignored by Git. No data-vendor outputs or headlines are automatically committed. No background task, scheduled trading workflow or real-order path exists.
