# SMS Text Alert Services Research

## Overview
This document contains research on affordable and easy-to-setup SMS text alert services for future implementation in the odds tracker application.

## Recommended Services (Ranked by Ease of Setup)

### 1. **Twilio** ⭐ Best for Developers
- **Free Trial**: $15.50 credit (enough for ~1,000 SMS messages)
- **Pricing**: ~$0.0075 per SMS in US (very cheap)
- **Setup Difficulty**: Easy-Medium (requires API integration)
- **Pros**:
  - Industry standard, very reliable
  - Excellent documentation and tutorials
  - Python SDK available (perfect for your FastAPI app)
  - Free trial with real credits
- **Cons**:
  - Requires some coding knowledge
  - Need to verify phone numbers initially
- **Best For**: If you're comfortable with API integration
- **Website**: https://www.twilio.com/
- **Integration**: Can be added to `main.py` with their Python SDK

### 2. **Textbelt** ⭐ Simplest API
- **Free Tier**: 1 free SMS per day
- **Pricing**: $0.99 for 100 SMS credits (very cheap)
- **Setup Difficulty**: Very Easy (single API call)
- **Pros**:
  - Extremely simple API (just one HTTP POST request)
  - No account required for free tier
  - Very cheap paid tier
- **Cons**:
  - Limited free tier (1 per day)
  - Less reliable than Twilio
- **Best For**: Quick testing and low-volume alerts
- **Website**: https://textbelt.com/
- **Example**: `curl https://textbelt.com/text --data-urlencode phone='5551234567' --data-urlencode message='Alert!' -d key=textbelt`

### 3. **Plivo**
- **Free Trial**: $10 credit
- **Pricing**: ~$0.0045 per SMS in US (cheapest option)
- **Setup Difficulty**: Easy-Medium
- **Pros**:
  - Cheapest per-message pricing
  - Good free trial
  - Python SDK available
- **Cons**:
  - Less well-known than Twilio
- **Website**: https://www.plivo.com/

### 4. **SimpleTexting**
- **Free Trial**: 14 days
- **Pricing**: Plans start at $29/month
- **Setup Difficulty**: Very Easy (web interface)
- **Pros**:
  - Web-based interface (no coding required)
  - Good for non-technical users
  - Free trial available
- **Cons**:
  - More expensive for low volume
  - Monthly subscription model
- **Best For**: If you prefer a web interface over API
- **Website**: https://simpletexting.com/

### 5. **EZ Texting**
- **Free Trial**: 14 days
- **Pricing**: Pay-as-you-go or monthly plans
- **Setup Difficulty**: Very Easy (web interface)
- **Pros**:
  - User-friendly web interface
  - Upload contacts via CSV
  - Good customer support
- **Cons**:
  - More expensive than API-based services
- **Website**: https://www.eztexting.com/

## Implementation Recommendations

### For Quick Testing (Low Volume)
**Use Textbelt** - It's the simplest to test with. You can send 1 free SMS per day without any account setup.

### For Production (Recommended)
**Use Twilio** - Best balance of:
- Reliability
- Cost (~$0.0075 per SMS)
- Ease of integration with Python/FastAPI
- Free trial with $15.50 credit

### Integration Steps for Twilio (Future Implementation)

1. **Sign up for Twilio**:
   - Go to https://www.twilio.com/try-twilio
   - Get $15.50 free credit

2. **Get credentials**:
   - Account SID
   - Auth Token
   - Phone number (free trial number provided)

3. **Install Python SDK**:
   ```bash
   pip install twilio
   ```

4. **Add to your FastAPI app**:
   ```python
   from twilio.rest import Client
   
   # In your alert function
   account_sid = os.getenv("TWILIO_ACCOUNT_SID")
   auth_token = os.getenv("TWILIO_AUTH_TOKEN")
   from_number = os.getenv("TWILIO_PHONE_NUMBER")
   
   client = Client(account_sid, auth_token)
   client.messages.create(
       body=f"Value Play Alert: {team_name} at {bookmaker} - {price}",
       from_=from_number,
       to="+1234567890"  # Your phone number
   )
   ```

## Cost Comparison (US SMS)

| Service | Free Trial | Cost per SMS | Best For |
|---------|-----------|--------------|----------|
| Twilio | $15.50 credit | ~$0.0075 | Production use |
| Textbelt | 1/day free | $0.0099 | Quick testing |
| Plivo | $10 credit | ~$0.0045 | Lowest cost |
| SimpleTexting | 14 days | $29+/month | Web interface |
| EZ Texting | 14 days | Varies | Web interface |

## Next Steps

1. **Current Implementation**: Window popup + sound alerts are now active in `watcher.html`
2. **Future Enhancement**: Add SMS alerts using one of the services above
3. **Recommended**: Start with Twilio for production, or Textbelt for quick testing

## Notes

- All services require phone number verification for security
- US SMS is typically cheapest; international rates vary
- Consider rate limiting to avoid spam
- Store phone numbers securely (environment variables)
- Test thoroughly before going live

