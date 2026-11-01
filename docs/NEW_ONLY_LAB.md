# Active price-action-only lab

This supersedes the EMA/Bollinger/RSI/double-bottom selection. Active cases: engulfing_low, three_candle, stair_step, reversal_mix (first two) and price_action_mix (all three). Each mixture shares one account; the three standalone cases use independent accounts. Old strategies remain registered for legacy experiments but are not selected here. active-setups.json records the current cases; its removed_from_active_lab list is historical, not exhaustive.

Entry rules use only completed raw OHLC candles. No EMA, RSI, Bollinger or volume-confirmation entry conditions. The inherited scanner still applies dollar-liquidity eligibility and volume-based ranking; price-action-only describes setup detection, not removal of execution/data safeguards. At least 13 session candles are required and no signal is emitted after 15:00 Eastern.

1. Engulfing at low: prior candle bearish, current bullish real body opens at/below prior close and closes above prior open, and the lower of their lows is at/below the preceding 12-candle low. Stop 0.1% below the lower low.
2. Three-candle reversal: first candle bearish; middle candle makes a lower low and its body is <=50% of its range; bullish final candle closes above the first candle high. Stop 0.1% below the three-candle low.
3. Stair-step continuation: three preceding candles have successively higher highs, lows and closes; bullish fourth candle holds a higher low and closes above the preceding high. Stop 0.1% below the four-candle low.

Targets remain known overhead historical highs, not fixed-RR or invented measured moves. Signals without a valid overhead target are rejected. No minimum RR. Same-day exits, USD 2,000 per case, USD 250/300 allocation ceiling, USD 20 planned risk, USD 1-35 price eligibility, October 1-31 default evaluation (November 1 exclusive) and original provider/reference safeguards remain. Normal/doubled spread and slippage give ten portfolio scenarios. No indicator/uptrend backtest precedes these; acquisition remains metadata-only. No live orders.

The three setups are unvalidated experimental hypotheses, not demonstrated improvements. Repeated October inspection makes October development data. Current-universe bias, complete-session eligibility, historical quote/cost limitations and OTC limitations remain. No automated profitable-winner claim. Synthetic regression tests are included, but full repository tests, hosted workflow execution and provider results have not been verified by the assistant.
