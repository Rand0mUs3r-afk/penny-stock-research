# Initial strategy hypotheses

These rules are initial software definitions, not findings about profitable market behavior. All use only completed same-session five-minute bars. No news influences historical signals. Twelve-bar baseline by default; startup needs lookback + 3 observations. A missing interval clears the signal warmup.

Common gate: raw signal close below USD 10, positive volume, prior baseline mean close-times-volume at least the configured threshold. The cutoff is an experiment assumption. Relative volume compares the signal bar to the earlier baseline, not to a full future trading day.

| Rule | Entry signal | Stop reference |
|---|---|---|
| Breakout/retest | Prior bar closes above the earlier-window highest high on at least 1.5x baseline volume; current low retests within 0.3% and closes above both resistance and its open | Retest low less a 0.1% buffer |
| Uptrend pullback | Later half of baseline has higher maximum high and minimum low than earlier half; prior bar pulls back without breaking later-half support; current closes above pullback high and its own open on at least 1x volume | Lower of pullback/recovery lows less 0.1% |
| Support bounce | At least two baseline lows within 0.3% of minimum support, separated by at least two bars; current retests and closes above previous close and own open on at least 1x volume | Lower of support/current low less 0.1% |
| VWAP reclaim | Prior close at/below its session VWAP; current closes above updated session VWAP and own open on at least 1.5x volume | Lower of prior/current low less 0.1% |

VWAP is a typical-price times bar-volume approximation, not exact trade-level VWAP. Buy next contiguous bar open plus modeled spread/slippage. Price limit is checked again at execution; gaps below the stop invalidate entry. Default target is entry plus 2 times raw entry-to-stop distance, before exit costs.

Initial simultaneous-entry score is capped relative volume plus capped fractional stop distance. It is a transparent deterministic scheduling heuristic, NOT a learned probability or validated quality ranking. Strategy name breaks equal-score overlap; symbol breaks equal-score cross-stock priority. All such choices need sensitivity testing. At most one position per symbol, no pyramiding. Re-entry after exit may be signaled on that completed bar but cannot execute until the following bar.
