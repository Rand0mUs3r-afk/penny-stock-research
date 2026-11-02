# Legacy stochastic experiments

The active experiment/uptrend-vwap-only workflow now runs the monthly diversified trend model documented in MONTHLY_TREND.md. It no longer executes the scalper or 45-day stochastic adaptation.

The earlier modules remain unchanged for reproducibility: penny_lab.stochastic_scalper is the one-minute strategy with quick exits; penny_lab.extended_holding is the overnight variant with a configurable maximum of 45 calendar days. Their source references and settings remain in code. Main and the separate research branch are untouched.
