# Testing the Arbitrage Watcher Text Feature

This document explains how to easily test the arbitrage watcher text (SMS) feature.

## Quick Start

### Option 1: Web Interface (Easiest)

1. Start your server:
   ```bash
   python main.py
   # or
   uvicorn main:app --reload
   ```

2. Open your browser and navigate to:
   ```
   http://localhost:8000/test-arbitrage.html
   ```

3. The test page provides three ways to test:
   - **Test SMS Directly**: Enter a phone number and send a test SMS
   - **Get Mock Arbitrage Play**: See what a mock arbitrage opportunity looks like
   - **Test Full Alert Flow**: Simulate the complete watcher flow (detect arbitrage + send SMS)

### Option 2: Command Line Script

1. Make sure your server is running

2. Run the test script:
   ```bash
   # Test SMS directly
   python test_arbitrage_watcher.py --phone 5551234567
   
   # Test with custom message
   python test_arbitrage_watcher.py --phone 5551234567 --message "Your custom message here"
   
   # Just get a mock arbitrage play (no SMS)
   python test_arbitrage_watcher.py --phone 5551234567 --test-mock
   
   # Test the full flow (get mock play + send SMS)
   python test_arbitrage_watcher.py --phone 5551234567 --full-flow
   
   # Use a different server URL
   python test_arbitrage_watcher.py --phone 5551234567 --base-url http://localhost:8000
   ```

### Option 3: API Endpoints Directly

#### Get a Test Arbitrage Play
```bash
curl http://localhost:8000/api/test-arbitrage-alert
```

#### Send a Test SMS
```bash
curl -X POST http://localhost:8000/api/send-sms \
  -H "Content-Type: application/json" \
  -d '{"phone": "5551234567", "message": "Test message"}'
```

## What Gets Tested

The test tools simulate:

1. **Mock Arbitrage Opportunity**: Creates a fake arbitrage play with:
   - Positive arbitrage margin (2.5%)
   - Realistic odds (e.g., -105 vs +105)
   - Proper sport, matchup, and outcome data
   - All fields that the watcher expects

2. **SMS Alert Formatting**: Tests the exact message format that the watcher uses:
   ```
   Hedge Alert! NBA: Lakers -105 vs +105 (2.5% margin). Lakers @ Warriors
   ```

3. **Full Flow**: Simulates the complete watcher process:
   - Detect arbitrage opportunity
   - Format the alert message
   - Send SMS notification

## Requirements

- Server must be running (main.py)
- `TEXTBELT_API_KEY` environment variable must be set (for SMS to actually send)
- Phone number must be valid (10+ digits)

## Notes

- The test endpoint (`/api/test-arbitrage-alert`) always returns the same mock play for consistent testing
- SMS messages require a valid Textbelt API key
- The mock play has `arb_margin_percent = 2.5%` which triggers the watcher's alert logic
- The test play is marked as `is_arbitrage = True`

## Troubleshooting

**SMS not sending?**
- Check that `TEXTBELT_API_KEY` is set in your environment
- Verify the phone number format (10+ digits, no special characters needed)
- Check the server logs for error messages

**Test endpoint not working?**
- Make sure the server is running
- Check that you're using the correct port (default: 8000)
- Verify the endpoint is accessible: `http://localhost:8000/api/test-arbitrage-alert`

**Want to test with different data?**
- Modify the `get_test_arbitrage_alert()` function in `main.py`
- Or create your own test endpoint with custom data






