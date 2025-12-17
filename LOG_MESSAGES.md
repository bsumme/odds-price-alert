# Player props log and warning reference

When the player props endpoint fetches odds for each event, the backend logs the
API calls and responses. A typical sequence:

- `Player props API returned ...` indicates how many events were collected for
the requested sport and markets after all event-level calls complete.
- `Calling event odds for player props` lines show each request to The Odds API
for a specific event, including the markets and bookmakers requested.
- If The Odds API responds with HTTP 422 because a market is not supported for
that sport, `_parse_invalid_markets` extracts the rejected market keys. The
logger then emits `WARNING: Retrying player props for event ... without invalid
markets: ...` and immediately retries the call with those markets removed.
- The follow-up `Event odds API response for player props` line captures the
response status and body for the retried request.

These warnings are expected when The Odds API rejects a specific market (for
example `player_saves` on NHL events). They document the automatic retry path
that preserves valid markets instead of failing the entire player props fetch.
