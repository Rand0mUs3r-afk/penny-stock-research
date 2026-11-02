# Monthly trend research: shared workflow update

The active experiment/uptrend-vwap-only workflow now runs one continuous USD 2,000 account shared by monthly trend, buy-and-hold and all five ETFs. See SHARED_PORTFOLIO.md for allocation rules, trade entry/exit dates and exact holding-day reports. It no longer runs independent case/cost/period accounts automatically.

The original penny_lab.monthly_trend module remains unchanged for manual reproduction of the earlier comparisons. Its monthly 10-month moving-average rule, SPY/EFA/IEF/VNQ/DBC universe, fractional provider-adjusted daily research-price units, USD 250/300 allocation ceiling and original spread/slippage assumptions are retained in the new shared account. The new ceiling applies to both strategies combined per ticker. No 45-day variant is active. The old USD 1-35 stock filter and intraday USD 20 stop-risk rule are not used by this monthly model. No exact historical whole-share or broker execution is claimed.

Source: https://mebfaber.com/2017/12/13/episode-86-quantitative-approach-tactical-asset-allocation/. These ETF-proxy/account-constrained implementations are adaptations, not reproductions of the paper's index results. Source data availability and performance must be checked in actual runs. Main and the separate research branch are untouched.
