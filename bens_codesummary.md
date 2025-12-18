# Codebase structure and file purposes

## Root documentation and configuration
- `AGENTS.md`: contributor guidance outlining the FastAPI/static frontend setup and coding style preferences.  
- `README.md`: primary project overview, feature list, setup steps, and API usage notes.  
- `FLOW_CHART.md`: mermaid visualization of the main request/response flows.  
- `REFACTORING_PLAN.md`: roadmap for further modularization and duplication cleanup.  
- `REFACTORING_SUMMARY.md`: record of refactoring already completed.  
- `player_props_future_changes_research.md`: ideas for improving player-prop support and UX.  
- `HOSTING_OPTIONS.md`: hosting comparisons and deployment instructions.  
- `MOBILE_TESTING_GUIDE.md`: steps for exercising the mobile UI via emulator or device.  
- `SMS_ALERTS_RESEARCH.md`: survey of SMS providers and integration tips.  
- `requirements.txt`: pinned Python dependencies for the backend.  
- `Dockerfile`: builds the combined FastAPI + static frontend container on port 8000.  
- `.gitignore`: ignores common Python, node, OS, and log artifacts.  

## Core backend
- `main.py`: FastAPI app with request/response models, dummy odds generators, value and arbitrage computations, player-prop handling, featured games, SMS endpoint, line tracker snapshot API, test arbitrage alert, and static asset mounting.  
- `bet_watcher.py`: interactive CLI watcher that polls moneylines, prints snapshots, and alerts when target odds are reached.  
- `line_tracker.py`: CLI tracker that polls a selected matchup, logs moneyline/spread/total movement, and prints snapshots.  
- `data/sports_schema.json`: cached sports metadata used for validation and UI options.  

## Services layer
- `services/__init__.py`: package marker exporting domain models.  
- `services/odds_api.py`: Odds API client with logging, credit tracking, dummy-data hooks, rate-limit handling, and player-prop/event retrieval.  
- `services/odds_utils.py`: odds conversion helpers, EV estimation, vig adjustment, and point matching utilities.  
- `services/value_play_service.py`: orchestrates odds fetching and value-play/best-value aggregation and sorting.  
- `services/odds_service.py`: groups watcher bets by sport, fetches odds, and surfaces best prices per bookmaker.  
- `services/odds_cache.py`: lightweight in-memory cache decorator for odds and player-prop calls.  
- `services/player_props_config.py`: player-prop market definitions, aliases, supported sports, and expansion helpers.  
- `services/domain/models.py`: dataclasses representing odds queries/results and value/best-value plays.  
- `services/domain/mappers.py`: conversions between transport DTOs and domain dataclasses.  
- `services/domain/__init__.py`: exports domain models for convenient imports.  
- `services/repositories/odds_repository.py`: repository that resolves regions, coordinates live vs. dummy fetchers, caches payloads, and normalizes requested markets.  
- `services/repositories/__init__.py`: package marker for repository modules.  

## Utilities
- `utils/formatting.py`: bookmaker label helper and EST time formatting.  
- `utils/logging_control.py`: trace-level handling, file logging setup, and safe log truncation.  
- `utils/regions.py`: maps bookmaker selections to Odds API region strings.  
- `utils/__init__.py`: package marker for utility modules.  

## Deployment and helper scripts
- `deploy_on_ec2.sh`: rebuilds Docker image on EC2, removes old containers/images, and restarts the app.  
- `ssm_startup.sh`: SSM helper to rebuild and redeploy the Docker image as the `ubuntu` user.  
- `rebuild_and_run.ps1`: PowerShell script to create/refresh a venv, clear caches, set trace level, optionally enable dummy data, and start uvicorn.  
- `restart_server.ps1`: PowerShell helper to stop existing processes, clear caches, activate the venv, and relaunch uvicorn with a browser open.  
- `update_and_restart.ps1`: PowerShell workflow for updating dependencies and restarting the server.  
- `start_server.bat`: Windows batch file to activate a local venv (when present) and start uvicorn with reload.  

## Frontend (static assets)
- `frontend/BensSportsBookApp.html`: desktop arbitrage finder homepage and navigation hub.  
- `frontend/ArbritrageBetFinder-mobile.html`: mobile-first arbitrage finder landing page.  
- `frontend/mobile/BestValueBetMobile.html`: mobile view for best-value searches.  
- `frontend/mobile/Bens-Direct-FliffBet.html`: mobile-only page enforcing redirect when not on mobile, tailored to Fliff betting flow.  
- `frontend/value.html`: value plays UI comparing target vs. comparison books.  
- `frontend/watcher.html`: web-based bet watcher interface with controls for polling odds and testing alerts.  
- `frontend/linetracker.html`: line movement tracker UI for monitoring specific matchups.  
- `frontend/settings.html`: desktop settings/preferences page.  
- `frontend/mobile/settings-mobile.html`: mobile settings/preferences page.  
- `frontend/sgp-builder.html`: same-game parlay builder interface.  
- `frontend/test-arbitrage.html`: page for exercising the arbitrage watcher text/SMS flow.  
- `frontend/widgets.html`: collection of odds widgets and UI components.  
- `frontend/table-renderers.js`: shared client-side helpers for formatting odds tables, hedging stakes, and rendering play rows.  
- `frontend/nav-trim.js`: mobile detection/redirect logic and toolbar trimming for disallowed pages.  
- `frontend/favicon.svg`: site icon used across pages.  

## Tests and CLI helpers
- `tests/README.md`: overview of test/CLI utilities.  
- `tests/conftest.py`: ensures repository root is on the import path for tests.  
- `tests/test_logging_control.py`: validates logging utility behaviors and trace-level parsing.  
- `tests/test_human_readable_logs.py`: checks human-readable odds summaries from `services.odds_api`.  
- `tests/test_nav_trim.js`: Node-based test validating mobile nav enforcement and path normalization.  
- `tests/test_player_props_throttling.py`: exercises player-prop fetch rate limiting and fallback logic.  
- `tests/test_player_props_api.py`: API-level tests for player-prop endpoints, filtering, and warnings.  
- `tests/test_featured_games.py`: ensures featured games endpoint sorts correctly and honors dummy data.  
- `tests/test_best_value_service.py`: covers best-value aggregation across expanded player-prop markets.  
- `tests/test_value_plays.py`: validates value-play collection rules for moneylines and hedging.  
- `tests/test_odds_cache.py`: verifies caching decorator behavior and dummy-data bypass.  
- `tests/test_odds_repository.py`: confirms repository excludes player filters for team markets and passes correct arguments.  
- `tests/test_arbitrage_watcher.py`: CLI helper (skipped in pytest) for testing SMS flow and mock arbitrage retrieval.  
- `tests/TEST_ARBITRAGE_WATCHER.md`: guide for exercising the arbitrage watcher via web UI, CLI, or API.  
- `tests/test_odds_api.py`: CLI script for pulling odds directly from The Odds API for debugging.  
