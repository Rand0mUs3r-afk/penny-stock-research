# Active experiment: monthly diversified trend allocation

On experiment/uptrend-vwap-only, Uptrend filter comparison now runs penny_lab.monthly_trend. Main and the research branch are untouched. Old scalper and overnight modules remain available by CLI but are no longer this workflow's active job.

Default universe SPY,EFA,IEF,VNQ,DBC represents US stocks, foreign stocks, government bonds, real estate and commodities. It replaces the USD 1-35 stock screen. Default evaluation starts 2010-01-01 with 400 earlier calendar days for warmup. Require the full common daily calendar and ten completed monthly observations for every requested ETF. Saved source OHLC/Adj Close files are fingerprinted. Failed assets are not silently dropped.

At completed exchange month-end, close > ten-month SMA enables that asset's equal-weight sleeve; otherwise its sleeve stays in zero-yield cash. Execute/rebalance at next session open. No leverage or indicator optimization.

Four independent USD 2,000 portfolios: trend (monthly long/cash, no fixed dollar stop/cap/45-day exit); buy_hold (equal weights once, no monthly rebalance); trend_45_capped (USD 300 cost-inclusive per-asset ceiling, USD 20 cost-inclusive planned-risk stop, maximum 45 calendar days); buy_hold_capped (USD 300 ceiling and idle cash, no trend/stop/expiry). The constrained variant exits gaps at actual open, cannot reenter on the deadline day and does not reset its oldest entry date when adding units. These are separately labeled adaptations, not identical paper rules.

Fractional normalized total-return-adjusted ETF units model dividend/split-adjusted returns; they are NOT historical broker share counts or quote-calibrated raw-price stop fills. Source monthly family: Meb Faber, A Quantitative Approach to Tactical Asset Allocation and follow-ups, https://mebfaber.com/2017/12/13/episode-86-quantitative-approach-tactical-asset-allocation/ .

All profiles use the same dates, capital and explicit costs. Default 50-bps spread/25-bps slippage is unchanged, with normal/doubled-cost runs. No separate order fee. Final open holdings include an exit-cost reserve. Gross P&L adds costs back to the SAME executed positions, not a zero-cost rerun. Full/earlier70/later30 accounts reset independently; optional boundary does not certify untouched data.

Summary/comparison show starting/final equity, gross P&L, costs, net P&L, return, drawdown and turnover. Per-case run JSON and CSVs contain orders, equity/exposure, open holdings and per-asset attribution. Realized plus unrealized P&L reconciles to net P&L. No fabricated final liquidation or missing-data returns.

Run Actions -> Uptrend filter comparison -> experiment/uptrend-vwap-only. Artifacts monthly-trend-RUNID. CLI python -m penny_lab.monthly_trend --symbols SPY,EFA,IEF,VNQ,DBC --start 2010-01-01. Optional --end, --boundary, --spread-bps, --slippage-bps. Fourteen targeted tests passed locally; full repository tests, hosted workflow and provider downloads have not been run by the assistant. No profitability result is asserted for this implementation.
