# Refactoring Plan: Modularization & Code Cleanup

## Overview
This document outlines suggested refactoring work to reduce redundancy, improve code clarity, and make the codebase more maintainable.

## Current Issues Identified

### 1. Code Duplication
- **`get_api_key()`** duplicated in 3 files: `main.py`, `bet_watcher.py`, `nba_price_alert.py`
- **`compute_regions_for_books()`** duplicated in 2 files: `main.py`, `bet_watcher.py`
- **`fetch_odds()`** / `fetch_odds_for_sport()` duplicated in 3 files with slight variations
- Similar logic for extracting team prices, formatting odds, etc.

### 2. Monolithic File Structure
- **`main.py`** is 2036 lines containing:
  - Pydantic models (23-162)
  - Utility functions (odds conversion, vig adjustment, etc.)
  - Dummy data generation (very long functions, 214-808)
  - Business logic (value plays, arbitrage detection)
  - API endpoints (FastAPI routes)
  - All mixed together with no clear separation

### 3. Mixed Concerns
- Models, utilities, business logic, and API routes all in one file
- Makes testing difficult
- Hard to navigate and maintain

### 4. Potentially Unused Code
- `hedge_ev_percent` is marked as "legacy" in comments but still calculated and returned
- Some duplicate logic that could be consolidated

## Proposed Refactoring Structure

```
odds-price-alert/
├── main.py                    # FastAPI app initialization only (~50 lines)
├── config.py                  # Configuration constants
├── models/
│   ├── __init__.py
│   ├── requests.py            # Request models (BetRequest, ValuePlaysRequest, etc.)
│   └── responses.py           # Response models (OddsResponse, ValuePlaysResponse, etc.)
├── services/
│   ├── __init__.py
│   ├── odds_api.py            # API client wrapper (fetch_odds, get_api_key, etc.)
│   ├── odds_utils.py          # Odds conversion utilities (american_to_decimal, etc.)
│   ├── value_plays.py         # Value plays business logic
│   ├── arbitrage.py           # Arbitrage detection logic
│   └── dummy_data.py          # Dummy data generation
├── routes/
│   ├── __init__.py
│   ├── odds.py                # /api/odds endpoint
│   ├── value_plays.py         # /api/value-plays, /api/best-value-plays
│   ├── player_props.py        # /api/player-props
│   └── sms.py                 # /api/send-sms, /api/test-arbitrage-alert
├── utils/
│   ├── __init__.py
│   ├── regions.py             # Region computation logic
│   ├── formatting.py          # Time formatting, book labels, etc.
│   └── validation.py          # Input validation helpers
└── scripts/                   # Standalone scripts (can import from shared modules)
    ├── bet_watcher.py
    └── nba_price_alert.py
```

## Detailed Refactoring Steps

### Phase 1: Extract Shared Utilities (High Priority)

#### 1.1 Create `utils/regions.py`
```python
# Consolidate compute_regions_for_books() from main.py and bet_watcher.py
```

#### 1.2 Create `services/odds_api.py`
```python
# Consolidate:
# - get_api_key() from all 3 files
# - fetch_odds() / fetch_odds_for_sport() from all files
# - BASE_URL constant
```

#### 1.3 Create `utils/formatting.py`
```python
# Extract:
# - pretty_book_label()
# - format_start_time_est()
# - BOOK_LABELS constant
```

#### 1.4 Create `services/odds_utils.py`
```python
# Extract odds conversion utilities:
# - american_to_decimal()
# - decimal_to_american()
# - american_to_prob()
# - estimate_ev_percent()
# - apply_vig_adjustment()
# - points_match()
# - is_price_or_better() (from bet_watcher.py)
```

### Phase 2: Extract Models (Medium Priority)

#### 2.1 Create `models/requests.py`
```python
# Extract all request models:
# - BetRequest
# - OddsRequest
# - ValuePlaysRequest
# - BestValuePlaysRequest
# - PlayerPropsRequest
# - SMSAlertRequest
```

