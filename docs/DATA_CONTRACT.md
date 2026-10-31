# Input data contract

## Bars

UTF-8 CSV headers: `timestamp,symbol,open,high,low,close,volume` (column order is not important).

- Timezone-aware ISO timestamps at the **END** of completed five-minute bars, aligned on five-minute boundaries. Alpaca bar starts are converted by the adapter.
- Unadjusted/raw positive OHLC; finite nonnegative volume; no duplicate symbol/time pairs. The engine rejects zero-volume regular-session bars to avoid fictitious fills.
- Raw prices enforce historical entry eligibility below USD 10. Already split-adjusted past prices must not be used to construct a misleading cheap-stock universe.
- Explicit U.S. listed-exchange provenance per symbol. OTC and unknown exchange labels are not accepted by this initial importer.
- Supply full session-close coverage for every symbol/day included, using an authoritative exchange calendar including holidays and early closes. Incomplete closure fails rather than pricing an invented liquidation.
- Investigate corporate actions, stale data, changed tickers, delistings, missing bars and halts. Initial engine has no automatic split accounting: partition/exclude affected sessions and document exclusions.

## Provenance manifest

JSON fields required:

| Field | Meaning |
|---|---|
| source | Named source, never a generated market dataset |
| feed | Explicit feed; no silent feed substitution |
| universe | `listed_under_10`; `otc` currently unsupported |
| price_adjustment | Must be `raw` |
| timeframe_minutes | Must be 5 |
| timestamp_convention | Must be `bar_end` |
| symbols | Object mapping each symbol to NASDAQ, NYSE, AMEX, ARCA, BATS, NYSEARCA or NYSEAMERICAN |
| session_closes | Object mapping each included New York session date to its official close, e.g. `16:00` or early close `13:00` |
| corporate_actions_reviewed | Boolean true only AFTER actual review, not a switch to bypass checks |
| survivorship_warning | Explain historical universe gaps, exclusions and selection method |

`fetch` writes an incomplete manifest on purpose. There is no automatic approval. A symbol selected today and historical bars do not establish that symbol's historical listing/trading eligibility. News and fundamental features require publication/first-observed timestamps if added later; current context is not historical input.
