# Yahoo pilot: run without API keys

Open Actions > Yahoo coverage and backtest pilot > Run workflow > main. Leave symbols blank for Yahoo discovery; start with 30 days, 25 candidates per screen, and USD 300 allocation. Wait for completion and open the yahoo-pilot artifact. No Alpaca secrets are used. GitHub Actions account usage/billing limits still apply.

Read SUMMARY.txt and coverage.csv first. coverage.json records scanner failures and limitations. history-*.csv contains returned raw five-minute history. With eligible listed data, run.json, trades.csv, ranking.csv, equity.csv, and rejections.csv contain the existing engine results. A successful job may report no eligible data or no trades. No data or returns are invented.

## Critical scope limitation

This is a coverage pilot for OTC and an exploratory simulation for eligible exchange-listed stocks, NOT an OTC backtester. The existing engine blocks OTC. OTC candidates are downloaded and identified as coverage_only, not relabeled as listed stocks. Yahoo PNK metadata is not independent confirmation of Pink tier. OTC execution support, historical quotes, charts, historical universe reconstruction, and Alpaca fallback are not added here.

Yahoo scan coverage is not exhaustive; the two capped screens are current snapshots. Manual symbols can test coverage beyond scan results. Failed discovery is reported, not replaced with fabricated candidates. Data uses the last 1-59 calendar days; Yahoo may restrict individual symbols further. Rate limits or empty history are expected failure modes.

Only verified USD equities and recognized listed venues enter simulation. Each included listed session must contain every five-minute regular-session bar with valid positive OHLCV, including the closing bar. Missing/zero-volume sessions are rejected. This intentionally conservative selection introduces material liquidity/selection bias. NYSE calendar hours/holidays/early closes are used for the listed-US pilot only. Current partial days are excluded. Yahoo start timestamps are shifted five minutes to bar end. Any split/dividend event returned in the window rejects the whole listed symbol; missing event reporting and ticker-change risks remain. This automatic check is NOT a full corporate-action review. The existing CSV-manifest manual-review safeguard is unchanged. The pilot runs the engine directly and marks automated checks and manual-review status separately.

Default configuration remains USD 2,000 equity, USD 250/300 allocation ceiling, USD 20 planned risk, no leverage, hypothetical costs and immediate reuse of realized cash. Actual loss can exceed USD 20. Four strategies compete in one shared portfolio; ranking is attribution within that portfolio, NOT four independent trials or proof of profitability. No historical news is used. Price eligibility is checked by the existing engine at entry. Today's scanner price filter can miss historically eligible securities.

## Local run

```bash
python -m pip install -e '.[dev]' 'yfinance>=0.2.65,<1' 'pandas-market-calendars>=4,<6'
python -m pytest -q
python -m penny_lab.yahoo_pilot --days 30 --limit 25 --allocation 300
```

For explicit symbols add --symbols with a comma-separated list. Results default to results/yahoo-pilot. This integration has not been exercised against Yahoo from the assistant environment. The workflow executes offline tests before the network pilot. Inspect failures and coverage rather than trusting job success as strategy validation. Yahoo data use remains subject to provider terms; this is personal research, not redistribution or broker order execution.
