# Two-strategy branch experiment

Branch experiment/uptrend-vwap-only starts from main commit b20697d6b2ebd9612193c3bb945ffe66dfcdba11. Main is not modified.

Run Actions > Yahoo coverage and backtest pilot > Run workflow, selecting experiment/uptrend-vwap-only in the branch dropdown. The workflow invokes penny_lab.two_strategy_pilot, a scoped configuration-factory adapter around the unchanged multi_pilot runner. It selects exactly uptrend_pullback and vwap_reclaim; support_bounce and breakout_retest cannot be selected by that run's configured scanner. The original strategy implementations, default config, legacy CLI and four-strategy tests remain intact. Running the legacy multi_pilot command directly still uses four strategies; use the experiment entry point for this branch's intended test.

All other experiment settings and pipeline behavior are inherited unchanged: USD 2,000 starting equity, USD 250/300 allocation ceiling, USD 20 planned-risk limit, price below USD 25 at discovery and modeled entry, Yahoo discovery/recent history with Alpaca secondary, optional start_date, explicit feed, current news display-only, shared capital, costs, five-minute bars, stops/targets, session exits, coverage checks and result exports. OTC stays coverage-only. Historical-start access and complete coverage are not guaranteed.

Local command (after installing the same dependencies):

```bash
python -m penny_lab.two_strategy_pilot --days 30 --limit 25 --allocation 300 --feed sip
```

For the same historical request add --start 2023-01-01. The same long-range candidate caps and corporate-action rejection rules apply. run.json config.strategies and strategy_ranking should contain only the two selected names.

For a fair comparison, use the same exact symbols, date range, feed and data snapshots as the baseline. A fresh automatic scan can choose different stocks, and the recent window moves with time. Removing strategies also frees capital and changes overlapping-signal selection: do not assume the new result equals simply deleting old trades. This is an exploratory experiment selected after inspecting the previous results, not an untouched out-of-sample validation. New tests verify only strategy selection changes and the scoped adapter restores its factory. Hosted tests and market-data results must be checked on the next workflow run.