#### 2.2 Create `models/responses.py`
```python
# Extract all response models:
# - PriceOut
# - SingleBetOdds
# - OddsResponse
# - ValuePlayOutcome
# - ValuePlaysResponse
# - BestValuePlayOutcome
# - BestValuePlaysResponse
```

### Phase 3: Extract Business Logic (Medium Priority)

#### 3.1 Create `services/value_plays.py`
```python
# Extract:
# - collect_value_plays()
# - find_best_comparison_outcome()
# - choose_three_leg_parlay()
```

#### 3.2 Create `services/arbitrage.py`
```python
# Extract arbitrage-specific logic:
# - Arbitrage detection calculations
# - Hedge margin calculations
```

#### 3.3 Create `services/dummy_data.py`
```python
# Extract:
# - generate_dummy_odds_data() (very long function, 214-668)
# - generate_dummy_player_props_data() (671-807)
```

### Phase 4: Extract API Routes (Low Priority - Can be done incrementally)

#### 4.1 Create `routes/odds.py`
```python
# Extract /api/odds endpoint
```

#### 4.2 Create `routes/value_plays.py`
```python
# Extract:
# - /api/value-plays
# - /api/best-value-plays
```

#### 4.3 Create `routes/player_props.py`
```python
# Extract /api/player-props endpoint
```

#### 4.4 Create `routes/sms.py`
```python
# Extract:
# - /api/send-sms
# - /api/test-arbitrage-alert
# - /api/check-active-odds
# - /api/credits
```

### Phase 5: Update Standalone Scripts (Medium Priority)

#### 5.1 Update `bet_watcher.py`
- Import shared utilities from `services/odds_api.py` and `utils/regions.py`
- Remove duplicate functions
- Keep script-specific logic (CLI, interactive prompts)

#### 5.2 Update `nba_price_alert.py`
- Import shared utilities
- Remove duplicate functions
- Keep script-specific logic

### Phase 6: Cleanup & Remove Unused Code (Low Priority)

#### 6.1 Review `hedge_ev_percent`
- Currently marked as "legacy" but still calculated
- Decision needed: Remove entirely or keep for backward compatibility
- If keeping, update comments to clarify purpose

#### 6.2 Remove Unused Imports
- Check all files for unused imports after refactoring

#### 6.3 Consolidate Constants
- Move all constants to `config.py`:
  - `BASE_URL`
  - `MAX_VALID_AMERICAN_ODDS`
  - `BOOK_LABELS`
  - `POLL_INTERVAL_SECONDS` (if used in main app)

## Benefits of This Refactoring

1. **Reduced Duplication**: Shared utilities eliminate code duplication
2. **Better Testability**: Isolated modules are easier to unit test
3. **Improved Maintainability**: Clear separation of concerns
4. **Easier Navigation**: Smaller, focused files
5. **Reusability**: Scripts can import shared utilities
6. **Scalability**: Easier to add new features without bloating main.py

## Migration Strategy

1. **Start with Phase 1** (shared utilities) - lowest risk, highest impact
2. **Update scripts** to use shared utilities (Phase 5) - validates the approach
3. **Extract models** (Phase 2) - straightforward, low risk
4. **Extract business logic** (Phase 3) - requires careful testing
5. **Extract routes** (Phase 4) - can be done incrementally, one route at a time
6. **Cleanup** (Phase 6) - final polish

## Testing Strategy

- After each phase, run existing tests/scripts to ensure nothing breaks
- Test with both real API calls and dummy data mode
- Verify all endpoints still work
- Test standalone scripts still function

## Estimated Impact

- **main.py**: Reduce from 2036 lines to ~50-100 lines (app initialization only)
- **Code duplication**: Eliminate ~200-300 lines of duplicate code
- **File count**: Increase from 4 Python files to ~15-20 files (but much smaller, focused files)
- **Maintainability**: Significantly improved

## Notes

- This refactoring maintains backward compatibility - all existing functionality remains
- Can be done incrementally, one phase at a time
- No changes to frontend or API contracts needed
- Consider using type hints consistently throughout



