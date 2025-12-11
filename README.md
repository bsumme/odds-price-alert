# Odds Price Alert - Arbitrage Bet Finder

A web application for finding arbitrage betting opportunities by comparing odds across different sportsbooks using The Odds API.

## Features

- **Arbitrage Finder**: Search across multiple sports and markets to find arbitrage opportunities
- **Value Plays**: Compare odds between sportsbooks to identify value bets
- **Bet Watcher**: Track specific teams/lines across multiple books with real-time updates
- **Decimal/American Odds Toggle**: Switch between odds formats throughout the site
- **Persistent Preferences**: Form selections and preferences are saved using localStorage

## The Odds API

This project uses [The Odds API](https://the-odds-api.com/) v4 to fetch live sports betting odds.
https://app.swaggerhub.com/apis-docs/the-odds-api/odds-api/4#/current%20events/get_v4_sports__sport__scores
### API Overview

The Odds API provides real-time and historical odds data from multiple sportsbooks. The v4 API offers:

- Live odds from major sportsbooks (DraftKings, FanDuel, Novig, Fliff, etc.)
- Multiple sports coverage (NBA, NFL, NCAAB, NCAAF, and more)
- Various markets (moneyline, spreads, totals, props)
- Multiple odds formats (American, Decimal, Fractional)
- Regional support (US, US2, US_EX)

### API Documentation

Official documentation: https://the-odds-api.com/liveapi/guides/v4/#overview

### Getting Started with The Odds API

1. **Sign up for an API key**: Visit https://the-odds-api.com/ to create an account and obtain your API key
2. **Set environment variable**: Set `THE_ODDS_API_KEY` in your environment variables
3. **API Endpoints used in this project**:
   - `GET /v4/sports/{sport_key}/odds` - Fetch odds for a specific sport

### API Request Parameters

The project uses the following parameters when calling The Odds API:

- `apiKey` (required): Your API key
- `regions` (required): Comma-separated list of regions (e.g., "us", "us2", "us_ex")
- `markets` (required): Comma-separated list of markets (e.g., "h2h", "spreads", "totals")
- `oddsFormat` (optional): Format for odds - "american" (default), "decimal", or "fractional"
- `bookmakers` (optional): Comma-separated list of bookmaker keys to filter results

### Supported Sports

- `basketball_nba` - NBA
- `americanfootball_nfl` - NFL
- `basketball_ncaab` - NCAAB
- `americanfootball_ncaaf` - NCAAF

### Supported Markets

- `h2h` - Moneyline/Head-to-Head
- `spreads` - Point Spreads
- `totals` - Over/Under Totals
- `player_points` - Player Props (where available)

### Supported Bookmakers

- `draftkings` - DraftKings (region: us)
- `fanduel` - FanDuel (region: us)
- `novig` - Novig (region: us_ex)
- `fliff` - Fliff (region: us2)

### API Response Structure

The API returns an array of events, each containing:

```json
{
  "id": "event_id",
  "sport_key": "basketball_nba",
  "home_team": "Lakers",
  "away_team": "Warriors",
  "commence_time": "2024-01-20T20:00:00Z",
  "bookmakers": [
    {
      "key": "draftkings",
      "title": "DraftKings",
      "markets": [
        {
          "key": "h2h",
          "outcomes": [
            {
              "name": "Lakers",
              "price": -150
            },
            {
              "name": "Warriors",
              "price": +130
            }
          ]
        }
      ]
    }
  ]
}
```

### Rate Limits

The Odds API has rate limits based on your subscription tier:
- Free tier: Limited requests per month
- Paid tiers: Higher limits

Check your API dashboard for current usage and limits.

### Error Handling

The application handles common API errors:
- Missing API key: Raises RuntimeError with instructions
- API errors: Returns HTTP 502 with error details
- Invalid requests: Returns HTTP 400 with error message

### Dummy Data Mode

For development and testing when API credits are exhausted, the application includes a dummy data mode that generates realistic mock odds data.

## Project Structure

```
odds-price-alert/
├── main.py              # FastAPI backend with API endpoints
├── frontend/
│   ├── BensSportsBookApp.html       # Main home page - Arbitrage Finder
│   ├── value.html       # Value Plays page
│   └── watcher.html     # Bet Watcher page
└── README.md            # This file
```

## Setup

1. **Install dependencies**:
   ```bash
   pip install fastapi uvicorn requests pydantic
   ```

2. **Set environment variable**:
   ```bash
   # Windows PowerShell
   $env:THE_ODDS_API_KEY="your_api_key_here"
   
   # Windows CMD
   set THE_ODDS_API_KEY=your_api_key_here
   
   # Linux/Mac
   export THE_ODDS_API_KEY=your_api_key_here
   ```

3. **Run the server**:
   ```bash
   uvicorn main:app --reload
   ```

4. **Access the application**:
   Open http://localhost:8000 in your browser

5. **Optional: control API trace logging**:
   The backend honors a `TRACE_LEVEL` environment variable when you start `uvicorn`:

   - `regular` (default): suppress request/response tracing and credit tracking logs.
   - `trace`: enable the existing info-level tracing (including persisted API responses).
   - `debug`: log all API calls and responses at debug level.

   ```bash
   # Example: show info-level traces
   TRACE_LEVEL=trace uvicorn main:app --reload
   ```

## Containerized deployment

Builds in the included `Dockerfile` support either a single-container deployment (FastAPI + static assets) or a two-container setup that separates the API and static frontend.

### Single container (API + static files)

```bash
docker build -t odds-price-alert .

# Provide your Odds API key and publish port 8000
docker run -p 8000:8000 -e THE_ODDS_API_KEY=your_api_key odds-price-alert
```

This runs `uvicorn` and serves the `frontend/` HTML directly from the FastAPI app at http://localhost:8000.

### Quick EC2 rebuild script

If you want a one-liner to rebuild and restart the combined image on an EC2 host (or any Docker-capable VM), use `deploy_on_ec2.sh`:

```bash
# From the repo root on your server
export THE_ODDS_API_KEY=your_api_key_here
# Optional overrides:
#   IMAGE_NAME=odds-price-alert \
#   CONTAINER_NAME=odds-price-alert \
#   APP_PORT=8000 \
#   AUTO_FREE_APP_PORT=false   # set to true to auto-stop containers that already publish APP_PORT

./deploy_on_ec2.sh
```

The script stops any existing container with the chosen name, removes old images for the project, rebuilds the Docker image, and starts it with `--restart unless-stopped` so the app stays up across reboots. If port `APP_PORT` is already bound by another process or container, the script will exit with a clear message—either stop the conflicting process or set a different `APP_PORT` before rerunning. For running containers, you can also set `AUTO_FREE_APP_PORT=true` to automatically stop and remove any container that already publishes `APP_PORT` before continuing.

If the port is held by a non-Docker process, the script will show diagnostic commands such as `sudo ss -ltnp 'sport = :<PORT>'` (and `sudo lsof -iTCP:<PORT> -sTCP:LISTEN` if available) so you can identify and stop the blocker. Access the running site at `http://<your-public-ip>:APP_PORT` once the port is free.

### Two-container setup (API + nginx frontend)

```bash
# Build the API image
docker build -t odds-price-alert-api --target api .

# Build the nginx-based static site image
docker build -t odds-price-alert-frontend --target frontend .

# Run the API
docker run -d --name odds-api -p 8000:8000 -e THE_ODDS_API_KEY=your_api_key odds-price-alert-api

# Run the static frontend (adjust port if desired)
docker run -d --name odds-frontend -p 8080:80 odds-price-alert-frontend
```

You can also wire the two containers together with Docker Compose or a reverse proxy (e.g., nginx/Traefik) that routes `/api` traffic to the FastAPI container and everything else to the static frontend.

## Formatting the captured Odds API logs in VS Code

The real API payloads used for dummy data live in `logs/real_odds_api_responses.jsonl`. To make that newline-delimited
JSON file easier to read in VS Code:

1. Open `logs/real_odds_api_responses.jsonl` in VS Code.
2. Change the language mode (bottom right or `Ctrl/Cmd+K M`) to **JSON** so the built-in formatter can run. If you want VS Code to
   remember this for all `.jsonl` files, add the following workspace setting: `"files.associations": { "*.jsonl": "json" }`.
3. Run **Format Document** (`Shift+Alt+F` on Windows/Linux or `Shift+Option+F` on macOS) to pretty-print each line. You can also
   enable `"editor.formatOnSave": true` if you prefer formatting whenever the file is saved.
4. If you prefer a dedicated formatter, install the "JSON Lines" extension from the VS Code marketplace and use **Format Document**
   with that extension active.

Each line remains an independent JSON object after formatting, so downstream processing of the `.jsonl` file still works.

## Quick CLI odds test

Use `tests/test_odds_api.py` to pull raw odds responses (especially for totals) without running the web server. The script hits The Odds API directly and prints either a condensed summary or the full JSON so you can inspect issues with the data.

```bash
# Fetch NBA totals from all configured regions and bookmakers (requires THE_ODDS_API_KEY)
python tests/test_odds_api.py --sport basketball_nba --markets totals --limit 3

# Dump full JSON for debugging
python tests/test_odds_api.py --sport basketball_nba --markets totals --raw

# Use dummy data if you want to test formatting without hitting the network
python tests/test_odds_api.py --sport basketball_nba --markets totals --use-dummy-data
```

## API Endpoints

### `POST /api/odds`
Fetch current odds for specific bets.

**Request Body**:
```json
{
  "bets": [
    {
      "sport_key": "basketball_nba",
      "market": "h2h",
      "team": "Lakers",
      "point": null,
      "bookmaker_keys": ["draftkings", "fanduel"]
    }
  ],
  "use_dummy_data": false
}
```

### `POST /api/value-plays`
Compare a target sportsbook to a comparison book for value plays.

**Request Body**:
```json
{
  "sport_key": "basketball_nba",
  "target_book": "draftkings",
  "compare_book": "novig",
  "market": "h2h",
  "max_results": 25
}
```

### `POST /api/best-value-plays`
Search across multiple sports and markets for best value plays.

**Request Body**:
```json
{
  "sport_keys": ["basketball_nba", "americanfootball_nfl"],
  "markets": ["h2h", "spreads", "totals"],
  "target_book": "draftkings",
  "compare_book": "novig",
  "max_results": 50
}
```

## Features Implementation

### Decimal/American Odds Toggle

The application includes a toggle in the header to switch between American and Decimal odds formats. The preference is saved in localStorage and persists across sessions.

### Form Selection Memory

All form selections (sports, markets, books, etc.) are automatically saved to localStorage and restored when you return to the page.

## Development Notes

- The backend uses FastAPI for the API server
- Frontend is vanilla JavaScript with no framework dependencies
- Data persistence uses browser localStorage (not cookies)
- The application filters out live/started events to only show upcoming games

## License

This project is for personal/educational use. The Odds API has its own terms of service that must be followed.

## Resources

- [The Odds API Documentation](https://the-odds-api.com/liveapi/guides/v4/#overview)
- [The Odds API Website](https://the-odds-api.com/)






