# Under-25 research with Alpaca secondary

Run Actions > Yahoo coverage and backtest pilot > Run workflow on main. Default recent run: days 30, limit 25, allocation 300, feed sip, blank start_date. Scanner and historical modeled entry both use a strict price ceiling below USD 25. For an actual request since 2023, set start_date to 2023-01-01. This overrides days and routes five-minute history to Alpaca after recording Yahoo's retention limit. Long runs cap discovery at five candidates per screen and ten total explicit symbols to bound runner memory and time. They can still time out or fail access checks.

The workflow reads existing ALPACA_API_KEY and ALPACA_SECRET_KEY repository secrets only in the data step. Their presence/access has not been verified by the assistant. Missing keys are reported without printing values. No secrets are sent to Yahoo. Existing read-only Alpaca code provides raw five-minute bars with pagination and explicit sip/iex selection. No order submission. No silent feed fallback.

Recent windows use Yahoo first, then Alpaca if fetching or complete-session validation fails. Long windows skip the unavailable Yahoo intraday request and try Alpaca. Each symbol uses one provider for its full requested window; there is no candle-level patching. Different symbols may use different feeds/providers, which limits volume-signal comparability and is disclosed in provider_by_symbol. Yahoo remains necessary for symbol metadata and daily corporate-action checks; metadata/action failures reject the symbol before provider selection. This is a price-data fallback, not fully independent Yahoo-outage recovery. Any returned split/dividend in the window rejects the entire symbol for manual review. Long windows may therefore exclude many stocks; this material bias is intentional and reported, not silently adjusted away.

Only complete, positive-volume regular sessions enter simulation; partial sessions and missing bars are rejected. A symbol can pass with some complete sessions while others are rejected. sessions_used and sessions_rejected explicitly distinguish this from full historical coverage. IPOs, ticker changes, inactive names, and incomplete Yahoo action reporting remain unresolved research limitations. Yahoo current screens are not a 2023 universe. No point-in-time or full-history claim is made.

The existing engine universe string listed_under_10 is retained as a legacy internal compatibility label, NOT the effective threshold; this runner sets Config(max_price=25) and manifest historical_entry_ceiling=25. The old yahoo_pilot module/default config remain legacy under-10 tools. The Actions workflow now uses multi_pilot. OTC is still downloaded from Yahoo for recent coverage only, never relabeled or backtested. Long-range OTC needs a dedicated provider.

Final summary preserves equity, trade metrics and trade tables, adds actual provider/feed coverage, credential-presence status (not values), and entry-price-band attribution below 5, 5 to below 10, and 10 to below 25. All share the same USD 2,000 cash portfolio, USD 250/300 allocation ceiling and USD 20 planned-risk rule. News remains display-only. The prior news module's Yahoo-specific retention warning does not describe Alpaca entitlement; the appended provider coverage table is the actual outcome.

Local example:

```bash
python -m penny_lab.multi_pilot --start 2023-01-01 --limit 5 --feed sip --allocation 300
python -m penny_lab.report
python -m penny_lab.news_context --requested-start 2023-01-01
python -m penny_lab.multi_pilot --report-only
```

Dependencies are installed by the workflow. This integration and access to the configured credentials have not been live-verified from the assistant environment. Tests include price bands, ceiling configuration, primary selection, validation-triggered fallback, and explicit all-provider failure. They do not establish fill realism, coverage, or profitability.
