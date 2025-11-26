#!/usr/bin/env python3
"""
Simple command-line test script for the arbitrage watcher text feature.

Usage:
    python test_arbitrage_watcher.py --phone 5551234567
    python test_arbitrage_watcher.py --phone 5551234567 --test-mock
    python test_arbitrage_watcher.py --phone 5551234567 --full-flow
"""

import argparse
import requests
import json
from typing import Optional


BASE_URL = "http://localhost:8000"


def test_sms(phone: str, message: str) -> bool:
    """Test sending an SMS directly."""
    print(f"📱 Testing SMS alert to {phone}...")
    print(f"Message: {message}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/send-sms",
            json={"phone": phone, "message": message},
            timeout=10
        )
        result = response.json()
        
        if response.ok and result.get("success"):
            print(f"✅ SMS sent successfully!")
            print(f"   Quota remaining: {result.get('quotaRemaining', 'N/A')}")
            return True
        else:
            print(f"❌ SMS failed: {result.get('detail', result.get('error', 'Unknown error'))}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Error: {e}")
        return False


def get_test_arbitrage() -> Optional[dict]:
    """Get a mock arbitrage play for testing."""
    print("🔍 Fetching test arbitrage play...")
    
    try:
        response = requests.get(f"{BASE_URL}/api/test-arbitrage-alert", timeout=10)
        data = response.json()
        
        if response.ok and data.get("plays") and len(data["plays"]) > 0:
            play = data["plays"][0]
            print(f"✅ Test arbitrage play found:")
            print(f"   Sport: {play['sport_key']}")
            print(f"   Matchup: {play['matchup']}")
            print(f"   Outcome: {play['outcome_name']}")
            print(f"   Book Odds: {play['book_price']}")
            print(f"   Hedge Odds: {play['novig_reverse_price']}")
            print(f"   Arbitrage Margin: {play['arb_margin_percent']}%")
            print(f"   Is Arbitrage: {play['is_arbitrage']}")
            return play
        else:
            print("❌ No test play returned")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Error: {e}")
        return None


def test_full_flow(phone: str) -> bool:
    """Test the complete watcher alert flow."""
    print("🔄 Testing full alert flow...")
    print()
    
    # Step 1: Get test arbitrage play
    play = get_test_arbitrage()
    if not play:
        return False
    
    print()
    
    # Step 2: Format message (same as watcher does)
    sport_labels = {
        "basketball_nba": "NBA",
        "americanfootball_nfl": "NFL",
        "basketball_ncaab": "NCAAB",
        "americanfootball_ncaaf": "NCAAF"
    }
    
    sport_label = sport_labels.get(play["sport_key"], play["sport_key"])
    team_name = play["outcome_name"]
    
    def format_odds(odds: int) -> str:
        if odds > 0:
            return f"+{odds}"
        return str(odds)
    
    margin = round(play["arb_margin_percent"] * 100) / 100
    book_odds = format_odds(play["book_price"])
    hedge_odds = format_odds(play["novig_reverse_price"]) if play["novig_reverse_price"] else "N/A"
    
    message = (
        f"Hedge Alert! {sport_label}: {team_name} {book_odds} vs {hedge_odds} "
        f"({margin}% margin). {play.get('matchup', '')}"
    )
    
    print(f"📝 Formatted message:")
    print(f"   {message}")
    print()
    
    # Step 3: Send SMS
    return test_sms(phone, message)


def main():
    parser = argparse.ArgumentParser(
        description="Test the arbitrage watcher text feature"
    )
    parser.add_argument(
        "--phone",
        type=str,
        required=True,
        help="Phone number to send test SMS to (e.g., 5551234567)"
    )
    parser.add_argument(
        "--test-mock",
        action="store_true",
        help="Just test getting a mock arbitrage play (no SMS)"
    )
    parser.add_argument(
        "--full-flow",
        action="store_true",
        help="Test the complete flow: get mock play and send SMS"
    )
    parser.add_argument(
        "--message",
        type=str,
        help="Custom message to send (for direct SMS test)"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )
    
    args = parser.parse_args()
    
    global BASE_URL
    BASE_URL = args.base_url
    
    print("🧪 Arbitrage Watcher Text Feature Test")
    print("=" * 50)
    print()
    
    if args.test_mock:
        # Just test getting the mock play
        get_test_arbitrage()
    elif args.full_flow:
        # Test complete flow
        test_full_flow(args.phone)
    else:
        # Test SMS directly
        message = args.message or "Hedge Alert! NBA: Lakers -105 vs +105 (2.5% margin). Lakers @ Warriors"
        test_sms(args.phone, message)
    
    print()
    print("=" * 50)
    print("Test complete!")


if __name__ == "__main__":
    main()





