# Penny Stock Research

**Private, backtesting-only foundation. No live orders, no supplied market data, no profitability claims.**

A starting research engine for four long-only setups on exchange-listed stocks with raw entry prices below USD 10. True OTC/Pink Sheets research is a separate integration and currently fails closed. Under-$10 listed stocks are **not** described as OTC.

## Available now

- Validated TOML configuration: USD 2,000 starting equity, USD 250/300 configurable allocation ceiling, USD 20 planned risk per position.
- Whole-share sizing constrained by available cash, stop distance, modeled costs, previous-bar volume participation, and optional combined risk cap.
- Shared cash ledger across symbols; realized profits/losses affect later available capital. Fixed allocation does **not** automatically grow per position.
- Four deterministic initial hypotheses: breakout/retest, uptrend pullback, support bounce, session VWAP reclaim.
- Five-minute completed-bar signals and next-bar-open execution; conservative stop-first ambiguity, gap-through-stop losses and session-end exits.
- CSV input with provenance manifest; GET-only Alpaca assets/bars adapter with pagination, explicit feed and no silent fallback.
- Optional yfinance current-news adapter; historical signals cannot read that current news.
- Exploratory strategy ranking, trade/rejection ledgers, equity series and reproducible JSON run audit.
- Offline unit tests and manually runnable GitHub Actions checks. No keys needed for tests.

## Quick start

Python 3.11 or newer:

```bash
python -m pip install -e '.[dev]'
python -m penny_lab.cli status --config config/default.toml
python -m pytest -q
```

This works without API credentials. There is no demo backtest or invented performance dataset. Tiny invented inputs in `tests/` are explicitly software fixtures only.

## Later: connect data

Set `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` privately in environment variables or GitHub Actions secrets. Do not paste secrets into chats, source code, issue comments or commits. `.env.example` has blank fields; `.env` files are ignored and are **not** automatically loaded.

```bash
python -m penny_lab.cli assets --output data/assets.json
python -m penny_lab.cli fetch --symbols YOUR_SYMBOLS --start YOUR_ISO_START --end YOUR_ISO_END --feed sip
```

The asset adapter currently reads the **paper account** read-only asset endpoint. Feed access depends on your account; failures are explicit and never fall back from SIP to IEX. The current active/inactive catalog is not a historical security master. The fetch command deliberately writes a **blocked** manifest: review exchange provenance, corporate actions, session dates and early closes before backtesting. No full-universe discovery by historical price is claimed yet.

Once real data and its manifest are reviewed:

```bash
python -m penny_lab.cli backtest --bars data/bars.csv --manifest data/bars.manifest.json --config config/default.toml --output results/run
```

Outputs: `run.json`, `trades.csv`, `equity.csv`, `ranking.csv`, `rejections.csv`. Entry/exit reasons and times are recorded; **interactive trade charts/dashboard are not implemented yet**. Run each strategy separately via the config to compare independently; the default combines signals in one shared-cash portfolio.

Optional current news:

```bash
python -m pip install -e '.[news]'
python -m penny_lab.cli news --symbol YOUR_SYMBOL
```

Yahoo/yfinance usage is subject to provider terms. Current headlines and current fundamentals are never substituted for historically available features.

## Important limitations

- This is a **coarse bar-based exploratory engine**, not the planned one-minute/quote-accurate simulator. Hypothetical cost settings are uncalibrated assumptions, not measured spreads or slippage.
- Entry uses the next bar's raw open plus adverse costs. Stop/target collisions use stop-first; exit timestamps identify the bar end, not an exact intrabar execution time.
- A prior-bar participation cap is not evidence of real fillability. Partial fills, queue priority, historical quotes/depth and halts are not simulated yet.
- USD 20 is **planned**, not guaranteed realized loss. Gaps can exceed it. No leverage; optional aggregate planned-risk cap is disabled unless explicitly configured.
- Shared-cash sequential fills reserve cash/risk as each ranked candidate is considered. There are no persistent broker pending orders or brokerage integration.
- Missing next bars expire pending signals; gaps reset setup warmups. Missing session-close bars or zero-volume regular-session bars fail the run instead of fabricating executable liquidations.
- Realized proceeds are immediately reusable in this abstract ledger. Settlement, cash-account restrictions, margin/PDT rules and broker/account-specific eligibility are not modeled. Do not equate its turnover with what a live USD 2,000 account can execute.
- No walk-forward/holdout validation, point-in-time complete universe, automated corporate-action handling, robust optimizer or statistically validated rankings yet. Current results are labeled exploratory/in-sample.
- No live-trading mode, broker order methods, keys, purchased data or claimed profitable backtest is included.

See [data contract](docs/DATA_CONTRACT.md), [strategy rules](docs/STRATEGIES.md), [architecture](docs/ARCHITECTURE.md) and [roadmap](docs/ROADMAP.md).
