# Security

Never commit API keys, `.env` files, account details, private datasets or results. Put credentials directly in repository/environment secrets or your private runtime environment. Keep the repository private. Private visibility is not a substitute for protecting credentials.

This project implements no order submission, live execution toggle, webhook or unauthenticated dashboard. Alpaca methods are GET-only and read data/assets. Do not add a brokerage order client without a separate safety/security review.

CI tests require no secrets and make no network requests. yfinance news is optional and must follow Yahoo usage terms; no automated redistribution is included.

If a credential is exposed, revoke/rotate it immediately. Removing it from the latest source revision does not remove it from Git history or logs.
