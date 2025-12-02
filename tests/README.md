# Tests and CLI Helpers

This folder collects the ad-hoc testing utilities and documentation so they stay separate from the main application code.

- `test_odds_api.py` – CLI helper for pulling odds directly from The Odds API.
- `test_arbitrage_watcher.py` – CLI helper for exercising the arbitrage watcher SMS flow.
- `TEST_ARBITRAGE_WATCHER.md` – Guide for testing the arbitrage watcher via the web UI, CLI, or direct API calls.

Run any of the scripts from the repository root, for example:

```bash
python tests/test_odds_api.py --sport basketball_nba --markets totals --limit 3
```
