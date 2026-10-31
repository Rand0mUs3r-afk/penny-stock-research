# Foundation validation

Validated in the build workspace using Python 3.12.8:

- `python -m pip install -e '.[dev]'`: succeeded.
- `python -m pytest -q`: **42 passed**.
- `python -m compileall -q src`: succeeded.
- `python -m penny_lab.cli status --config config/default.toml`: succeeded without API keys.

Checks cover configuration rejection, cash/allocation/risk sizing, all four rule triggers, shared cash and aggregate-risk cap, next-bar entry timing, conservative stop-first exits, gaps exceeding planned risk, missing intervals/session closes, zero-volume failure, OTC failure, missing credentials and provider pagination.

Tests use tiny explicitly invented SOFTWARE FIXTURES only. No fixture output is a market backtest or evidence of returns. No real market-data backtest, API credential connection, hosted CI completion, true OTC integration or profitable strategy has been verified. The Alpaca network adapter and optional Yahoo news adapter await credential/provider-access testing.

GitHub Actions is configured to repeat offline tests on Python 3.11 and 3.12, but hosted completion is separate from the local verification above.
