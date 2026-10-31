# Penny-stock and OTC discovery plan

Status: REQUIREMENTS / DESIGN ONLY. This document does not implement a scanner, Yahoo historical-data adapter, OTC backtesting, or a data workflow. The existing engine's OTC restriction must remain in place until its data contract and validation are extended and tested.

## Confirmed intent

- User has an Alpaca paper account. All work remains backtesting-only; no paper or live order submissions.
- Discover candidates automatically rather than requiring a manually supplied ticker universe.
- Prioritize OTC/Pink Sheets candidates and penny stocks, keeping exchange-listed stocks under USD 10 as a separate cohort.
- Try usable historical data from Alpaca or Yahoo Finance via yfinance. A candidate need not be tradable through Alpaca to be researched, but results must never imply brokerage eligibility.
- Keep the existing four setup hypotheses and USD 2,000 initial equity, configurable USD 250/300 allocation ceiling, and USD 20 planned loss budget per position. Planned risk is not a guaranteed realized-loss cap.
- Realized gains/losses affect available cash. Allocation ceilings remain fixed unless the user separately selects proportional allocation growth.

## Proposed discovery sources

1. Yahoo Finance screener through yfinance EquityQuery/screen, with pagination, retries, caching, and bounded requests. Check supported exchange/region/price filters at runtime. Record requested filters, total reported results, retrieved counts and truncation; do not claim the screen is a complete OTC directory.
2. User-supplied ticker files or permissioned symbol-directory exports, with source and collection time.
3. Optional licensed/permitted news feeds or Google News links as candidate hints, not a security master or price feed. Resolve ambiguous company names and confirm symbol/exchange identity before accepting them. No search scraping or automatic ticker extraction has been implemented.
4. TradingView integration is disabled by default. Do not scrape its screener or assume CSV export grants automated/non-display usage rights. Enable only an appropriately permissioned integration after a terms review.

Deduplicate using provider symbol mappings and record source URL/provider, discovered_at UTC, company identity, currency, exchange evidence and available ticker metadata. Never identify Pink Sheets status from price alone or treat every OTC venue/tier as Pink. Use labels such as verified Pink, other verified OTC, OTC tier unverified, listed under USD 10, and unresolved. Unknown venue/tier is not a verified OTC result. Current exchange metadata does not prove historical venue membership.

## Proposed data routing

- Listed candidates: try an explicitly selected Alpaca feed when credentials/access permit; an enabled Yahoo history adapter may be tried separately on failure or insufficient coverage.
- OTC candidates: ordinary retail Alpaca access is not assumed to cover OTC. Try Yahoo where available; Alpaca OTC requires independently verified entitlement and an explicitly supported adapter.
- Provider switches must be explicit and recorded per symbol/run. Never splice Alpaca and Yahoo bars silently or fabricate missing intervals.
- Treat every requested symbol and interval as a coverage probe. A ticker appearing in a screener does not demonstrate that suitable historical intraday data exists.
- Record requested and actual date range, interval, feed/provider, timezone, adjustment policy, missing bars, zero-volume bars, actions and exclusions.
- Keep data/results out of Git. Avoid logging credentials and comply with provider access/use terms.

## Strategy compatibility and validation

The initial engine expects five-minute intraday bars. All four existing setups must be tested at their declared interval; session VWAP reclaim cannot be reconstructed from daily OHLCV. Daily-only availability must be labeled unsupported for these runs, not silently converted to an intraday test or given an invented ranking.

Yahoo's download documentation describes limited recent intraday history (generally within the latest 60 days; restrictions vary by interval and availability). Probe actual coverage and use a shorter explicit sample where necessary; do not promise a twelve-month Yahoo five-minute OTC backtest. Longer-history daily/swing research would be a separate strategy specification, not the current intraday engine.

Require chronological unique bars, valid OHLCV, provider timestamps converted correctly to completed-bar times, currency/identity validation, explicit sessions and early closes, and corporate-action review. Preserve raw-price semantics for the historical under-USD-10 filter; setting auto_adjust=False alone does not establish fully unadjusted historical prices. The existing blocked-manifest review remains mandatory. Sparse OTC histories may fail current execution assumptions; do not forward-fill bars or pretend zero-volume bars were executable.

A rejected symbol must carry a reason such as unknown venue, unsupported interval, insufficient history, missing sessions, unresolved corporate action or provider access failure. No data means no backtest for that symbol. Report attempted/usable/skipped counts separately for each cohort and show an explicit no-coverage outcome if no OTC symbols qualify.

## Historical selection and news safeguards

- Today's scanner/news candidates backtested over earlier dates form a current-universe retrospective sample, with selection and survivorship bias. Label it exploratory; it is not a point-in-time universe or proof of historical strategy profitability.
- Archive discovery snapshots for forward research. Snapshot timestamps indicate first observed availability, not a historical discovery time.
- Keep current news descriptive only. Historical news-dependent entry/ranking requires a historical publication/availability record and must never use headlines first observed after the simulated decision.
- Track skipped/unavailable/delisted candidates instead of presenting only successfully downloaded winners.
- Final strategy evaluation needs later chronological validation/holdout and realistic execution-cost work, not just the coverage screen.

## Proposed delivery sequence

1. Scanner and candidate schema with offline tests, provider identity checks and discovery timestamps.
2. Optional Yahoo historical adapter and auditable coverage report; explicit Alpaca/Yahoo routing.
3. Validated OTC data-contract support. Keep OTC runs disabled until complete.
4. Manually triggered credential-aware data/backtest workflow; existing CI tests do not download market data.
5. Separate listed/OTC exploratory results, rejection logs and later trade charts/holdout evaluation.

No API connection, end-to-end Yahoo scan, OTC coverage, complete market universe, real backtest or profitable outcome is asserted by this plan. No passwords or API keys should be sent in chat. Add Alpaca credentials privately to the selected runtime or repository secrets when a credential-aware workflow is ready.

## Provider documentation

- [yfinance screener implementation](https://github.com/ranaroussi/yfinance/blob/main/yfinance/screener/query.py)
- [yfinance download intervals and adjustments](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
- [Alpaca market-data FAQ and OTC entitlement](https://docs.alpaca.markets/us/docs/market-data-faq)
- [TradingView usage restrictions](https://www.tradingview.com/policies/)
